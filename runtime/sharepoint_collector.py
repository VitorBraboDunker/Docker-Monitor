#!/usr/bin/env python3
"""Dunker SharePoint collector, private API and durable daily snapshots (stdlib)."""
from __future__ import annotations
import csv
import datetime as dt
import hashlib
import hmac
import http.server
import io
import json
import math
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PRIVATE = Path(os.environ.get('DNK_SP_PRIVATE', '/data'))
DB_PATH = PRIVATE / 'sharepoint.sqlite3'
TOKEN_FILE = PRIVATE / 'gateway_token'
LOCK = threading.RLock()
JOBS: dict[str, dict] = {}
BUSY: set[str] = set()
POOL = ThreadPoolExecutor(max_workers=4)
MAX_BODY = 256 * 1024
MAX_REPORT = 20 * 1024 * 1024
GIB = 2 ** 30
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
REPORT_HOSTS = frozenset(('reports.office.com', 'reports.office365.com', 'reportsncu.office.com'))


class SafeError(ValueError):
    """Only messages from this class may be exposed to the browser/logs."""


def init_db():
    os.umask(0o077)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    with LOCK, connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS tenants (id TEXT PRIMARY KEY, config TEXT NOT NULL,
          secret TEXT NOT NULL, revision TEXT NOT NULL, last_attempt REAL DEFAULT 0,
          last_success REAL DEFAULT 0, error TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS snapshots (tenant TEXT NOT NULL, report_date TEXT NOT NULL,
          collected REAL NOT NULL, sites TEXT NOT NULL, PRIMARY KEY(tenant,report_date));
        ''')
    os.chmod(DB_PATH, 0o600)


def connect():
    db = sqlite3.connect(DB_PATH, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA secure_delete=ON')
    return db


def number(value, name, low, high):
    try: result = float(value)
    except (ValueError, TypeError): raise SafeError(f'{name}: número inválido') from None
    if not math.isfinite(result) or not low <= result <= high:
        raise SafeError(f'{name}: use um valor entre {low} e {high}')
    return result


def normalize(payload, current=None, old_secret=''):
    defaults = dict(name='', Cliente='', tenant_id='', client_id='', enabled=True,
        interval_hours=24, capacity_gib=0, capacity_unit='GB', warning_percent=80, critical_percent=90,
        emergency_percent=95, stale_hours=96, selected_sites=[], site_aliases={}, secret_expires='')
    if current: defaults.update(current)
    # Allowlist: never persist an arbitrary field supplied by the browser.
    cfg = {k: payload.get(k, v) for k, v in defaults.items()}
    if cfg['capacity_unit'] not in ('GB', 'TB'):
        raise SafeError('Unidade de capacidade inválida: use GB ou TB')
    # Keep GiB as the canonical field for existing databases and Prometheus.
    if 'capacity_value' in payload:
        amount = number(payload['capacity_value'], 'Capacidade', 0, 100000000)
        cfg['capacity_gib'] = amount * (1024 if cfg['capacity_unit'] == 'TB' else 1)
    cfg['id'] = current['id'] if current else str(uuid.uuid4())
    for k in ('name', 'Cliente'):
        cfg[k] = str(cfg[k]).strip()
        if not cfg[k] or len(cfg[k]) > 120: raise SafeError('Preencha nome e cliente (até 120 caracteres)')
    for k in ('tenant_id', 'client_id'):
        try: cfg[k] = str(uuid.UUID(str(cfg[k])))
        except (ValueError, TypeError): raise SafeError(f'{k}: informe um GUID válido') from None
    if not isinstance(cfg['enabled'], bool): raise SafeError('Estado inválido')
    for k, low, high in (('interval_hours',6,168),('capacity_gib',0,100000000),
            ('warning_percent',1,100),('critical_percent',1,100),
            ('emergency_percent',1,100),('stale_hours',48,720)):
        cfg[k] = number(cfg[k], k, low, high)
    if not cfg['warning_percent'] < cfg['critical_percent'] < cfg['emergency_percent']:
        raise SafeError('Use limites crescentes: atenção < crítico < emergência')
    if not isinstance(cfg['selected_sites'], list) or len(cfg['selected_sites']) > 50000:
        raise SafeError('Seleção de sites inválida')
    if any(not isinstance(s,str) or not re.fullmatch(r'[\w-]{1,128}',s) for s in cfg['selected_sites']):
        raise SafeError('ID de site inválido')
    cfg['selected_sites'] = sorted(set(cfg['selected_sites']))
    aliases = cfg['site_aliases']
    if not isinstance(aliases,dict) or len(aliases)>50000: raise SafeError('Apelidos inválidos')
    if any(not isinstance(k,str) or not re.fullmatch(r'[\w-]{1,128}',k) or
           not isinstance(v,str) or len(v)>120 for k,v in aliases.items()): raise SafeError('Apelidos inválidos')
    if cfg['secret_expires']:
        try: dt.date.fromisoformat(cfg['secret_expires'])
        except (ValueError,TypeError): raise SafeError('Data de expiração inválida') from None
    secret = payload.get('client_secret') or old_secret
    if not isinstance(secret,str) or not 1 <= len(secret) <= 4096: raise SafeError('Informe o valor do segredo do aplicativo')
    return cfg, secret


def rows():
    with LOCK, connect() as db: return [dict(r) for r in db.execute('SELECT * FROM tenants ORDER BY id')]


def get_row(tenant):
    with LOCK, connect() as db:
        r=db.execute('SELECT * FROM tenants WHERE id=?',(tenant,)).fetchone()
    if r is None: raise SafeError('Integração não encontrada')
    return dict(r)


def latest(tenant):
    with LOCK, connect() as db:
        r=db.execute('SELECT * FROM snapshots WHERE tenant=? ORDER BY report_date DESC LIMIT 1',(tenant,)).fetchone()
    return dict(r) if r else None


def public(row):
    cfg=json.loads(row['config']); snap=latest(row['id'])
    cfg.update(secret_configured=bool(row['secret']), last_attempt=row['last_attempt'],
        last_success=row['last_success'], error=row['error'], collecting=row['id'] in BUSY,
        report_date=snap['report_date'] if snap else None, capacity_source='manual')
    cfg.setdefault('capacity_unit', 'GB')
    cfg['capacity_value'] = cfg['capacity_gib'] / (1024 if cfg['capacity_unit'] == 'TB' else 1)
    cfg['report_warning'] = report_warning(json.loads(snap['sites'])) if snap else ''
    return cfg


def save(payload, tenant=None):
    with LOCK:
        previous=get_row(tenant) if tenant else None
        cfg,secret=normalize(payload,json.loads(previous['config']) if previous else None,
            previous['secret'] if previous else '')
        for other in rows():
            if other['id']!=cfg['id'] and json.loads(other['config'])['tenant_id']==cfg['tenant_id']:
                raise SafeError('Este tenant já está cadastrado; edite a integração existente')
        changed_identity=previous and any(cfg[k]!=json.loads(previous['config'])[k] for k in ('tenant_id','client_id'))
        if changed_identity: raise SafeError('Tenant e aplicativo não podem ser trocados: crie outra integração')
        with connect() as db:
            if previous:
                db.execute('UPDATE tenants SET config=?,secret=?,revision=?,last_attempt=0 WHERE id=?',
                    (json.dumps(cfg),secret,str(uuid.uuid4()),cfg['id']))
            else:
                db.execute('INSERT INTO tenants(id,config,secret,revision) VALUES(?,?,?,?)',
                    (cfg['id'],json.dumps(cfg),secret,str(uuid.uuid4())))
        return public(get_row(cfg['id']))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None


def request(url, headers=None, data=None):
    """No automatic redirects: never forward a Graph token to the report host."""
    req=urllib.request.Request(url,headers=headers or {},data=data)
    opener=urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req,timeout=30) as r:
            body=r.read(MAX_REPORT+1)
            if len(body)>MAX_REPORT: raise SafeError('Relatório excede o limite de 20 MiB')
            return r.status,dict(r.headers),body
    except urllib.error.HTTPError as e:
        if e.code in REDIRECT_STATUSES: return e.code,dict(e.headers),b''
        if e.code==429:
            # Do not busy-loop: next scheduled attempt happens in at least one hour.
            raise SafeError('Microsoft limitou as chamadas (429). Tente novamente mais tarde.') from None
        if e.code in (400,401): raise SafeError('Autenticação recusada. Confira IDs, valor e validade do segredo.') from None
        if e.code==403: raise SafeError('Acesso recusado. Confira Reports.Read.All (Aplicativo) e consentimento administrativo.') from None
        raise SafeError(f'Microsoft retornou HTTP {e.code}. Tente novamente mais tarde.') from None
    except (urllib.error.URLError,TimeoutError,OSError):
        raise SafeError('Não foi possível alcançar a Microsoft. Confira DNS, saída HTTPS e tente novamente.') from None


def parse_report(raw):
    try:
        reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        required={'Report Refresh Date','Site Id','Site URL','Is Deleted','Storage Used (Byte)','Storage Allocated (Byte)','File Count'}
        if not required.issubset(set(reader.fieldnames or [])): raise SafeError('Relatório recebido sem as colunas de armazenamento esperadas')
        records={};dates=set()
        for line in reader:
            day=dt.date.fromisoformat(line['Report Refresh Date'])
            if day > dt.datetime.now(dt.timezone.utc).date(): raise SafeError('Data futura no relatório')
            dates.add(day.isoformat())
            if str(line['Is Deleted']).lower() in ('true','1'): continue
            identity=line['Site Id'].strip()
            if not identity: raise SafeError('Relatório com site sem identificação')
            sid=identity if re.fullmatch(r'[\w-]{1,128}',identity) else hashlib.sha256(identity.encode()).hexdigest()
            def integer(field):
                v=int(line[field])
                if not 0 <= v <= 2**63-1: raise SafeError('Valor de armazenamento inválido')
                return v
            url=line['Site URL'].strip()
            visible=url.startswith('https://')
            name=(urllib.parse.unquote(urllib.parse.urlsplit(url).path.rstrip('/').split('/')[-1])
                  or urllib.parse.urlsplit(url).hostname) if visible else 'Site '+sid[:10]
            site=dict(site_id=sid,site_name=str(name)[:120],url=url if visible else '',
                used_bytes=integer('Storage Used (Byte)'),quota_bytes=integer('Storage Allocated (Byte)'),
                files=integer('File Count'),concealed=not visible,report_rows=1,report_conflict=False)
            # A repeated row is not additional storage. A different site URL can
            # distinguish records whose reported ID is shared. Keep opaque URLs
            # in the temporary key only; do not expose concealed identifiers.
            url_key=url.rstrip('/').casefold() if visible else url
            key=(sid,url_key)
            previous=records.get(key)
            if previous:
                values=lambda s:(s['used_bytes'],s['quota_bytes'],s['files'])
                conflict=previous['report_conflict'] or values(previous)!=values(site)
                count=previous['report_rows']+1
                # No chronology is provided for conflicting rows of one date.
                # Select one complete row conservatively, never sum its copies.
                if values(site)>values(previous): records[key]=site
                records[key].update(report_rows=count,report_conflict=conflict)
            else:
                records[key]=site
            if len(records)>50000: raise SafeError('Relatório excede 50 mil sites')
        if len(dates)!=1: raise SafeError('Relatório vazio ou com datas de atualização inconsistentes')
        groups={}
        for sid,url_key in records:groups.setdefault(sid,[]).append(url_key)
        shared={sid:min(url_keys) for sid,url_keys in groups.items() if len(url_keys)>1}
        sites=[];assigned=set()
        for sid,url_key in sorted(records):
            site=records[(sid,url_key)]
            if sid in shared:
                site['report_id_shared']=True
                # Preserve the original ID for the first stable URL; other IDs
                # are derived from ID + URL and do not depend on CSV row order.
                if url_key!=shared[sid]:
                    site['site_id']='sp-'+hashlib.sha256((sid+'\0'+url_key).encode()).hexdigest()
                    if site['concealed']:site['site_name']='Site '+site['site_id'][3:13]
            if site['site_id'] in assigned:raise SafeError('Não foi possível distinguir as identificações dos sites no relatório')
            assigned.add(site['site_id']);sites.append(site)
        return dates.pop(),sites
    except SafeError: raise
    except (UnicodeError,ValueError,TypeError,KeyError,csv.Error):
        raise SafeError('Formato inválido no relatório da Microsoft') from None


def report_warning(sites):
    notices=[]
    repeated=sum(max(0,s.get('report_rows',1)-1) for s in sites)
    conflicts=sum(bool(s.get('report_conflict')) for s in sites)
    if repeated:notices.append(f'{repeated} linha(s) repetida(s) consolidada(s), sem somar o armazenamento novamente.')
    if conflicts:notices.append(f'{conflicts} site(s) com valores divergentes na mesma data: mantida uma linha completa com o maior uso. Confira o total no centro de administração SharePoint.')
    if any(s.get('report_id_shared') for s in sites):
        notices.append('Há IDs compartilhados por URLs diferentes; os registros foram distinguidos pela URL. Confira a lista de sites e o total no centro de administração SharePoint.')
    if any(s['concealed'] for s in sites):
        notices.append('A Microsoft ocultou nomes/URLs. Use apelidos ou ajuste a privacidade dos relatórios no Microsoft 365.')
    return ' '.join(notices)


def report_location(headers, base=None):
    """Validate every download hop; expose only a sanitized host on rejection."""
    target = next((v for k,v in headers.items() if k.lower() == 'location'), '')
    if not isinstance(target, str) or not target.strip():
        raise SafeError('Microsoft retornou redirecionamento sem Location. Teste novamente.')
    target = target.strip()
    host = ''
    try:
        if any(ord(c) < 32 or ord(c) == 127 for c in target) or '\\' in target:
            raise ValueError('Invalid URL')
        if base:
            target = urllib.parse.urljoin(base, target)
        url = urllib.parse.urlsplit(target)
        host = (url.hostname or '').lower()
        valid = (url.scheme == 'https' and not url.username and not url.password
                 and url.port in (None, 443) and host in REPORT_HOSTS
                 and (url.path.startswith('/data/download/') or url.path == '/data/v1.0/download')
                 and not url.fragment)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        diagnostic = host if re.fullmatch(r'[a-z0-9.-]{1,253}', host) else 'inválido ou ausente'
        raise SafeError('Destino de download do relatório não reconhecido (domínio: '+diagnostic+
                        '). Atualize o Dunker Monitor; se persistir, informe somente este domínio.')
    return target


def download_report(headers):
    target = report_location(headers)
    for _ in range(4):
        status, headers, raw = request(target)  # Never send Authorization or Graph headers.
        if status == 200:
            return raw
        if status not in REDIRECT_STATUSES:
            raise SafeError('Download do relatório retornou resposta inesperada. Teste novamente.')
        target = report_location(headers, base=target)
    raise SafeError('Download do relatório excedeu o limite de redirecionamentos. Teste novamente.')


def fetch_report(cfg, secret):
    form=urllib.parse.urlencode(dict(client_id=cfg['client_id'],client_secret=secret,
        grant_type='client_credentials',scope='https://graph.microsoft.com/.default')).encode()
    _,_,raw=request('https://login.microsoftonline.com/'+cfg['tenant_id']+'/oauth2/v2.0/token',
        {'Content-Type':'application/x-www-form-urlencoded'},form)
    try: token=json.loads(raw)['access_token']
    except (ValueError,KeyError,TypeError): raise SafeError('Resposta de autenticação inválida') from None
    if not isinstance(token,str) or not token: raise SafeError('Token não recebido')
    status,headers,raw=request("https://graph.microsoft.com/v1.0/reports/getSharePointSiteUsageDetail(period='D7')",
        {'Authorization':'Bearer '+token})
    if status in REDIRECT_STATUSES:
        raw = download_report(headers)
    elif status != 200:
        raise SafeError('Microsoft Graph retornou resposta inesperada para o relatório. Teste novamente.')
    return parse_report(raw)


def commit_report(row, report_date, sites):
    now=time.time()
    with LOCK,connect() as db:
        current=db.execute('SELECT revision FROM tenants WHERE id=?',(row['id'],)).fetchone()
        if not current or current['revision']!=row['revision']:
            raise SafeError('A configuração mudou durante a coleta; repita a operação')
        db.execute('INSERT OR REPLACE INTO snapshots VALUES(?,?,?,?)',
            (row['id'],report_date,now,json.dumps(sites)))
        cutoff=(dt.datetime.now(dt.timezone.utc).date()-dt.timedelta(days=365)).isoformat()
        db.execute('DELETE FROM snapshots WHERE report_date<?',(cutoff,))
        db.execute("UPDATE tenants SET last_success=?,error='' WHERE id=?",(now,row['id']))


def enqueue(payload=None, tenant=None, test=False):
    with LOCK:
        if tenant:
            row=get_row(tenant);cfg,secret=normalize(payload or {},json.loads(row['config']),row['secret'])
        else:
            if not test: raise SafeError('Salve a integração antes de coletar')
            cfg,secret=normalize(payload or {});row=None
        if tenant and tenant in BUSY: raise SafeError('Já existe uma coleta em andamento para esta integração')
        # Tests without a saved tenant are limited too (one at a time).
        key=tenant or 'unsaved-test'
        if key in BUSY or len(BUSY)>=8: raise SafeError('Aguarde o término das operações em andamento')
        job_id=secrets.token_hex(16)
        JOBS[job_id]=dict(id=job_id,state='running',created=time.time())
        BUSY.add(key)
        if row and not test:
            with connect() as db: db.execute('UPDATE tenants SET last_attempt=? WHERE id=?',(time.time(),tenant))
        POOL.submit(run_job,job_id,key,row,cfg,secret,test)
        return dict(job_id=job_id)


def run_job(job_id,key,row,cfg,secret,test):
    try:
        day,sites=fetch_report(cfg,secret)
        if not test: commit_report(row,day,sites)
        result=dict(report_date=day,sites=sites,site_count=len(sites),used_bytes=sum(s['used_bytes'] for s in sites),
            warning=report_warning(sites))
        with LOCK: JOBS[job_id].update(state='done',result=result)
    except Exception as exc:
        message=str(exc) if isinstance(exc,SafeError) else 'Falha interna na coleta. Confira a disponibilidade do volume e tente novamente.'
        with LOCK:
            JOBS[job_id].update(state='error',error=message)
            if row and not test:
                with connect() as db:
                    db.execute('UPDATE tenants SET error=? WHERE id=? AND revision=?',(message,row['id'],row['revision']))
    finally:
        with LOCK: BUSY.discard(key)


def scheduler():
    while True:
        try:
            now=time.time()
            with LOCK,connect() as db:
                cutoff=(dt.datetime.now(dt.timezone.utc).date()-dt.timedelta(days=365)).isoformat()
                db.execute('DELETE FROM snapshots WHERE report_date<?',(cutoff,))
            for row in rows():
                cfg=json.loads(row['config'])
                retry=3600 if row['error'] else cfg['interval_hours']*3600
                if cfg['enabled'] and now-row['last_attempt']>=retry:
                    try: enqueue(tenant=row['id'])
                    except SafeError: pass
            with LOCK:
                for key in list(JOBS):
                    if JOBS[key]['state']!='running' and now-JOBS[key]['created']>3600: del JOBS[key]
        except Exception:
            print('Agendador SharePoint: falha interna; nova tentativa em 30s',flush=True)
        time.sleep(30)


def selected(cfg,sites):
    wanted=set(cfg['selected_sites'])
    return [s for s in sites if not wanted or s['site_id'] in wanted]


def baseline(tenant,day,days):
    cutoff=(dt.date.fromisoformat(day)-dt.timedelta(days=days)).isoformat()
    with LOCK,connect() as db:
        old=db.execute('SELECT * FROM snapshots WHERE tenant=? AND report_date<=? ORDER BY report_date DESC LIMIT 1',
            (tenant,cutoff)).fetchone()
    if not old: return None
    # Do not present nine days of change as seven: require the exact report date.
    if old['report_date']!=cutoff: return None
    return json.loads(old['sites'])


def growth(tenant,day,sites,days,site_id=None,prior=None):
    if prior is None: prior=baseline(tenant,day,days)
    if prior is None: return None
    if site_id:
        a=next((s for s in sites if s['site_id']==site_id),None)
        b=next((s for s in prior if s['site_id']==site_id),None)
        return a['used_bytes']-b['used_bytes'] if a and b else None
    return sum(s['used_bytes'] for s in sites)-sum(s['used_bytes'] for s in prior)


def site_details(tenant):
    row=get_row(tenant);cfg=json.loads(row['config']);snap=latest(tenant)
    sites=json.loads(snap['sites']) if snap else []
    for s in sites:
        s['site_name']=cfg['site_aliases'].get(s['site_id']) or s['site_name']
        s['selected']=not cfg['selected_sites'] or s['site_id'] in cfg['selected_sites']
    return dict(report_date=snap['report_date'] if snap else None,sites=sites)


def labels(values):
    def escape(v): return str(v).replace('\\','\\\\').replace('\n','\\n').replace('"','\\"')
    return '{'+','.join(k+'="'+escape(v)+'"' for k,v in values.items())+'}'


def metrics(now=None):
    now=now or time.time();lines=[];typed=set()
    def emit(name,value,lab):
        name='dnk_sharepoint_'+name
        if name not in typed: lines.extend(['# TYPE '+name+' gauge']);typed.add(name)
        lines.append(name+labels(lab)+' '+str(value))
    for row in rows():
        cfg=json.loads(row['config']);lab=dict(Cliente=cfg['Cliente'],tenant_id=cfg['tenant_id'],
            integration_id=row['id'],monitor_name=cfg['name'])
        emit('enabled',int(cfg['enabled']),lab)
        if not cfg['enabled']: continue
        snap=latest(row['id'])
        emit('collector_success',int(bool(row['last_success']) and not row['error']),lab)
        emit('last_success_timestamp_seconds',row['last_success'],lab)
        emit('last_attempt_timestamp_seconds',row['last_attempt'],lab)
        emit('stale_limit_seconds',cfg['stale_hours']*3600,lab)
        emit('capacity_bytes',cfg['capacity_gib']*GIB,lab)
        for kind in ('warning','critical','emergency'): emit(kind+'_threshold_percent',cfg[kind+'_percent'],lab)
        if cfg['secret_expires']:
            expiry=dt.datetime.combine(dt.date.fromisoformat(cfg['secret_expires']),dt.time(),dt.timezone.utc).timestamp()
            emit('secret_expiry_timestamp_seconds',expiry,lab)
        state=4
        if snap:
            all_sites=json.loads(snap['sites']);sites=selected(cfg,all_sites)
            used=sum(s['used_bytes'] for s in all_sites);cap=cfg['capacity_gib']*GIB
            epoch=dt.datetime.combine(dt.date.fromisoformat(snap['report_date']),dt.time(),dt.timezone.utc).timestamp()
            emit('report_timestamp_seconds',epoch,lab)
            emit('tenant_used_bytes',used,lab)
            emit('selected_used_bytes',sum(s['used_bytes'] for s in sites),lab)
            emit('site_count',len(all_sites),lab)
            emit('selected_site_count',len(sites),lab)
            if cap:
                emit('free_bytes',max(0,cap-used),lab);emit('utilization_percent',100*used/cap,lab)
                if used>=cap: emit('estimated_days_to_full',0,lab)
            valid=not row['error'] and now-epoch<=cfg['stale_hours']*3600 and now-row['last_success']<=cfg['stale_hours']*3600
            if valid:
                state=5 if not cap else sum(100*used/cap>=cfg[k+'_percent'] for k in ('warning','critical','emergency'))
            baselines={days:baseline(row['id'],snap['report_date'],days) for days in (7,30)}
            for days in (7,30):
                delta=growth(row['id'],snap['report_date'],all_sites,days,prior=baselines[days]) if baselines[days] is not None else None
                if delta is not None:
                    emit(f'growth_{days}d_bytes',delta,lab)
                    if days==7 and delta>0 and cap>used:
                        emit('estimated_days_to_full',(cap-used)/(delta/7),lab)
            maps={days:{s['site_id']:s for s in old} if old is not None else {} for days,old in baselines.items()}
            for s in sites:
                sl=dict(lab,site_id=s['site_id'],site_name=cfg['site_aliases'].get(s['site_id']) or s['site_name'])
                emit('site_used_bytes',s['used_bytes'],sl);emit('site_quota_bytes',s['quota_bytes'],sl)
                emit('site_files',s['files'],sl)
                for days in (7,30):
                    old=maps[days].get(s['site_id'])
                    delta=s['used_bytes']-old['used_bytes'] if old else None
                    if delta is not None: emit(f'site_growth_{days}d_bytes',delta,sl)
        emit('state',state,lab)
    return ('\n'.join(lines)+'\n').encode()


class Handler(http.server.BaseHTTPRequestHandler):
    server_version='DunkerSharePoint/1.0'
    def log_message(self,*args): pass  # URLs/body/secrets must never enter logs.
    def respond(self,value,status=200,ctype='application/json; charset=utf-8'):
        body=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type',ctype)
        self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)
    def authorized(self):
        try: token=TOKEN_FILE.read_text().strip()
        except OSError: token=''
        supplied=self.headers.get('Authorization','')
        return bool(token) and hmac.compare_digest(supplied.encode(),('Bearer '+token).encode())
    def payload(self):
        if self.headers.get('Content-Type','').split(';')[0]!='application/json': raise SafeError('Use application/json')
        try: length=int(self.headers.get('Content-Length','0'))
        except ValueError: raise SafeError('Tamanho inválido') from None
        if not 0<length<=MAX_BODY: raise SafeError('Requisição muito grande ou vazia')
        try: value=json.loads(self.rfile.read(length))
        except (ValueError,UnicodeError): raise SafeError('JSON inválido') from None
        if not isinstance(value,dict): raise SafeError('Objeto JSON esperado')
        return value
    def dispatch(self):
        path=urllib.parse.urlsplit(self.path).path
        if path=='/healthz' and self.command=='GET': return self.respond({'status':'ok'})
        if path=='/metrics' and self.command=='GET': return self.respond(metrics(),ctype='text/plain; version=0.0.4')
        if not self.authorized(): return self.respond({'error':'Não autorizado'},401)
        try:
            if path=='/api/tenants':
                if self.command=='GET': return self.respond([public(r) for r in rows()])
                if self.command=='POST': return self.respond(save(self.payload()),201)
            if path=='/api/test' and self.command=='POST':
                p=self.payload();return self.respond(enqueue(p,p.get('id'),test=True),202)
            match=re.fullmatch(r'/api/jobs/([0-9a-f]{32})',path)
            if match and self.command=='GET':
                with LOCK: result=dict(JOBS.get(match[1],{}))
                return self.respond(result or {'error':'Operação expirada'},200 if result else 404)
            match=re.fullmatch(r'/api/tenants/([0-9a-f-]{36})(?:/(collect|sites|export))?',path)
            if match:
                tenant,op=match.groups();get_row(tenant)
                if op=='collect' and self.command=='POST': return self.respond(enqueue(tenant=tenant),202)
                if op=='sites' and self.command=='GET': return self.respond(site_details(tenant))
                if op=='export' and self.command=='GET':
                    out=io.StringIO();writer=csv.writer(out)
                    writer.writerow(['Data do relatório','Data da coleta','Site ID','Site','Uso bytes','Limite bytes','Arquivos'])
                    with LOCK,connect() as db:
                        snapshots=list(db.execute('SELECT * FROM snapshots WHERE tenant=? ORDER BY report_date',(tenant,)))
                    for snap in snapshots:
                        for s in json.loads(snap['sites']):
                            # CSV formula injection: exported strings must remain text.
                            name=s['site_name'];name="'"+name if name.startswith(('=','+','-','@')) else name
                            writer.writerow([snap['report_date'],dt.datetime.fromtimestamp(snap['collected'],dt.timezone.utc).isoformat(),s['site_id'],name,s['used_bytes'],s['quota_bytes'],s['files']])
                    return self.respond(('\ufeff'+out.getvalue()).encode(),ctype='text/csv; charset=utf-8')
                if not op and self.command=='PUT': return self.respond(save(self.payload(),tenant))
                if not op and self.command=='DELETE':
                    with LOCK,connect() as db: db.execute('DELETE FROM tenants WHERE id=?',(tenant,))
                    return self.respond({'deleted':True,'history_preserved':True})
            self.respond({'error':'Não encontrado'},404)
        except SafeError as e: self.respond({'error':str(e)},400)
        except Exception: self.respond({'error':'Falha interna. Confira o volume persistente e tente novamente.'},500)
    do_GET=dispatch
    do_POST=dispatch
    do_PUT=dispatch
    do_DELETE=dispatch


if __name__=='__main__':
    init_db()
    if not TOKEN_FILE.is_file(): raise SystemExit('Token interno ausente. Execute a preparação SharePoint.')
    threading.Thread(target=scheduler,daemon=True).start()
    http.server.ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('DNK_SP_PORT','9430'))),Handler).serve_forever()
