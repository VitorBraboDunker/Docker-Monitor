#!/usr/bin/env python3
"""Sanitized Docker inspection: no environment, tokens or inventory contents."""
import argparse,json,subprocess,sys
from pathlib import Path

def run(*args):return subprocess.check_output(['docker',*args],text=True)
def audit(root,output,stage,check=False):
 items=[]
 for cid in run('ps','-aq','--filter','label=com.docker.compose.project').split():
  obj=json.loads(run('inspect',cid))[0];labels=obj['Config'].get('Labels') or {};project=labels.get('com.docker.compose.project','');working=labels.get('com.docker.compose.project.working_dir','')
  if 'dunker' not in project.lower() and working!=str(root):continue
  items.append({'Name':obj['Name'].lstrip('/'),'Image':obj['Config']['Image'],'Status':obj['State']['Status'],'Health':obj['State'].get('Health',{}).get('Status'),'Project':project,'Service':labels.get('com.docker.compose.service'),'WorkingDirectory':working,'ComposeFiles':labels.get('com.docker.compose.project.config_files',''),'Mounts':[{k:m.get(k) for k in ('Type','Source','Destination','Name','RW')} for m in obj['Mounts']],'Ports':obj['NetworkSettings'].get('Ports',{})})
 output.mkdir(parents=True,exist_ok=True)
 (output/f'docker-{stage}.json').write_text(json.dumps(items,ensure_ascii=False,indent=2)+'\n')
 (output/f'docker-{stage}.txt').write_text('\n'.join(['DUNKER MONITOR — DOCKER '+stage]+[f"{r['Name']} | {r['Image']} | {r['Status']} | saúde={r['Health']} | projeto={r['Project']} | pasta={r['WorkingDirectory']}" for r in items])+'\n')
 if not check:return
 matches=[r for r in items if r['WorkingDirectory']==str(root) and r['Service']!='monitor'];other=[r for r in items if r['WorkingDirectory']!=str(root) and r['Status']=='running']
 if not matches and other:raise ValueError('Os containers ativos usam outra pasta: '+other[0]['WorkingDirectory']+'. Use essa pasta como projeto.')
 if any(r['Service']=='monitor' and r['Status']=='running' for r in items):raise ValueError('Modo de container único ativo: migração precisa ser revisada antes de aplicar este pacote de containers separados.')
 names={r['Project'] for r in matches}
 if len(names)>1:raise ValueError('Mais de um projeto Compose usa a pasta; confira o relatório.')
 for r in matches:
  for name in r['ComposeFiles'].split(','):
   if name and Path(name).name not in ('compose.separado.yaml','compose.integracoes.yaml','compose.sharepoint.yaml'):raise ValueError('Compose adicional em uso: '+name+'. Integre esse complemento antes de aplicar.')
 (output/'compose-project-name.txt').write_text(next(iter(names),'')+'\n')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--output',required=True);p.add_argument('--stage',default='antes');p.add_argument('--check',action='store_true');a=p.parse_args()
 try:audit(Path(a.project).resolve(),Path(a.output),a.stage,a.check)
 except (OSError,ValueError,subprocess.CalledProcessError) as e:print(str(e),file=sys.stderr);sys.exit(1)
