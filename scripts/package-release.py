#!/usr/bin/env python3
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
legacy=['config/grafana/dashboards/'+n+'.json' for n in ('dnk-clientes-integrado','dnk-cliente-integrado','dnk-firewalls','dnk-firewall-detalhes','dnk-geral','dnk-links','dnk-logs','dnk-servidores','dnk-sharepoint-detalhes')]
legacy+=['tests/snmp-rules.yml','config/blackbox.yml','config/snmp-v3.yml.example','runtime/health.py','compose.integracoes.yaml','compose.sharepoint.yaml','config/sharepoint/prometheus.yml','config/sharepoint/rules.yml','config/secrets/credentials.json.example','config/grafana/provisioning/dashboards/links.yml']
files=[]
for f in sorted(ROOT.rglob('*')):
    rel=f.relative_to(ROOT).as_posix()
    if not f.is_file() or '__pycache__' in rel or rel.startswith(('agents/','diagnostico/','backups/','config/generated/')) or rel in ('package-manifest.json',):continue
    if rel in ('config/global/credentials.json','config/global/domains.json'):continue
    mode='seed' if rel.startswith('config/targets/') or rel in ('config/inventory.json','inventario.csv','config/global/status.json','config/alertmanager.yml') else 'managed'
    files.append({'path':rel,'mode':mode,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
(ROOT/'package-manifest.json').write_text(json.dumps({'version':'1.0.0','release_channel':'official','previous_beta_version':'1.4.3','files':files,'obsolete_files':legacy},ensure_ascii=False,indent=2)+'\n')
print(len(files),'arquivos no manifesto')
