#!/usr/bin/env python3
"""PID 1: forwards termination; exits if any component exits."""
import os,signal,subprocess,sys,time
from pathlib import Path
B=Path('/etc/dunker')
if not (B/'prometheus/unico.yml').exists():sys.exit('Use scripts/iniciar.sh unico para montar a configuração em /etc/dunker.')
for folder in ['grafana','prometheus','alertmanager','loki','alloy','caddy-config']:Path('/data',folder).mkdir(parents=True,exist_ok=True)
e=os.environ.copy();e.update({'GF_PATHS_HOME':'/opt/grafana','GF_PATHS_DATA':'/data/grafana','GF_PATHS_LOGS':'/data/grafana/log','GF_PATHS_PLUGINS':'/data/grafana/plugins','GF_PATHS_PROVISIONING':'/etc/dunker/grafana/provisioning','GF_SECURITY_ADMIN_USER':'admin','GF_SECURITY_ADMIN_PASSWORD':(B/'secrets/grafana_admin_password').read_text().strip(),'GF_SECURITY_SECRET_KEY':(B/'secrets/grafana_secret_key').read_text().strip(),'GF_USERS_ALLOW_SIGN_UP':'false','GF_AUTH_ANONYMOUS_ENABLED':'false','GF_SERVER_ROOT_URL':'%(protocol)s://%(domain)s:%(http_port)s/','GF_ANALYTICS_REPORTING_ENABLED':'false','GF_ANALYTICS_CHECK_FOR_UPDATES':'false','GF_NEWS_NEWS_FEED_ENABLED':'false','GF_PLUGINS_PREINSTALL_DISABLED':'true','PROM_URL':'http://127.0.0.1:9090','LOKI_URL':'http://127.0.0.1:3100','AM_URL':'http://127.0.0.1:9093','GF_UPSTREAM':'127.0.0.1:3000','PROM_UPSTREAM':'127.0.0.1:9090','LOKI_UPSTREAM':'127.0.0.1:3100','PROM_WRITE_URL':'http://127.0.0.1:9090/api/v1/write','LOKI_WRITE_URL':'http://127.0.0.1:3100/loki/api/v1/push','XDG_DATA_HOME':'/data','XDG_CONFIG_HOME':'/data/caddy-config'})
e.update({'ADMIN_UPSTREAM':'127.0.0.1:8080','DNK_ADMIN_DATA':'/etc/dunker/targets','ADMIN_PASSWORD_FILE':'/etc/dunker/secrets/grafana_admin_password','BLACKBOX_URL':'http://127.0.0.1:9115'})
commands={
'admin':['python3','/opt/dunker/admin_monitor.py'],
'prometheus':['/usr/local/bin/prometheus','--config.file=/etc/dunker/prometheus/unico.yml','--storage.tsdb.path=/data/prometheus','--storage.tsdb.retention.time=30d','--storage.tsdb.retention.size=20GB','--web.enable-remote-write-receiver','--web.listen-address=0.0.0.0:9090'],
'alertmanager':['/usr/local/bin/alertmanager','--config.file=/etc/dunker/alertmanager.yml','--storage.path=/data/alertmanager','--web.listen-address=0.0.0.0:9093','--cluster.listen-address='],
'blackbox':['/usr/local/bin/blackbox_exporter','--config.file=/etc/dunker/blackbox.yml','--web.listen-address=127.0.0.1:9115'],
'snmp':['/usr/local/bin/snmp_exporter','--config.file=/etc/dunker/snmp.yml','--web.listen-address=127.0.0.1:9116'],
'ping':['python3','/opt/dunker/ping_exporter.py'],
'loki':['/usr/local/bin/loki','-config.file=/etc/dunker/loki.yml'],
'alloy':['/bin/alloy','run','--server.http.listen-addr=127.0.0.1:12345','--storage.path=/data/alloy','/etc/dunker/alloy/central.alloy'],
'grafana':['/opt/grafana/bin/grafana','server','--homepath=/opt/grafana'],
'caddy':['/usr/local/bin/caddy','run','--config=/etc/dunker/caddy/Caddyfile','--adapter=caddyfile']}
processes={};stopping=False;code=0
def stop(*_):
 global stopping
 stopping=True
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
try:
 for name,cmd in commands.items():print('[supervisor] '+name,flush=True);processes[name]=subprocess.Popen(cmd,env=e,start_new_session=True)
 while not stopping:
  for name,p in processes.items():
   if p.poll() is not None:print('[supervisor] Processo encerrado: '+name,flush=True);code=1;stopping=True;break
  time.sleep(.5)
finally:
 for p in processes.values():
  if p.poll() is None:os.killpg(p.pid,signal.SIGTERM)
 deadline=time.monotonic()+25
 for p in processes.values():
  try:p.wait(timeout=max(.1,deadline-time.monotonic()))
  except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL)
sys.exit(code)
