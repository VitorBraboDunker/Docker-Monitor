#!/usr/bin/env python3
import argparse,csv,ipaddress,json,os,tempfile
from pathlib import Path
from urllib.parse import urlparse
BASE=Path(__file__).resolve().parents[1];TYPES={'icmp','snmp','http','tcp','windows','linux'};KEYS=['tipo','Cliente','Unidade','Provedor','instance']
def atomic(path,value):
 fd,tmp=tempfile.mkstemp(dir=path.parent,prefix=path.name+'.')
 with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(value,f,indent=2,ensure_ascii=False);f.write('\n')
 os.chmod(tmp,0o644);os.replace(tmp,path)
def load(path):
 with open(path,encoding='utf-8-sig',newline='') as f:
  sample=f.read(4096);f.seek(0);delimiter=';' if ';' in sample.partition('\n')[0] else ',';rows=[];seen=set()
  for line,row in enumerate(csv.DictReader(f,delimiter=delimiter),2):
   row={k:(v or '').strip() for k,v in row.items() if k is not None}
   if not any(row.values()):continue
   if any(not row.get(k) for k in KEYS):raise ValueError(f'Linha {line}: preencha '+', '.join(KEYS))
   if row['tipo'] not in TYPES:raise ValueError(f'Linha {line}: tipo inválido.')
   target=row['instance']
   if row['tipo'] in ['icmp','snmp']:ipaddress.IPv4Address(target)
   if row['tipo']=='http' and (urlparse(target).scheme not in ['https','http'] or not urlparse(target).hostname):raise ValueError(f'Linha {line}: URL inválida.')
   if row['tipo']=='tcp':
    host,sep,port=target.rpartition(':')
    if not host or not sep or not port.isdigit() or not 1<=int(port)<=65535:raise ValueError(f'Linha {line}: use host:porta.')
   if row['tipo']=='snmp':row['auth']=row.get('auth') or 'dunker_v2';row['module']=row.get('module') or 'if_mib,system'
   key=tuple(row[k] for k in KEYS)
   if key in seen:raise ValueError(f'Linha {line}: alvo duplicado.')
   seen.add(key);rows.append(row)
 return rows
if __name__=='__main__':
 p=argparse.ArgumentParser(description='Substitui todo o inventário ativo pelo conteúdo do CSV.');p.add_argument('csv',nargs='?',default=str(BASE/'inventario.csv'));a=p.parse_args()
 try:rows=load(a.csv)
 except (ValueError,OSError) as e:p.error(str(e))
 import sys
 sys.path.insert(0,str(BASE/'runtime'))
 from admin_monitor import normalize
 rows=[normalize(dict(r,name=r.get('name',r['instance']))) if r['tipo']=='icmp' else r for r in rows]
 for typ in ['icmp','snmp','http','tcp']:
  targets=[]
  for row in rows:
   if row['tipo']!=typ:continue
   labels={k:row[k] for k in ['Cliente','Unidade','Provedor']}
   if typ=='icmp':labels.update(monitor_id=row['id'],monitor_name=row['name'])
   if typ=='snmp':labels.update(snmp_auth=row['auth'],snmp_module=row['module'])
   targets.append({'targets':[row['instance']],'labels':labels})
  atomic(BASE/'config/targets'/f'{typ}.json',targets)
 atomic(BASE/'config/targets/inventory.json',rows);print(f'{len(rows)} alvos cadastrados. Atualização em até 60 segundos.')
