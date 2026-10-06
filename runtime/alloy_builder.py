"""Host Alloy configuration; select collectors and wire their dependencies."""
import base64, io, json, re, urllib.parse, uuid, zipfile
from pathlib import Path
J=lambda v:json.dumps(v,ensure_ascii=False)
ALLOY_VERSION='1.20.1'
DOWNLOADS={'windows':'https://github.com/grafana/alloy/releases/latest','linux':'https://grafana.com/docs/alloy/latest/set-up/install/linux/'}
TEMPLATES=Path(__file__).resolve().parent/'alloy_templates'
CHOICES={'cpu','memory','disk','network','services','logs'}
COLLECTORS={'windows':{'cpu':['cpu'],'memory':['memory'],'disk':['logical_disk'],'network':['net'],'services':['service']},'linux':{'cpu':['cpu'],'memory':['meminfo'],'disk':['filesystem','diskstats'],'network':['netdev'],'services':['systemd']}}
def build(payload,base,asset_id=None):
    osname=payload.get('os','windows');items=payload.get('items',[])
    if osname not in COLLECTORS or not isinstance(items,list) or not items or set(items)-CHOICES:raise ValueError('Selecione um sistema e pelo menos um item válido')
    labels={k:str(payload.get(k,'')).strip() for k in ('CLIENTE','UNIDADE','instance')}
    if any(not x or len(x)>120 for x in labels.values()):raise ValueError('Preencha CLIENTE, UNIDADE e o nome do servidor')
    if not re.fullmatch(r'[\w.-]+',labels['instance']):raise ValueError('Nome do servidor inválido')
    ident=asset_id or str(uuid.uuid4());win=osname=='windows';root='C:\\ProgramData\\DunkerMonitor\\' if win else '/etc/dunker-agent/'
    # An external agent uses an environment value provisioned from the global file.
    text='logging {\n  level = "info"\n}\n'
    component='prometheus.exporter.windows' if win else 'prometheus.exporter.unix'
    collectors=sorted({c for item in items for c in COLLECTORS[osname].get(item,[])})
    if collectors:
        collectors=sorted(set(collectors+(['os','system'] if win else ['os','uname','stat'])))
        text+=component+' "host" {\n  '+('enabled_collectors' if win else 'set_collectors')+' = '+J(collectors)+'\n}\n'
        text+='discovery.relabel "host" {\n  targets = '+component+'.host.targets\n'
        for k,v in {**labels,'asset_id':ident}.items():text+='  rule {\n    target_label = '+J(k)+'\n    replacement = '+J(v)+'\n  }\n'
        text+='}\nprometheus.scrape "host" {\n  targets = discovery.relabel.host.output\n  job_name = "integrations/'+('windows' if win else 'unix')+'"\n  scrape_interval = "30s"\n  forward_to = [prometheus.remote_write.dunker.receiver]\n}\n'
        text+='prometheus.remote_write "dunker" {\n  endpoint {\n    url = '+J(base+'/api/v1/write')+'\n    basic_auth {\n      username = "alloy_ingest"\n      password = sys.env("DNK_INGEST_PASSWORD")\n    }\n  }\n}\n'
    if 'logs' in items:
        text+='loki.write "dunker" {\n  endpoint {\n    url = '+J(base+'/loki/api/v1/push')+'\n    basic_auth {\n      username = "alloy_ingest"\n      password = sys.env("DNK_INGEST_PASSWORD")\n    }\n  }\n}\n'
        logs='{ '+', '.join(k+' = '+J(v) for k,v in {**labels,'asset_id':ident,'job':'eventlog' if win else 'journal'}.items())+' }'
        if win:
            for channel in ('System','Application'):
                text+='loki.source.windowsevent '+J(channel.lower())+' {\n  eventlog_name = '+J(channel)+'\n  xpath_query = "*[System[(Level=1 or Level=2 or Level=3)]]"\n  bookmark_path = '+J(root+channel+'.xml')+'\n  labels = '+logs+'\n  forward_to = [loki.write.dunker.receiver]\n}\n'
        else:text+='loki.source.journal "host" {\n  labels = '+logs+'\n  max_age = "12h"\n  forward_to = [loki.write.dunker.receiver]\n}\n'
    instructions=('Baixe o pacote com config e extraia no servidor. Windows: execute INSTALAR-ALLOY.ps1 como Administrador; ele baixa o instalador oficial e aplica a configuração. Linux: instale Alloy pelo link oficial e execute sudo bash APLICAR-CONFIG.sh. A senha de ingestão (system.ingest_password da central) é solicitada durante a execução. Configuração e scripts compartilham o mesmo ID do cadastro. Destino: '+base+'.')
    value={'asset_id':ident,'config':text,'instructions':instructions,'download_url':DOWNLOADS[osname],'alloy_version':ALLOY_VERSION,'asset':{'id':ident,'tipo':osname,'name':labels['instance'],**labels,'Provedor':'Interno','enabled':True,'items':sorted(set(items))}}
    value.update(bundle(value,osname,base))
    return value

def bundle(value,osname,base):
    filename='INSTALAR-ALLOY.ps1' if osname=='windows' else 'APLICAR-CONFIG.sh'
    metadata={'CLIENTE':value['asset']['CLIENTE'],'UNIDADE':value['asset']['UNIDADE'],'instance':value['asset']['instance'],'asset_id':value['asset_id'],'os':osname,'items':value['asset']['items'],'monitor_url':base,'alloy_version':ALLOY_VERSION,'official_download':DOWNLOADS[osname]}
    instructions=(
        'DUNKER MONITOR - AGENTE ALLOY\n\n'
        'Extraia o ZIP no servidor que sera monitorado.\n'
        'Cliente: '+metadata['CLIENTE']+' | Unidade: '+metadata['UNIDADE']+' | Servidor: '+metadata['instance']+'\n'
        'Destino: '+base+'\nID: '+value['asset_id']+'\n\n'
        'WINDOWS X64: abra o PowerShell como Administrador na pasta extraida:\n'
        'powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\INSTALAR-ALLOY.ps1\n'
        'O script instala Alloy '+ALLOY_VERSION+' se necessario, valida e aplica config.alloy.\n'
        'Para usar um EXE ja baixado, acrescente -Instalador "C:\\caminho\\alloy-installer-windows-amd64.exe".\n'
        'Se Alloy ja existir, acrescente -SubstituirConfiguracao para trocar a config com backup.\n\n'
        'LINUX COM SYSTEMD: instale primeiro Alloy usando o link oficial abaixo.\n'
        'sudo bash APLICAR-CONFIG.sh --substituir-configuracao\n'
        'A configuracao sera aplicada em /etc/alloy/config.alloy.\n\n'
        'SENHA: use system.ingest_password de config/global/credentials.json DA CENTRAL.\n'
        'Essa senha sera solicitada ao executar o script, sem ser exibida.\n'
        'Ela nao e a senha de acesso do Grafana. Nao ha credenciais no ZIP.\n'
        'Substituir uma configuracao Alloy existente muda os destinos anteriores (por exemplo Grafana Cloud/Fleet).\n'
        'O backup permite restaurar os arquivos e valores anteriores.\n'
        'Para Linux, confirme que o servico usa /etc/alloy/config.alloy. A leitura de journal/systemd depende das permissoes da conta alloy.\n'
        'O servidor precisa alcancar o destino acima; localhost/127.0.0.1 so atende o proprio computador.\n\n'
        'Download oficial: '+DOWNLOADS[osname]+'\n'
        'Windows: https://grafana.com/docs/alloy/latest/set-up/install/windows/\n'
        'Linux: https://grafana.com/docs/alloy/latest/set-up/install/linux/\n'
    )
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('config.alloy',value['config'])
        archive.writestr('agente.json',json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
        script=(TEMPLATES/filename).read_bytes()
        if osname=='windows':script=b'\xef\xbb\xbf'+script # PowerShell 5.1 needs a UTF-8 BOM.
        archive.writestr(filename,script)
        archive.writestr('LEIA-ME.txt',instructions)
    return {'bundle_base64':base64.b64encode(buffer.getvalue()).decode('ascii'),'bundle_name':'dunker-alloy-'+metadata['instance']+'.zip'}
