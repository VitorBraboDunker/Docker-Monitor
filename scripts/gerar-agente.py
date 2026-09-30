#!/usr/bin/env python3
import argparse,json,os,re,shutil
from pathlib import Path
B=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser(description='Gera configuração para Alloy já instalado no host.');p.add_argument('--tipo',choices=['windows','linux'],required=True);p.add_argument('--cliente',required=True);p.add_argument('--unidade',required=True);p.add_argument('--instance',required=True);p.add_argument('--logs',action='store_true');a=p.parse_args()
if not re.fullmatch(r'[A-Za-z0-9_.-]+',a.instance):p.error('instance deve ser um identificador de host: letras, números, ponto, traço ou sublinhado.')
e=dict(l.split('=',1) for l in (B/'.env').read_text().splitlines() if '=' in l);base='http://'+e['MONITOR_HOST']+':'+e.get('ACCESS_PORT','8443');win=a.tipo=='windows';folder=B/'agents'/a.instance
if folder.exists():p.error('A pasta deste agente já existe. Renomeie-a antes de gerar outra versão.')
folder.mkdir(parents=True,mode=0o700)
j=lambda x:json.dumps(x,ensure_ascii=False)
root='C:\\ProgramData\\DunkerMonitor\\' if win else '/etc/dunker-agent/'
secret=root+'ingest_password';ca=root+'ca.crt'
exporter='prometheus.exporter.windows' if win else 'prometheus.exporter.unix';settings='  enabled_collectors = ["cpu", "memory", "logical_disk", "net", "os", "system", "service", "time"]\n' if win else '  set_collectors = ["cpu", "meminfo", "filesystem", "loadavg", "netdev", "os", "uname", "time", "stat", "diskstats"]\n'
text='logging {\n  level = "info"\n}\nlocal.file "ingest" {\n  filename = '+j(secret)+'\n  is_secret = true\n}\n'+exporter+' "host" {\n'+settings+'}\n'
text+='discovery.relabel "host" {\n  targets = '+exporter+'.host.targets\n'
for k,v in [('instance',a.instance),('Cliente',a.cliente),('Unidade',a.unidade),('Provedor','Interno')]:text+='  rule {\n    target_label = '+j(k)+'\n    replacement = '+j(v)+'\n  }\n'
text+='}\nprometheus.scrape "host" {\n  targets = discovery.relabel.host.output\n  job_name = '+j('integrations/windows' if win else 'integrations/unix')+'\n  scrape_interval = "30s"\n  forward_to = [prometheus.remote_write.dunker.receiver]\n}\n'
text+='prometheus.remote_write "dunker" {\n  endpoint {\n    url = '+j(base+'/api/v1/write')+'\n    basic_auth {\n      username = "alloy_ingest"\n      password = local.file.ingest.content\n    }\n  }\n}\n'
if a.logs:
 text+='loki.write "dunker" {\n  endpoint {\n    url = '+j(base+'/loki/api/v1/push')+'\n    basic_auth {\n      username = "alloy_ingest"\n      password = local.file.ingest.content\n    }\n  }\n}\n'
 labels='{ job = "eventlog", Cliente = '+j(a.cliente)+', Unidade = '+j(a.unidade)+', instance = '+j(a.instance)+' }'
 if win:
  for channel in ['System','Application']:
   text+='loki.source.windowsevent '+j(channel.lower())+' {\n  eventlog_name = '+j(channel)+'\n  xpath_query = "*[System[(Level=1 or Level=2 or Level=3)]]"\n  bookmark_path = '+j(root+channel+'.xml')+'\n  labels = '+labels+'\n  forward_to = [loki.write.dunker.receiver]\n}\n'
 else:
  text+='loki.source.journal "system" {\n  labels = '+labels.replace('eventlog','journal')+'\n  max_age = "12h"\n  forward_to = [loki.write.dunker.receiver]\n}\n'
(folder/'config.alloy').write_text(text,encoding='utf-8');shutil.copy(B/'config/secrets/ingest_password',folder/'ingest_password')
for f in folder.iterdir():os.chmod(f,0o600)
readme=f'''Agente {a.instance} / {a.cliente} / {a.unidade}
Alloy precisa estar instalado no sistema operacional.
Destino: {base}
1. Copie ingest_password para {root}.
2. Preserve uma cópia do config.alloy existente, especialmente se envia ao Grafana Cloud.
3. Valide o novo arquivo com o binário do Alloy: alloy validate CAMINHO/config.alloy.
4. Após validar, use este config.alloy no serviço Alloy e reinicie o serviço.
Windows: caminho padrão C:\\Program Files\\GrafanaLabs\\Alloy\\config.alloy; Restart-Service Alloy.
Linux: caminho padrão /etc/alloy/config.alloy; sudo systemctl restart alloy.
No Linux, permita ao usuário do serviço ler /etc/dunker-agent; use grupo alloy, pasta 750 e arquivos 640.
Com --logs no Linux, o serviço também precisa de acesso ao journal (grupo systemd-journal).
No Windows, proteja a pasta permitindo Administrators, SYSTEM e a conta que executa o serviço.
5. Adicione ao inventario.csv a linha:
{a.tipo};{a.cliente};{a.unidade};Interno;{a.instance};;
6. Na VM, execute sudo python3 scripts/importar-inventario.py.
A configuração é autônoma. Ela substitui as rotas de envio anteriores se você substituir o arquivo inteiro.
Para envio simultâneo ao Cloud, mescle os componentes com nomes diferentes e ajuste forward_to.
'''
(folder/'LEIA-ME.txt').write_text(readme);print('Gerado:',folder)
