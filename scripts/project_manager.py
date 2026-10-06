#!/usr/bin/env python3
"""Offline inspection and reversible consolidation of Dunker Monitor."""
from __future__ import annotations
import argparse,datetime as dt,hashlib,json,os,secrets,shutil,sqlite3,sys,uuid,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'vendor'))
import yaml
sys.path.insert(0,str(Path(__file__).resolve().parent))
import global_settings

class Problem(ValueError):pass
class Dumper(yaml.SafeDumper):
 def ignore_aliases(self,data):return True

def read_yaml(path):
 try:
  value=yaml.safe_load(path.read_text(encoding='utf-8-sig'))
  if not isinstance(value,dict):raise Problem('Documento não é um objeto YAML: '+path.name)
  return value
 except (yaml.YAMLError,UnicodeError):raise Problem('YAML inválido: '+path.name+'. Consulte o arquivo local; nenhum segredo foi incluído na mensagem.') from None

def dump(value):return yaml.dump(value,Dumper=Dumper,sort_keys=False,allow_unicode=True).encode()
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def volume_target(value):
 if isinstance(value,dict):return value.get('target','')
 chunks=value.split(':');return chunks[-2] if chunks[-1] in ('ro','rw') else chunks[-1]

def merge(a,b):
 if isinstance(a,dict) and isinstance(b,dict):
  result=dict(a)
  for key,value in b.items():
   if key=='volumes' and isinstance(value,list) and isinstance(result.get(key),list):
    targets={volume_target(v) for v in value};result[key]=[v for v in result[key] if volume_target(v) not in targets]+value
   else:result[key]=merge(result[key],value) if key in result else value
  return result
 return b

def current_compose(root):
 main=root/'compose.separado.yaml'
 if not main.exists():return None
 value=read_yaml(main)
 for name in ('compose.integracoes.yaml','compose.sharepoint.yaml'):
  if (root/name).exists():value=merge(value,read_yaml(root/name))
 return value

def inspect(root,package,output,stage='antes'):
 expected=json.loads((package/'package-manifest.json').read_text())['files']
 files=[]
 for entry in expected:
  path=root/entry['path'];present=path.is_file()
  files.append({'arquivo':entry['path'],'estado':'ausente' if not present else ('igual ao pacote' if digest(path)==entry['sha256'] else 'existente / diferente'),'acao_prevista':entry['mode']})
 inventory=root/'config/targets/inventory.json';counts={}
 try:
  data=json.loads(inventory.read_text());counts={'verificacoes':sum(r.get('tipo') in ('icmp','http','tcp','dns') for r in data),'equipamentos_snmp':sum(bool(r.get('managed_snmp')) for r in data)}
 except (OSError,ValueError,TypeError):counts={'estado':'inventário ausente ou formato não reconhecido'}
 sharepoint_db=root/'config/sharepoint/private/sharepoint.sqlite3'
 try:
  if sharepoint_db.is_file():
   with sqlite3.connect('file:'+str(sharepoint_db)+'?mode=ro',uri=True) as db:counts['integracoes_sharepoint']=db.execute('SELECT COUNT(*) FROM tenants').fetchone()[0]
 except sqlite3.Error:counts['integracoes_sharepoint']='não foi possível consultar'
 secret_cfg=json.loads((root/'config/global/credentials.json').read_text()).get('system',{}) if (root/'config/global/credentials.json').exists() else {}
 secrets_status={name:bool(secret_cfg.get(name)) for name in ('grafana_admin_password','grafana_secret_key','ingest_password','snmp_community')}
 try:compose=current_compose(root);services=list((compose or {}).get('services',{}));project=(compose or {}).get('name')
 except Problem:services=[];project=None
 report={'pacote':'1.0.0','etapa':stage,'horario_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'pasta':str(root),'nome_compose':project,'servicos_definidos':services,'arquivos':files,'inventario':counts,'arquivos_de_credenciais_presentes':secrets_status,'rota_monitoramento':(root/'config/caddy/Caddyfile').is_file() and '/monitoramento/*' in (root/'config/caddy/Caddyfile').read_text(),'observacao':'Inspeção de arquivos. O relatório Docker separado contém containers e caminhos reais. Não inclui senhas nem conteúdo do inventário.'}
 output.mkdir(parents=True,exist_ok=True);(output/f'arquivos-{stage}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 lines=['DUNKER MONITOR — REVISÃO '+stage.upper(),'Pacote: 1.0.0','Pasta: '+str(root),'Serviços definidos: '+', '.join(services),'Arquivos ausentes: '+str(sum(f['estado']=='ausente' for f in files)),'Arquivos diferentes: '+str(sum(f['estado']=='existente / diferente' for f in files)),'','Inventário (somente contagens): '+json.dumps(counts,ensure_ascii=False),'Credenciais: somente presença dos arquivos, sem valores.','','Detalhes de arquivos:']
 lines += [f"{f['estado']} | {f['acao_prevista']} | {f['arquivo']}" for f in files]
 (output/f'arquivos-{stage}.txt').write_text('\n'.join(lines)+'\n')
 print('Revisão '+stage+': '+str(sum(f['estado']=='ausente' for f in files))+' arquivos ausentes. Relatório em '+str(output))

def compose_update(root,package,compose_name=None):
 canonical=read_yaml(package/'compose.separado.yaml');current=current_compose(root)
 if current is None:
  if compose_name:canonical['name']=compose_name
  return canonical
 if not all(k in current.get('services',{}) for k in ('grafana','prometheus','caddy')):raise Problem('Compose sem os serviços grafana/prometheus/caddy esperados. Nenhum arquivo alterado.')
 value=merge(current,canonical)
 # Preserve names, bind ports and storage identities from the existing installation.
 value['name']=compose_name or current.get('name') or root.name.lower().replace(' ','-')
 for name,original in current['services'].items():
  target=value['services'][name]
  for key in ('ports','networks','container_name','labels','profiles'):
   if key in original:target[key]=original[key]
  if 'environment' in original:
   env=original['environment']
   if isinstance(env,list):env=dict(v.split('=',1) if '=' in v else (v,None) for v in env)
   new=target.get('environment',{})
   target['environment']={**new,**env}
   # Explicitly enable only our local plugin, retaining any existing allowlist.
   if name=='grafana':
    configured=str(env.get('GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS',''))
    ids=[v.strip() for v in configured.split(',') if v.strip()]
    if 'dunker-integracoes-app' not in ids:ids.append('dunker-integracoes-app')
    target['environment']['GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS']=','.join(ids)
  # Named volume sources must stay unchanged; refresh only our source-code mounts.
  if 'volumes' in original:
   mounts=[v for v in target.get('volumes',[]) if name not in ('admin','ping') or not volume_target(v).startswith('/opt/dunker/')]
   source_code={'/opt/dunker'}
   for old in original['volumes']:
    dest=volume_target(old)
    if dest in source_code or dest.startswith('/opt/dunker/'):continue
    mounts=[v for v in mounts if volume_target(v)!=dest]+[old]
   target['volumes']=mounts
  if name=='admin':
   target.pop('ports',None)
  if name=='prometheus' and 'command' in original:
   # Preserve existing retention and other flags; reload the managed config path.
   command=original['command']
   if not isinstance(command,list):raise Problem('Prometheus usa command textual; adapte para uma lista antes da atualização.')
   target['command']=command
 value['services'].pop('sharepoint-prometheus',None)
 value['services'].pop('blackbox',None)
 # Canonical mounts and config interfaces, preserving volume identities.
 for name in ('grafana','admin','sharepoint'):
  target=value['services'][name];reference=canonical['services'][name]
  target['depends_on']=reference.get('depends_on',[])
  if name=='admin':target.get('environment',{}).pop('BLACKBOX_URL',None);target.get('environment',{}).pop('ADMIN_PASSWORD_FILE',None)
  for key in ('environment','volumes'):
   if key=='environment':target[key]={**target.get(key,{}),**reference.get(key,{})}
   else:
    targets={volume_target(v) for v in reference.get(key,[])}
    target[key]=[v for v in target.get(key,[]) if volume_target(v) not in targets]+reference.get(key,[])
 # Keep custom root fields and volume declarations/options from the original.
 for key in ('networks','secrets','configs'):
  if key in current:value[key]=current[key]
 for key,definition in current.get('volumes',{}).items():value['volumes'][key]=definition
 return value

def merge_groups(existing,new):
 definitions={g['name']:g for g in new.get('groups',[])}
 result=[];added=set()
 for group in existing.get('groups',[]):
  name=group['name']
  if name in definitions:
   if name not in added:result.append(definitions[name]);added.add(name)
  else:result.append(group)
 for name,group in definitions.items():
  if name not in added:result.append(group)
 return {'groups':result}

def prometheus_update(root,package):
 canonical=read_yaml(package/'config/prometheus/separado.yml');target=root/'config/prometheus/separado.yml'
 if not target.exists():return canonical
 old=read_yaml(target);value=merge(old,canonical)
 if 'global' in old:value['global']=old['global']
 if 'alerting' in old:value['alerting']=old['alerting']
 jobs={job['job_name']:job for job in canonical['scrape_configs']}
 value['scrape_configs']=[jobs.pop(job['job_name'],job) for job in old.get('scrape_configs',[]) if not job['job_name'].startswith(('blackbox_','exporter_blackbox'))]+list(jobs.values())
 managed={'/etc/dunker/prometheus/rules.yml','/etc/dunker/prometheus/integracoes.yml','/etc/dunker/prometheus/regras-links.yml'}
 extra=[v for v in old.get('rule_files',[]) if v not in managed]
 if any('*' in v or '?' in v or '[' in v for v in extra):raise Problem('rule_files usa um padrão de arquivos; revise o padrão para evitar grupos duplicados antes de atualizar.')
 value['rule_files']=['/etc/dunker/prometheus/rules.yml']+extra
 return value

def caddy_update(text):
 if '/monitoramento/*' in text:return text
 import re
 pattern=r'(?m)^(\s*)handle\s*\{\s*\n\s*reverse_proxy\s+\{\$GF_UPSTREAM\}'
 match=re.search(pattern,text)
 if not match:raise Problem('Caddyfile personalizado sem a rota de monitoramento reconhecível. Nenhum arquivo alterado.')
 indent=match[1]
 insertion=indent+'redir /monitoramento /monitoramento/ 308\n'+indent+'handle_path /monitoramento/* {\n'+indent+'\treverse_proxy {$ADMIN_UPSTREAM}\n'+indent+'}\n'
 return text[:match.start()]+insertion+text[match.start():]

def write(path,body,private=False):
 missing=[];parent=path.parent
 while not parent.exists():missing.append(parent);parent=parent.parent
 path.parent.mkdir(parents=True,exist_ok=True)
 for folder in missing:os.chmod(folder,0o700 if '/private' in folder.as_posix() or '/backups/' in folder.as_posix() else 0o755)
 existed=path.exists();fd,temporary=tempfile.mkstemp(dir=path.parent)
 with os.fdopen(fd,"wb") as stream:stream.write(body)
 os.chmod(temporary,0o600 if private else 0o644);os.replace(temporary,path)
 if private:os.chmod(path,0o600)
 elif not existed:os.chmod(path,0o644)
 # Grafana's unprivileged container must read its two bootstrap files.
 if private and path.name in ('grafana_admin_password','grafana_secret_key'):os.chmod(path,0o444)

def apply(root,package,new=False,compose_name=None):
 if root==package:raise Problem('Extraia o pacote em uma pasta separada da instalação; use -Projeto para apontar ao servidor.')
 if not new and not (root/'compose.separado.yaml').exists():raise Problem('Projeto existente não localizado nessa pasta. Use -NovaInstalacao apenas para uma instalação nova.')
 if new and (root/'compose.separado.yaml').exists():raise Problem('Já existe uma instalação. Execute sem -NovaInstalacao para preservar seus dados.')
 root.mkdir(parents=True,exist_ok=True);os.umask(0o077)
 manifest=json.loads((package/'package-manifest.json').read_text());changes={};private_paths=set()
 # Verify package integrity before changing the installation.
 for entry in manifest['files']:
  src=package/entry['path']
  if digest(src)!=entry['sha256']:raise Problem('Arquivo do pacote alterado: '+entry['path'])
  if entry['mode']=='managed' or not (root/entry['path']).exists():changes[entry['path']]=src.read_bytes()
 changes['compose.separado.yaml']=dump(compose_update(root,package,compose_name))
 changes['config/prometheus/separado.yml']=dump(prometheus_update(root,package))
 rules=root/'config/prometheus/rules.yml';canonical=read_yaml(package/'config/prometheus/rules.yml')
 changes['config/prometheus/rules.yml']=dump({'groups':[g for g in read_yaml(rules).get('groups',[]) if not g['name'].startswith('dunker-')]+canonical['groups']} if rules.exists() else canonical)
 # Do not let the admin bootstrap erase legacy probes when inventory is missing.
 inventory=root/'config/targets/inventory.json'
 if inventory.exists():
  try:rows=json.loads(inventory.read_text())
  except (ValueError,UnicodeError):raise Problem('Inventário existente inválido; restaure config/targets/inventory.json antes da atualização.') from None
  if not isinstance(rows,list):raise Problem('Inventário existente inválido: lista esperada. Nenhum arquivo alterado.')
 else:
  legacy=root/'config/inventory.json'
  if legacy.exists() and isinstance(json.loads(legacy.read_text()),list) and json.loads(legacy.read_text()):
   changes['config/targets/inventory.json']=legacy.read_bytes()
  else:
   for kind in ('icmp','http','tcp'):
    p=root/'config/targets'/f'{kind}.json'
    if p.exists() and json.loads(p.read_text()):raise Problem('Inventário ausente com alvos ativos. Restaure config/targets/inventory.json do backup antes de aplicar, para preservar parâmetros dos monitores.')

 # Preserve current listener, TLS and ingress hash; add only a missing central route.
 caddy=root/'config/caddy/Caddyfile'
 if caddy.exists():
  updated=caddy_update(caddy.read_text())
  if updated!=caddy.read_text():changes['config/caddy/Caddyfile']=updated.encode();private_paths.add('config/caddy/Caddyfile')
 else:
  changes['config/caddy/Caddyfile']=(package/'config/caddy/Caddyfile.example').read_bytes();private_paths.add('config/caddy/Caddyfile')
  changes['config/secrets/ingest_hash.pending']=b'Generate Caddy ingress hash before startup.\n';private_paths.add('config/secrets/ingest_hash.pending')
 if not (root/'.env').exists():
  changes['.env']=(package/'.env.example').read_bytes();private_paths.add('.env')
 for folder in ('config/integracoes/private','config/sharepoint/private','config/access/private'):
  path=root/folder
  if not path.exists():
   path.mkdir(parents=True,exist_ok=True);os.chmod(path,0o700)
   for parent in (path.parent,path.parent.parent):
    if parent.exists():os.chmod(parent,0o755)
 snmp='config/integracoes/private/snmp-managed.yml'
 if not (root/snmp).exists():changes[snmp]=(package/'config/integracoes/snmp-managed.example').read_bytes();private_paths.add(snmp)
 ignore=(root/'.gitignore').read_text() if (root/'.gitignore').exists() else ''
 for line in (package/'.gitignore').read_text().splitlines():
  if line and line not in ignore.splitlines():ignore=ignore.rstrip()+'\n'+line+'\n'
 changes['.gitignore']=ignore.encode()
 for relative in list(changes):
  if relative.startswith('config/secrets/') or relative=='config/sharepoint/private/gateway_token':changes.pop(relative)
 changes['package-manifest.json']=(package/'package-manifest.json').read_bytes()
 global_changes,removals=global_settings.plan(root,package,changes)
 changes.update(global_changes)
 for relative in ('config/snmp.yml','config/integracoes/private/snmp-managed.yml','config/targets/snmp.json'):
  if relative not in changes and (root/relative).exists():changes[relative]=(root/relative).read_bytes()
 if not (root/'config/snmp.yml').exists():
  config=read_yaml(package/'config/snmp.yml.example');config['auths']['dunker_v2']['community']=json.loads(global_changes['config/global/credentials.json'])['system']['snmp_community'];changes['config/snmp.yml']=dump(config)
 private_paths.update(k for k in global_changes if k.startswith(('config/global/credentials','config/generated/','config/caddy/')))
 removals += manifest.get('obsolete_files',[])
 removals=[r for r in dict.fromkeys(removals) if r not in changes and (root/r).is_file()]
 # Unknown targets, credentials and files stay outside this managed mutation set.
 backup='backups/completo-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
 record={'versao':'1.0.0','backup':backup,'files':[]}
 try:
  for relative,body in changes.items():
   target=root/relative;saved=root/backup/relative;existed=target.is_file()
   if existed:saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
   record['files'].append({'target':relative,'backup':saved.relative_to(root).as_posix(),'existed':existed})
   write(target,body,relative in private_paths)
  for relative in removals:
   target=root/relative;saved=root/backup/relative
   saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
   record['files'].append({'target':relative,'backup':saved.relative_to(root).as_posix(),'existed':True});target.unlink()
  global_settings.sync(root)
  path=root/backup/'manifest.json';write(path,(json.dumps(record,indent=2)+'\n').encode(),True)
  write(root/'.dnk-install-state.json',(json.dumps({'backup_manifest':str(path.relative_to(root))})+'\n').encode(),True)
 except Exception:
  restore(root,record);raise
 print('Projeto completo 1.0.0 preparado. Backup: '+backup)

def restore(root,record):
 for item in reversed(record['files']):
  target=root/item['target']
  if item['existed']:target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/item['backup'],target)
  elif target.is_file() and not item['target'].startswith(('config/secrets/','config/integracoes/private/','config/sharepoint/private/','config/access/private/')):target.unlink()
 ignore=root/'.gitignore';text=ignore.read_text() if ignore.exists() else ''
 for line in ('config/secrets/','config/integracoes/private/','config/sharepoint/private/','config/access/private/','backups/','.dnk-install-state.json'):
  if line not in text.splitlines():text=text.rstrip()+'\n'+line+'\n'
 ignore.write_text(text)

def rollback(root):
 state=json.loads((root/'.dnk-install-state.json').read_text());record=json.loads((root/state['backup_manifest']).read_text());restore(root,record)
 print('Arquivos restaurados. Segredos e dados privados foram preservados. Não foram removidos volumes Docker.')

def finalize_hash(root):
 p=root/'config/generated/ingest_hash';bcrypt=p.read_text().strip()
 if not bcrypt.startswith(('$2a$','$2b$','$2y$')) or len(bcrypt)!=60:raise Problem('Hash de ingestão inválido')
 cfg_path=root/'config/global/credentials.json';cfg=json.loads(cfg_path.read_text());cfg['system']['ingest_hash']=bcrypt
 write(cfg_path,(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n').encode(),True)
 global_settings.sync(root)
 for file in ('ingest_hash','ingest_hash.pending'):
  p=root/'config/generated'/file
  if p.exists():p.unlink()
 print('Autenticação de ingestão preparada a partir do arquivo global.')

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('action',choices=['inspect','apply','rollback','finalize-hash']);parser.add_argument('--project',required=True);parser.add_argument('--package',default=str(Path(__file__).resolve().parents[1]));parser.add_argument('--output');parser.add_argument('--stage',default='antes');parser.add_argument('--new',action='store_true');parser.add_argument('--compose-name');a=parser.parse_args()
 root=Path(a.project).resolve();package=Path(a.package).resolve()
 try:
  if a.action=='inspect':inspect(root,package,Path(a.output or str(root/'diagnostico')),a.stage)
  elif a.action=='apply':apply(root,package,a.new,a.compose_name)
  elif a.action=='rollback':rollback(root)
  else:finalize_hash(root)
 except (Problem,OSError,ValueError,KeyError) as exc:
  print(str(exc) if isinstance(exc,Problem) else 'Falha na preparação dos arquivos. Confira formato, permissões e espaço no projeto.',file=sys.stderr);raise SystemExit(1)
