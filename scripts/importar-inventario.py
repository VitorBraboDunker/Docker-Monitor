#!/usr/bin/env python3
"""Import client checks/servers while preserving IDs and recoverable removals."""
import argparse,csv,json,os,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'runtime'))
import admin_monitor as admin
KEYS=('tipo','CLIENTE','UNIDADE','Provedor','instance')
def load(path):
 with open(path,encoding='utf-8-sig',newline='') as stream:
  sample=stream.read(4096);stream.seek(0);rows=[]
  for line,row in enumerate(csv.DictReader(stream,delimiter=';' if ';' in sample.partition('\n')[0] else ','),2):
   row={k:(v or '').strip() for k,v in row.items() if k}
   for old,new in (('Cliente','CLIENTE'),('Unidade','UNIDADE')):
    if old in row:row.setdefault(new,row.pop(old))
   if not any(row.values()):continue
   if any(not row.get(k) for k in KEYS):raise ValueError(f'Linha {line}: preencha '+', '.join(KEYS))
   if row['tipo']=='snmp':raise ValueError(f'Linha {line}: cadastre SNMP pela central Grafana para separar credenciais e descobrir interfaces')
   if row['tipo'] not in admin.SUPPORTED|{'linux','windows'}:raise ValueError(f'Linha {line}: tipo inválido')
   row['name']=row.get('name') or row['instance'];rows.append({k:v for k,v in row.items() if k in set(KEYS)|{'name'}})
 return rows
if __name__=='__main__':
 parser=argparse.ArgumentParser(description='Importa/atualiza itens sem apagar cadastros existentes. Exclusões pela central.');parser.add_argument('csv',nargs='?',default=str(ROOT/'inventario.csv'));args=parser.parse_args()
 admin.DATA_DIR=ROOT/'config/targets';admin.INVENTORY=admin.DATA_DIR/'inventory.json'
 try:
  incoming=load(args.csv);rows=admin.load_inventory()
  for item in incoming:
   previous=next((r for r in rows if not r.get('deleted_at') and all(r.get(k)==item[k] for k in KEYS)),None)
   if item['tipo'] in admin.SUPPORTED:row=admin.normalize(item,previous)
   else:row={**item,'id':previous['id'] if previous else str(uuid.uuid4()),'enabled':previous.get('enabled',True) if previous else True,'items':['cpu','memory','disk','network']}
   if previous:rows[rows.index(previous)]=row
   else:rows.append(row)
  admin.persist(rows)
 except (ValueError,OSError) as exc:parser.error(str(exc))
 print(f'{len(incoming)} itens importados. Cadastros existentes e Itens Excluídos preservados.')
