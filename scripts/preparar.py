#!/usr/bin/env python3
import argparse,ipaddress,json,os,re,subprocess
from pathlib import Path
B=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--host');p.add_argument('--syslog-bind');a=p.parse_args()
e=dict(l.split('=',1) for l in (B/'.env').read_text().splitlines() if '=' in l and not l.startswith('#'));host=a.host or e.get('MONITOR_HOST','127.0.0.1')
if host=='127.0.0.1' and not a.host:
 try:host=re.search(r'\bsrc (\S+)',subprocess.check_output(['ip','-4','route','get','1.1.1.1'],text=True)).group(1)
 except Exception:pass
if not re.fullmatch(r'[a-zA-Z0-9.-]+',host):p.error('Use um IPv4 ou hostname, sem protocolo, porta ou caminho.')
e['MONITOR_HOST']=host
if a.syslog_bind:ipaddress.IPv4Address(a.syslog_bind);e['SYSLOG_BIND']=a.syslog_bind
(B/'.env').write_text('\n'.join(f'{k}={v}' for k,v in e.items())+'\n');os.chmod(B/'.env',0o600);os.chmod(B,0o700)
for d in [B/'config',*(d for d in (B/'config').rglob('*') if d.is_dir())]:os.chmod(d,0o755)
for f in (B/'config').rglob('*'):
 if f.is_file():os.chmod(f,0o444 if 'secrets' in f.parts else 0o644)
c={name:(B/'config/secrets'/name).read_text().strip() for name in ['grafana_admin_password','grafana_secret_key','ingest_password','snmp_community']}
base='http://'+host+':'+e.get('ACCESS_PORT','8443')
s=f'''DUNKER MONITOR - ACESSOS PRIVADOS
Guarde no 1Password. Não envie este arquivo aos clientes.

Grafana: {base}
Usuário: admin
Senha inicial: {c['grafana_admin_password']}
A senha inicial só é aplicada ao criar o banco. Mudanças posteriores são feitas no Grafana.

Recebimento de métricas: {base}/api/v1/write
Recebimento de logs: {base}/loki/api/v1/push
Usuário de ingestão: alloy_ingest
Senha de ingestão: {c['ingest_password']}
Cadastro de pings: {base}/monitoramento/
HTTP sem certificado: use rede confiável ou VPN.

SNMP v2c somente leitura - perfil dunker_v2:
Comunidade: {c['snmp_community']}
Cadastre a mesma comunidade no equipamento. Não é uma senha preexistente do roteador.

Chave de criptografia interna do Grafana:
{c['grafana_secret_key']}
Preserve esta chave junto ao backup do banco do Grafana.

Prometheus na VM: http://127.0.0.1:9090
Alertmanager na VM: http://127.0.0.1:9093
Sem login próprio: publicados apenas no loopback da VM.

Banco do Grafana: SQLite persistente, sem senha de banco separada.
Métricas: TSDB do Prometheus. Logs: arquivos do Loki.
Containers: não têm SSH nem senha de login. Administração pelo Docker.
Ubuntu: use o usuário SSH e a senha que você criou na VM; o pacote não os altera.

A ingestão compartilhada é para o laboratório. Para operação MSP, separe as
credenciais por agente/cliente e o acesso aos dados. Labels não são isolamento.
'''
f=B/'ACESSOS-PRIVADOS.txt';f.write_text(s);os.chmod(f,0o600);print('Acesso: '+base);print('Credenciais em ACESSOS-PRIVADOS.txt')
