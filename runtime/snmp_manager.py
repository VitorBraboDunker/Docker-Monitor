"""SNMP configuration and discovery. Credentials never enter inventory or API replies."""
from __future__ import annotations
import copy
import json
import math
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from monitor_probes import validate_host

CONFIG = Path(os.environ.get('DNK_CONFIG', '/etc/dunker'))
PRIVATE = Path(os.environ.get('DNK_SNMP_PRIVATE', str(CONFIG / 'integracoes/private')))
MODULES = CONFIG / 'integracoes/modules.json'
EXPORTER = os.environ.get('SNMP_URL', 'http://snmp:9116')
PRESETS = {
    'sonicwall': ('dnk_if_mib,dnk_system', 'dnk_sonicwall_health'),
    'mikrotik': ('dnk_if_mib,dnk_system', 'dnk_hrDevice,dnk_hrStorage'),
    'generico': ('dnk_if_mib,dnk_system', ''),
}
SECRET_KEYS = ('community', 'username', 'password', 'priv_password')

def read_json(path, default):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError: return copy.deepcopy(default)

def atomic(path, value, mode=0o600):
    atomic_bytes(path,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode(),mode)

def atomic_bytes(path, body, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(body)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)

def exporter_yaml(value, indent=0, numeric_keys=False):
    """Small YAML writer for JSON-shaped values; SNMP enum keys must stay integers."""
    pad=' '*indent
    if isinstance(value,dict):
        lines=[]
        for key,item in value.items():
            name=str(int(key)) if numeric_keys else json.dumps(str(key),ensure_ascii=False)
            if isinstance(item,(dict,list)) and item:
                lines.append(pad+name+':\n'+exporter_yaml(item,indent+2,key=='enum_values'))
            else: lines.append(pad+name+': '+json.dumps(item,ensure_ascii=False))
        return '\n'.join(lines)
    if isinstance(value,list):
        return '\n'.join(pad+'-\n'+exporter_yaml(item,indent+2) if isinstance(item,(dict,list)) and item else pad+'- '+json.dumps(item,ensure_ascii=False) for item in value)
    return pad+json.dumps(value,ensure_ascii=False)

def number(value, field, low, high):
    try: value = float(value)
    except (TypeError, ValueError): raise ValueError(f'{field}: número inválido')
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{field}: use {low} a {high}')
    return value

def normalize(payload, current=None, previous_auth=None):
    current = current or {}
    row = {k: current[k] for k in ('name','Cliente','Unidade','Provedor','host','port','vendor','model','firmware','interval_seconds','timeout_seconds','enabled','version','interfaces','cpu_oid','ram_oid') if k in current}
    row.update({k:v for k,v in payload.items() if k in ('name','Cliente','Unidade','Provedor','host','port','vendor','model','firmware','interval_seconds','timeout_seconds','enabled','version','interfaces','cpu_oid','ram_oid')})
    row.update(id=current.get('id', str(uuid.uuid4())), tipo='snmp', managed_snmp=True)
    for field in ('name','Cliente','Unidade','Provedor','model','firmware'):
        row[field] = str(row.get(field, '')).strip()[:180]
    if not all(row[k] for k in ('name','Cliente','Unidade')):
        raise ValueError('Preencha nome, cliente e unidade')
    row['Provedor'] = row['Provedor'] or 'Equipamento'
    row['host'] = validate_host(str(row.get('host','')).strip())
    row['port'] = int(number(row.get('port',161),'Porta',1,65535))
    if ':' in row['host']: row['instance'] = f"[{row['host']}]:{row['port']}"
    else: row['instance'] = row['host'] if row['port']==161 else f"{row['host']}:{row['port']}"
    row['vendor'] = row.get('vendor','sonicwall')
    if row['vendor'] not in PRESETS: raise ValueError('Fabricante inválido')
    row['interval_seconds'] = int(number(row.get('interval_seconds',60),'Frequência',30,120))
    row['timeout_seconds'] = int(number(row.get('timeout_seconds',20),'Timeout total',5,50))
    if row['timeout_seconds'] >= row['interval_seconds']: raise ValueError('Timeout precisa ser menor que a frequência')
    row['enabled'] = row.get('enabled', True)
    if not isinstance(row['enabled'],bool): raise ValueError('Estado inválido')
    row['version'] = str(row.get('version','3'))
    if row['version'] not in ('2','3'): raise ValueError('Use SNMPv2c ou SNMPv3')
    for field in ('cpu_oid','ram_oid'):
        oid = str(row.get(field,'')).strip().lstrip('.')
        if oid and not re.fullmatch(r'1\.3\.(?:\d+\.)+\d+',oid): raise ValueError('OID inválido: informe o OID numérico completo, com .0 para escalar')
        row[field]=oid
    interfaces=row.get('interfaces',[])
    if not isinstance(interfaces,list) or len(interfaces)>256: raise ValueError('Lista de interfaces inválida')
    row['interfaces']=[]; indexes=set()
    for item in interfaces:
        if not isinstance(item,dict): raise ValueError('Interface inválida')
        index=str(int(number(item.get('ifIndex'),'Índice da interface',1,2147483647)))
        if index in indexes: raise ValueError('Interface duplicada')
        indexes.add(index)
        row['interfaces'].append({'ifIndex':index,'name':str(item.get('name',index))[:180],
          'download_mbps':number(item.get('download_mbps',0),'Download contratado',0,10000000),
          'upload_mbps':number(item.get('upload_mbps',0),'Upload contratado',0,10000000)})
    auth = dict(previous_auth or {})
    if auth.get('version') != int(row['version']): auth={}
    supplied=payload.get('credentials',{})
    if not isinstance(supplied,dict): raise ValueError('Credenciais inválidas')
    for key in SECRET_KEYS:
        if supplied.get(key): auth[key]=str(supplied[key])
    auth['version']=int(row['version'])
    if row['version']=='2':
        if not auth.get('community'): raise ValueError('Informe a comunidade somente leitura')
        auth={k:auth[k] for k in ('version','community')}
    else:
        auth['security_level']='authPriv'
        auth['auth_protocol']=supplied.get('auth_protocol',auth.get('auth_protocol','SHA'))
        auth['priv_protocol']=supplied.get('priv_protocol',auth.get('priv_protocol','AES'))
        if auth['auth_protocol'] not in ('SHA','MD5','SHA256'): raise ValueError('Autenticação SNMPv3 inválida')
        if auth['priv_protocol'] not in ('AES','DES'): raise ValueError('Criptografia SNMPv3 inválida')
        if not auth.get('username') or len(auth.get('password',''))<8 or len(auth.get('priv_password',''))<8:
            raise ValueError('SNMPv3 requer usuário e duas senhas de pelo menos 8 caracteres')
        auth={k:v for k,v in auth.items() if k!='community'}
    row['snmp_auth']='dnk_'+row['id'].replace('-','')
    row['snmp_module'],row['health_module']=PRESETS[row['vendor']]
    if row['cpu_oid'] or row['ram_oid']: row['health_module']='health_'+row['id'].replace('-','')
    return row,auth

def public(row,auth=None):
    result={k:v for k,v in row.items() if k not in SECRET_KEYS and k!='credentials'}
    result['credentials_configured']=bool(auth)
    result['auth_protocol']=(auth or {}).get('auth_protocol','SHA')
    result['priv_protocol']=(auth or {}).get('priv_protocol','AES')
    return result

def document(rows,auths):
    modules=read_json(MODULES,{})
    if not modules: raise ValueError('Módulos SNMP não instalados')
    for row in rows:
        if not row.get('managed_snmp'): continue
        if row.get('cpu_oid') or row.get('ram_oid'):
            metrics=[];gets=[]
            for field,name in (('cpu_oid','dnkCustomCPUPercent'),('ram_oid','dnkCustomRAMPercent')):
                oid=row.get(field)
                if oid:
                    gets.append(oid)
                    metrics.append({'name':name,'oid':oid[:-2] if oid.endswith('.0') else oid,'type':'gauge','help':'Configured vendor utilization percent'})
            modules[row['health_module']]={'get':gets,'metrics':metrics,'timeout':'3s','retries':1}
    return {'auths':{r['snmp_auth']:auths[r['id']] for r in rows if r.get('managed_snmp') and r['id'] in auths},'modules':modules}

def reload_exporter():
    try:
        with urllib.request.urlopen(urllib.request.Request(EXPORTER+'/-/reload',data=b'',method='POST'),timeout=8) as r:
            r.read(1024)
    except Exception:
        raise ValueError('O coletor SNMP não recarregou. Confira os containers e os logs do serviço snmp; a alteração não foi aplicada.') from None

def apply(rows,auths):
    path=PRIVATE/'snmp-managed.yml'
    previous=path.read_bytes() if path.exists() else (exporter_yaml({'auths':{},'modules':read_json(MODULES,{})})+'\n').encode()
    atomic_bytes(path,(exporter_yaml(document(rows,auths))+'\n').encode())
    try: reload_exporter()
    except Exception:
        atomic_bytes(path,previous)
        try: reload_exporter()
        except ValueError: pass
        raise

def targets(rows,legacy):
    result=[x for x in legacy if x.get('labels',{}).get('managed_by')!='dnk']
    for r in rows:
        if not r.get('managed_snmp') or not r.get('enabled',True): continue
        labels={k:str(r[k]) for k in ('Cliente','Unidade','Provedor','snmp_auth')}
        labels.update(managed_by='dnk',monitor_id=r['id'],monitor_name=r['name'],vendor=r['vendor'],tipo='snmp',
                      __scrape_interval__=f"{r['interval_seconds']}s",__scrape_timeout__=f"{r['timeout_seconds']}s")
        result.append({'targets':[r['instance']],'labels':dict(labels,snmp_module=r['snmp_module'],snmp_scope='interfaces')})
        if r['health_module']:
            result.append({'targets':[r['instance']],'labels':dict(labels,snmp_module=r['health_module'],snmp_scope='health',job='snmp_health')})
    return result

METRIC=re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*?)\})?\s+([^\s]+)')
LABEL=re.compile(r'(\w+)="((?:\\.|[^"\\])*)"')
def parse_metrics(text):
    result=[]
    for line in text.splitlines():
        m=METRIC.match(line)
        if not m: continue
        try: value=float(m[3])
        except ValueError: continue
        labels={k:json.loads('"'+v+'"') for k,v in LABEL.findall(m[2] or '')}
        result.append((m[1],labels,value))
    return result

def scrape(row,module):
    query=urllib.parse.urlencode({'target':row['instance'],'auth':row['snmp_auth'],'module':module})
    try:
        with urllib.request.urlopen(EXPORTER+'/snmp?'+query,timeout=row['timeout_seconds']+2) as r:
            return parse_metrics(r.read(8*1024*1024).decode('utf-8'))
    except Exception:
        raise ValueError('Sem coleta SNMP: confira rota/VPN, UDP 161, permissão da origem, versão e credenciais.') from None

def discover(row):
    metrics=scrape(row,row['snmp_module']);interfaces={}
    for name,labels,value in metrics:
        index=labels.get('ifIndex')
        if index:
            item=interfaces.setdefault(index,{'ifIndex':index,'name':labels.get('ifName') or labels.get('ifDescr') or index})
            if name=='ifOperStatus': item['up']=value==1
            if name=='ifHighSpeed': item['speed_mbps']=value
    health={};warning=''
    if row['health_module']:
        try:
            for name,labels,value in scrape(row,row['health_module']):
                if name in ('sonicCurrentCPUUtil','dnkCustomCPUPercent'): health['cpu_percent']=value
                if name in ('sonicCurrentRAMUtil','dnkCustomRAMPercent'): health['ram_percent']=value
                if name=='hrProcessorLoad': health.setdefault('cores',[]).append(value)
                if name in ('hrStorageUsed','hrStorageSize') and (labels.get('hrStorageType')=='1.3.6.1.2.1.25.2.1.2' or re.search(r'(?i)ram|main memory',labels.get('hrStorageDescr',''))):
                    health[name]=value
            if health.get('cores'):
                cores=health.pop('cores');health['cpu_percent']=sum(cores)/len(cores)
        except ValueError: warning='Interfaces responderam; o módulo de CPU/RAM não respondeu. Confirme o suporte dos OIDs no modelo/firmware.'
    # HOST-RESOURCES percentages apply only to physical RAM.
    if health.get('hrStorageSize',0)>0: health['ram_percent']=100*health['hrStorageUsed']/health['hrStorageSize'] if 'hrStorageUsed' in health else None
    health={k:v for k,v in health.items() if k in ('cpu_percent','ram_percent')}
    if row['health_module'] and not health and not warning: warning='CPU/RAM não foram expostas pelo equipamento. A coleta de banda permanece disponível.'
    return {'success':True,'interfaces':sorted(interfaces.values(),key=lambda x:int(x['ifIndex'])),'health':health,'warning':warning}
