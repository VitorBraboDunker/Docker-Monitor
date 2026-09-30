#!/usr/bin/env python3
import json,ssl,sys,time,urllib.request,urllib.error
from pathlib import Path
B=Path(__file__).resolve().parents[1];e=dict(l.split('=',1) for l in (B/'.env').read_text().splitlines() if '=' in l);ctx=None;url='http://'+e['MONITOR_HOST']+':'+e.get('ACCESS_PORT','8443')
for attempt in range(60):
 try:
  with urllib.request.urlopen(url+'/api/health',context=ctx,timeout=5) as r:d=json.load(r)
  if d.get('database')=='ok':break
 except Exception:
  if attempt==59:sys.exit('Grafana ainda não está pronto. Consulte docker compose logs.')
  time.sleep(2)
else:sys.exit('Banco do Grafana sem confirmação de saúde.')
with urllib.request.urlopen('http://127.0.0.1:9090/api/v1/targets',timeout=10) as r:targets=json.load(r)['data']['activeTargets']
bad=[t for t in targets if t.get('health')!='up'];print('Grafana, HTTP e banco: OK');print(f'Prometheus: {len(targets)} targets; {len(bad)} ainda sem coleta.')
for t in bad:print(t['labels'].get('job','?')+': '+t.get('lastError',''))
try:urllib.request.urlopen(urllib.request.Request(url+'/api/v1/write',data=b''),context=ctx,timeout=5);sys.exit('ERRO: ingestão sem credencial foi aceita.')
except urllib.error.HTTPError as e:
 if e.code!=401:sys.exit('Resposta inesperada sem credencial: '+str(e.code))
print('Ingestão exige autenticação: OK');print('Acesso: '+url)
