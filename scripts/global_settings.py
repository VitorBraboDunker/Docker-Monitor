"""Read legacy secrets once; render adapters from the global source of truth."""
import json, os, re, secrets, sqlite3, uuid,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'vendor'))
SYSTEM_KEYS=('grafana_admin_password','grafana_secret_key','ingest_password','snmp_community')

def plan(root,package,pending=None):
    pending=pending or {}
    changes={};remove=[]
    source=root/'config/global/credentials.json'
    cfg=json.loads(source.read_text()) if source.exists() else {'system':{},'snmp':{},'sharepoint':{}}
    system=cfg.setdefault('system',{})
    old=root/'config/secrets/credentials.json'
    legacy=json.loads(old.read_text()) if old.exists() else {}
    for key in SYSTEM_KEYS:
        file=root/'config/secrets'/key
        system.setdefault(key,file.read_text().strip() if file.exists() else legacy.get(key) or secrets.token_urlsafe(36))
    token=root/'config/sharepoint/private/gateway_token'
    system.setdefault('gateway_token',token.read_text().strip() if token.exists() else secrets.token_urlsafe(48))
    auth=root/'config/integracoes/private/credentials.json'
    if auth.exists():
        for key,value in json.loads(auth.read_text()).items():cfg.setdefault('snmp',{}).setdefault(key,value)
    dbpath=root/'config/sharepoint/private/sharepoint.sqlite3'
    if dbpath.exists():
        with sqlite3.connect('file:'+str(dbpath)+'?mode=ro',uri=True) as db:
            for ident,secret in db.execute('SELECT id,secret FROM tenants'):
                if secret:cfg.setdefault('sharepoint',{}).setdefault(ident,secret)
    import yaml
    legacy_snmp=root/'config/snmp.yml'
    if legacy_snmp.exists() and not source.exists():
        for key,value in (yaml.safe_load(legacy_snmp.read_text()) or {}).get('auths',{}).items():cfg.setdefault('snmp_legacy',{}).setdefault(key,value)
    # Existing hashes from Caddy remain valid; secret is preserved, not rotated.
    hashfile=root/'config/secrets/ingest_hash'
    caddy=root/'config/caddy/Caddyfile'
    match=re.search(r'\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}',caddy.read_text()) if caddy.exists() else None
    system.setdefault('ingest_hash',hashfile.read_text().strip() if hashfile.exists() else match[0] if match else '')
    changes['config/global/credentials.json']=(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n').encode()
    for key in SYSTEM_KEYS:changes['config/generated/'+key]=(system[key]+'\n').encode()
    if not system['ingest_hash']:changes['config/generated/ingest_hash.pending']=b'Generate hash before startup.\n'
    env={}
    if (root/'.env').exists():
        env={line.split('=',1)[0]:line.split('=',1)[1] for line in (root/'.env').read_text().splitlines() if '=' in line and not line.startswith('#')}
    domainpath=root/'config/global/domains.json'
    domains=json.loads(domainpath.read_text()) if domainpath.exists() else {'access':{'host':env.get('MONITOR_HOST','172.16.27.51'),'bind':env.get('ACCESS_BIND','0.0.0.0'),'port':int(env.get('ACCESS_PORT','8443')),'tls_mode':'http','public_url':'http://'+env.get('MONITOR_HOST','172.16.27.51')+':'+env.get('ACCESS_PORT','8443')},'certificates':{'email':'','cert_file':'','key_file':''},'checks':[],'VM_NAME':env.get('VM_NAME','SRV-DUNKER'),'SYSLOG_BIND':env.get('SYSLOG_BIND','127.0.0.1'),'GRAFANA_ORG_ID':int(env.get('GRAFANA_ORG_ID','1'))}
    if not domainpath.exists():domains['checks']=[{'name':'Acesso Dunker','host':domains['access']['host'],'port':domains['access']['port'],'tls':domains['access']['tls_mode']!='http','enabled':True}]
    if not domainpath.exists() and caddy.exists() and 'https://' in caddy.read_text():
        domains['access']['tls_mode']='internal' if 'tls internal' in caddy.read_text() else 'acme'
        domains['access']['public_url']='https://'+domains['access']['host']+':'+str(domains['access']['port'])
        domains['checks'][0]['tls']=True
    changes.update(render(domains,system))
    changes['config/global/domains.json']=(json.dumps(domains,ensure_ascii=False,indent=2)+'\n').encode()
    if not (root/'config/global/status.json').exists():changes['config/global/status.json']=(package/'config/global/status.json').read_bytes()
    for path in list((root/'config/secrets').glob('*'))+[auth,token]:
        if path.is_file():remove.append(path.relative_to(root).as_posix())
    # Canonical IDs and required identifiers, preserving deletion records and pause state.
    inventory=root/'config/targets/inventory.json'
    if inventory.exists() or 'config/targets/inventory.json' in pending:
        rows=json.loads(inventory.read_text()) if inventory.exists() else json.loads(pending['config/targets/inventory.json'])
        for row in rows:
            for old,new in (('Cliente','CLIENTE'),('Unidade','UNIDADE')):
                if old in row:row.setdefault(new,row.pop(old))
            if not row.get('CLIENTE') or not row.get('UNIDADE'):raise ValueError('Ativo sem CLIENTE/UNIDADE: preencha o inventário antes de migrar')
            row.setdefault('id',str(uuid.uuid5(uuid.NAMESPACE_URL,'dunker:'+row['tipo']+':'+row['CLIENTE']+':'+row['UNIDADE']+':'+row['instance'])))
            row.setdefault('name',row['instance']);row.setdefault('enabled',True)
        if not any(r.get('tipo') in ('linux','windows') and r.get('instance')==domains.get('VM_NAME','SRV-DUNKER') and r.get('CLIENTE')=='DunkerIT' for r in rows):
            rows.append({'id':str(uuid.uuid5(uuid.NAMESPACE_URL,'dunker:central:'+domains.get('VM_NAME','SRV-DUNKER'))),'name':domains.get('VM_NAME','SRV-DUNKER'),'instance':domains.get('VM_NAME','SRV-DUNKER'),'tipo':'linux','CLIENTE':'DunkerIT','UNIDADE':'Central','Provedor':'Interno','enabled':True,'items':['cpu','memory','disk']})
        changes['config/targets/inventory.json']=(json.dumps(rows,ensure_ascii=False,indent=2)+'\n').encode()
        for kind in ('icmp','http','tcp'):
            targets=[{'targets':[r['instance']],'labels':{k:r[k] for k in ('CLIENTE','UNIDADE','Provedor')}|{'monitor_id':r['id'],'monitor_name':r['name']}} for r in rows if r['tipo']==kind and r.get('enabled',True) and not r.get('deleted_at') and kind=='icmp']
            changes['config/targets/'+kind+'.json']=(json.dumps(targets,ensure_ascii=False,indent=2)+'\n').encode()
    return changes,remove

def render(domains,system):
    access=domains['access'];mode=access.get('tls_mode','http')
    if mode not in ('http','internal','acme','manual'):raise ValueError('tls_mode inválido')
    host=access['host'];port=int(access['port'])
    if not re.fullmatch(r'[A-Za-z0-9.-]+',host) or not 1<=port<=65535:raise ValueError('Host/porta inválidos')
    public=access['public_url']
    from urllib.parse import urlsplit
    url=urlsplit(public)
    if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):raise ValueError('URL pública inválida')
    if (mode=='http')!=(url.scheme=='http'):raise ValueError('URL pública e modo TLS não correspondem')
    for key in ('bind',):
        import ipaddress
        ipaddress.ip_address(access[key])
    cert=domains.get('certificates',{})
    listener='http://:8443' if mode=='http' else 'https://'+host+':8443'
    directives=''
    if mode=='internal':directives='\ttls internal\n'
    elif mode=='manual':
        files=[cert.get('cert_file',''),cert.get('key_file','')]
        if any(not re.fullmatch(r'/etc/dunker/certificates/[A-Za-z0-9_.-]+',f) for f in files):raise ValueError('Certificados manuais devem estar em /etc/dunker/certificates/')
        directives='\ttls '+files[0]+' '+files[1]+'\n'
    elif mode=='acme':
        email=cert.get('email','')
        if email and not re.fullmatch(r'[^\s{}]+@[^\s{}]+',email):raise ValueError('Email ACME inválido')
        directives='\ttls {\n\t\tissuer acme {\n\t\t\tdisable_http_challenge\n'+('\t\t\temail '+email+'\n' if email else '')+'\t\t}\n\t}\n'
    hashvalue=system.get('ingest_hash') or '{$INGEST_HASH}'
    template='''{\n admin off\n skip_install_trust\n auto_https disable_redirects\n}\nLISTENER {\nDIRECTIVES
 redir /monitoramento /monitoramento/ 308
 @private path /monitoramento/metrics /monitoramento/healthz
 respond @private 404
 handle_path /monitoramento/* {\n  reverse_proxy {$ADMIN_UPSTREAM}\n }
 handle /api/v1/write {
  basic_auth {\n   alloy_ingest HASH\n  }
  @write_not_post not method POST
  respond @write_not_post 405
  reverse_proxy {$PROM_UPSTREAM} {\n   header_up -Authorization\n  }
 }
 handle /loki/api/v1/push {
  basic_auth {\n   alloy_ingest HASH\n  }
  @logs_not_post not method POST
  respond @logs_not_post 405
  reverse_proxy {$LOKI_UPSTREAM} {\n   header_up -Authorization\n  }
 }
 handle {\n  reverse_proxy {$GF_UPSTREAM}\n }
}\n'''
    if mode=='acme':template=template.replace(' admin off',' admin off\n https_port 8443')
    caddy=template.replace('LISTENER',listener).replace('DIRECTIVES',directives).replace('HASH',hashvalue)
    # .env is generated public adapter; do not store secrets in it.
    values={'MONITOR_HOST':host,'ACCESS_BIND':access['bind'],'ACCESS_PORT':str(port),'VM_NAME':domains.get('VM_NAME','SRV-DUNKER'),'SYSLOG_BIND':domains.get('SYSLOG_BIND','127.0.0.1'),'GRAFANA_ORG_ID':str(domains.get('GRAFANA_ORG_ID',1))}
    if any('\n' in str(v) or '\r' in str(v) for v in values.values()):raise ValueError('Configuração contém quebra de linha inválida')
    return {'config/caddy/Caddyfile':caddy.encode(),'.env':('# Gerado de config/global/domains.json\n'+'\n'.join(k+'='+str(v) for k,v in values.items())+'\n').encode()}

def render_snmp(root,cfg):
    import sys,yaml
    sys.path.insert(0,str(root/'runtime'))
    import snmp_manager as snmp
    snmp.CONFIG=root/'config';snmp.MODULES=root/'config/integracoes/modules.json'
    rows=json.loads((root/'config/targets/inventory.json').read_text())
    document=snmp.document(rows,cfg.get('snmp',{}))
    path=root/'config/integracoes/private/snmp-managed.yml';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(snmp.exporter_yaml(document)+'\n');os.chmod(path,0o600)
    path=root/'config/targets/snmp.json'
    legacy=json.loads(path.read_text()) if path.exists() else []
    for target in legacy:
        for old,new in (('Cliente','CLIENTE'),('Unidade','UNIDADE')):
            if old in target.get('labels',{}):target['labels'].setdefault(new,target['labels'].pop(old))
    path.write_text(json.dumps(snmp.targets(rows,legacy),ensure_ascii=False,indent=2)+'\n');os.chmod(path,0o644)
    template=yaml.safe_load((root/'config/snmp.yml.example').read_text())
    template['auths']=cfg.get('snmp_legacy') or {'dunker_v2':{'version':2,'community':cfg['system']['snmp_community']}}
    path=root/'config/snmp.yml';path.write_text(yaml.safe_dump(template,sort_keys=False));os.chmod(path,0o600)

def sync(root):
    for folder in ('config/history','config/excluidos','config/certificates'):
        (root/folder).mkdir(parents=True,exist_ok=True)
    cfg=json.loads((root/'config/global/credentials.json').read_text());domains=json.loads((root/'config/global/domains.json').read_text())
    changes=render(domains,cfg['system'])
    for key in SYSTEM_KEYS:changes['config/generated/'+key]=(cfg['system'][key]+'\n').encode()
    for rel,body in changes.items():
        file=root/rel;file.parent.mkdir(parents=True,exist_ok=True);fd,temp=tempfile.mkstemp(dir=file.parent)
        with os.fdopen(fd,'wb') as stream:stream.write(body)
        os.replace(temp,file);os.chmod(file,0o444 if rel.endswith(('grafana_admin_password','grafana_secret_key')) else 0o600)
    render_snmp(root,cfg)
if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Renderiza arquivos dos serviços a partir dos dois arquivos globais.');parser.add_argument('--project',default=str(Path(__file__).resolve().parents[1]));args=parser.parse_args();sync(Path(args.project))
