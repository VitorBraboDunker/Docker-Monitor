#!/usr/bin/env python3
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from alloy_builder import build
p=argparse.ArgumentParser(description='Gera Alloy sem copiar senhas; cadastre pela central Grafana para acompanhar o agente.')
p.add_argument('--tipo',choices=['windows','linux'],required=True);p.add_argument('--cliente',required=True);p.add_argument('--unidade',required=True);p.add_argument('--instance',required=True);p.add_argument('--logs',action='store_true');args=p.parse_args()
domain=json.loads((ROOT/'config/global/domains.json').read_text());value=build({'os':args.tipo,'CLIENTE':args.cliente,'UNIDADE':args.unidade,'instance':args.instance,'items':['cpu','memory','disk','network']+(['logs'] if args.logs else [])},domain['access']['public_url'])
folder=ROOT/'agents'/args.instance;folder.mkdir(parents=True,exist_ok=True)
(folder/'config.alloy').write_text(value['config']);(folder/'LEIA-ME.txt').write_text(value['instructions'])
inventory=ROOT/'config/targets/inventory.json';rows=json.loads(inventory.read_text())
if any(r.get('instance')==args.instance and r.get('CLIENTE')==args.cliente and not r.get('deleted_at') for r in rows):p.error('Servidor já cadastrado; use a configuração existente')
rows.append(value['asset']);inventory.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
print('Agente gerado:',folder)
