#!/usr/bin/env python3
"""Enable the native app and remove the legacy token from its settings."""
import global_config
import base64,json,os,time,urllib.request,urllib.error
from pathlib import Path
private=Path(os.environ.get('DNK_SP_PRIVATE','/etc/dunker/sharepoint/private'))
password=global_config.get('system','grafana_admin_password','')
headers={'Content-Type':'application/json','Authorization':'Basic '+base64.b64encode(('admin:'+password).encode()).decode()}
body=json.dumps({'enabled':True,'pinned':True,'jsonData':{},'secureJsonData':{'gatewayToken':''}}).encode()
for attempt in range(30):
    try:
        req=urllib.request.Request('http://grafana:3000/api/plugins/dunker-integracoes-app/settings',headers=headers,data=body,method='POST')
        with urllib.request.urlopen(req,timeout=5) as response: response.read()
        print('Plugin Dunker ativado. Abra /a/dunker-integracoes-app/links');break
    except urllib.error.HTTPError as e:
        if e.code in (401,403): raise SystemExit('Grafana recusou a conta admin do arquivo de senha. Confira a ativação do plugin.')
    except (urllib.error.URLError,TimeoutError,OSError): pass
    time.sleep(1)
else: raise SystemExit('Grafana não ativou o plugin. Confira os logs.')
