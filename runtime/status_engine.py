"""Inventory-backed operational status; missing telemetry cannot look healthy."""
import concurrent.futures, datetime as dt, json, math, os, socket, ssl, threading, time, urllib.parse, urllib.request
from pathlib import Path
import global_config, release_state
ROOT=global_config.ROOT
PROM=os.environ.get('DNK_PROM_URL','http://prometheus:9090')
LOCK=threading.RLock();CACHE=[];DOMAINS=[];LAST=0;ERROR=''
CODES=['OK','Sem Dados','Atenção','Grave','Crítico','Pausado']
DEFAULTS={'recovery_seconds':600,'warning_to_serious_seconds':600,'serious_to_critical_seconds':1800,'cpu_warning':85,'cpu_serious':95,'ram_warning':85,'ram_serious':95,'disk_warning':80,'disk_serious':95,'server_stale_seconds':180,'certificate_warning_days':30,'certificate_serious_days':7}
def settings():
    p=ROOT/'global/status.json'
    return {**DEFAULTS,**(json.loads(p.read_text()) if p.exists() else {})}
def prom_values():
    selector='{__name__=~"dnk:snmp_(cpu_percent|ram_percent|in_selected_bps|out_selected_bps)|dnk:server_.*|dnk_check_.*|dnk_ping_(loss_percent|rtt_seconds|collector_success|packets_sent|packets_received)|dnk_sharepoint_.*|up|ifOperStatus"}'
    with urllib.request.urlopen(PROM+'/api/v1/query?'+urllib.parse.urlencode({'query':selector}),timeout=12) as response:data=json.load(response)
    if data.get('status')!='success':raise ValueError('Consulta de telemetria indisponível')
    out=[]
    for series in data['data']['result']:
        value=float(series['value'][1])
        if math.isfinite(value):out.append((series['metric'],value,float(series['value'][0])))
    return out
def asset_labels(row,category):
    return {'asset_id':row['id'],'category':category,'CLIENTE':row.get('CLIENTE',row.get('Cliente','SemMapeamento')),'UNIDADE':row.get('UNIDADE',row.get('Unidade','Geral')),'instance':row.get('instance',row.get('tenant_id','')),'name':row.get('name',row.get('instance',''))}
def category(row):return 'firewalls' if row.get('managed_snmp') or row.get('tipo')=='snmp' else 'servidores' if row.get('tipo') in ('windows','linux') else 'links'
def evaluate(row,kind,series,now,limits):
    matches=[(m,v,t) for m,v,t in series if m.get('monitor_id',m.get('asset_id',m.get('integration_id')))==row['id']]
    if kind=='servidores' and not matches:
        # Migration of already-installed agents without asset_id, scoped by tenant/unit/host.
        matches=[(m,v,t) for m,v,t in series if m.get('instance')==row['instance'] and m.get('CLIENTE',m.get('Cliente'))==row.get('CLIENTE',row.get('Cliente')) and m.get('UNIDADE',m.get('Unidade'))==row.get('UNIDADE',row.get('Unidade'))]
    values={}
    for m,v,t in matches:
        key=m['__name__']
        if now-t<=limits['server_stale_seconds']:values[key]=max(values.get(key,-math.inf),v)
    get=lambda name:values.get(name)
    data={};reasons=[];severity=0
    def threshold(value,key,warning,serious):
        nonlocal severity
        if value is not None:
            data[key]=value
            if value>=serious:severity=max(severity,3);reasons.append(key+' acima do limite grave')
            elif value>=warning:severity=max(severity,2);reasons.append(key+' acima do limite de atenção')
    if kind=='links':
        timestamp=get('dnk_check_timestamp_seconds');collector=get('dnk_ping_collector_success')
        stale=2*row.get('interval_seconds',30)+row.get('timeout_seconds',5)*row.get('packet_count',5)+30
        if timestamp is None or now-timestamp>stale or (row.get('tipo')=='icmp' and collector!=1):return 1,'Telemetria ausente, antiga ou coletor indisponível',data
        success=get('dnk_check_success')
        if success is None:return 1,'Resultado da verificação ausente',data
        for field in ('packets_sent','packets_received'):
            if get('dnk_ping_'+field) is not None:data[field]=get('dnk_ping_'+field)
        data['available']=success;data['latency_ms']=(get('dnk_ping_rtt_seconds') or 0)*1000
        if get('dnk_check_duration_seconds') is not None:data['duration_seconds']=get('dnk_check_duration_seconds')
        if get('dnk_check_http_status_code') is not None:data['http_status_code']=get('dnk_check_http_status_code')
        if get('dnk_check_dns_answers') is not None:data['dns_answers']=get('dnk_check_dns_answers')
        if success==0:return 4,'Serviço completamente fora do ar',data
        loss=get('dnk_ping_loss_percent');rtt=get('dnk_ping_rtt_seconds')
        if loss is not None:threshold(loss,'loss_percent',max(0.000001,row.get('loss_warning_percent',5)),max(50,4*row.get('loss_warning_percent',5)))
        if rtt is not None:threshold(rtt*1000,'latency_ms',row.get('latency_warning_ms',100),3*row.get('latency_warning_ms',100))
    elif kind=='firewalls':
        ups=[v for m,v,t in matches if m['__name__']=='up' and m.get('job')=='snmp' and now-t<180]
        if not ups:return 1,'Sem comunicação com o coletor SNMP',data
        if min(ups)==0:return 1,'Coleta SNMP falhou; disponibilidade do equipamento não confirmada',data
        data['available']=1
        threshold(get('dnk:snmp_cpu_percent'),'cpu_percent',limits['cpu_warning'],limits['cpu_serious'])
        threshold(get('dnk:snmp_ram_percent'),'ram_percent',limits['ram_warning'],limits['ram_serious'])
        selected={str(i['ifIndex']) for i in row.get('interfaces',[])}
        wan=[v for m,v,t in matches if m['__name__']=='ifOperStatus' and m.get('job')=='snmp' and m.get('ifIndex') in selected and now-t<180]
        observed={m.get('ifIndex') for m,v,t in matches if m['__name__']=='ifOperStatus' and m.get('job')=='snmp' and now-t<180}
        if selected-observed:return 1,'Estado de interface selecionada não recebido',data
        if any(v!=1 for v in wan):severity=4;reasons.append('Interface monitorada fora do ar')
        for field,metric in [('download_bps','dnk:snmp_in_selected_bps'),('upload_bps','dnk:snmp_out_selected_bps')]:
            rates=[v for m,v,t in matches if m['__name__']==metric and now-t<180]
            if rates:data[field]=sum(rates)
    elif kind=='servidores':
        observed=get('dnk:server_observed_timestamp_seconds')
        if observed is None or now-observed>limits['server_stale_seconds']:return 1,'Agente sem telemetria recente',data
        data['available']=1
        expected=row.get('items',['cpu','memory','disk','network'])
        if not set(expected)-{'logs'}:return 1,'Agente configurado somente para logs; sem métricas de saúde',data
        for item,key in [('cpu','cpu'),('memory','ram'),('disk','disk')]:
            if item in expected:
                value=get('dnk:server_'+key+'_percent')
                if value is None:return 1,'Métrica selecionada não recebida: '+item,data
                threshold(value,key+'_percent',limits[key+'_warning'],limits[key+'_serious'])
        if 'network' in expected:
            if get('dnk:server_network_bps') is None:return 1,'Métrica de rede selecionada não recebida',data
            data['network_bps']=get('dnk:server_network_bps')
        if 'services' in expected:
            failed=get('dnk:server_failed_services')
            if failed is None:return 1,'Métrica de serviços selecionada não recebida',data
            data['failed_services']=failed
            if failed>0:severity=max(severity,3);reasons.append('Serviço automático falhou')
    else:
        if row.get('error'):return 1,'Falha na coleta SharePoint: '+row['error'],data
        stamp=get('dnk_sharepoint_report_timestamp_seconds');last=get('dnk_sharepoint_last_success_timestamp_seconds')
        stale=row.get('stale_hours',96)*3600
        if stamp is None or not last or now-stamp>stale or now-last>stale:return 1,'Relatório Microsoft ausente ou antigo',data
        for key,metric in [('used_bytes','tenant_used_bytes'),('capacity_bytes','capacity_bytes'),('free_bytes','free_bytes'),('growth_7d_bytes','growth_7d_bytes'),('growth_30d_bytes','growth_30d_bytes'),('site_count','site_count')]:
            if get('dnk_sharepoint_'+metric) is not None:data[key]=get('dnk_sharepoint_'+metric)
        cap=get('dnk_sharepoint_capacity_bytes')
        if not cap:severity=2;reasons.append('Capacidade do tenant não informada')
        elif get('dnk_sharepoint_utilization_percent') is not None:
            usage=get('dnk_sharepoint_utilization_percent');data['utilization_percent']=usage
            threshold(usage,'utilization_percent',row.get('warning_percent',80),row.get('critical_percent',90))
            if usage>=row.get('emergency_percent',95):severity=4;reasons.append('Armazenamento em nível crítico')
        expiry=get('dnk_sharepoint_secret_expiry_timestamp_seconds')
        if expiry is not None:
            data['secret_days_remaining']=(expiry-now)/86400
            if expiry<=now:severity=4;reasons.append('Segredo Microsoft expirado')
            elif expiry-now<30*86400:severity=max(severity,2);reasons.append('Segredo Microsoft perto da expiração')
    return severity,'; '.join(reasons) or 'Dentro dos parâmetros',data

def transition(asset,raw,reason,data,now,limits,old):
    enabled=asset.pop('enabled',True)
    incident=old.get('incident_since',0);recovered=old.get('recovered_at',0)
    if not enabled:raw=5;reason='Monitoramento pausado';incident=0;recovered=0
    elif raw in (2,3,4):
        if old.get('raw') not in (2,3,4):incident=now
        duration=now-incident
        if raw==2 and duration>=limits['warning_to_serious_seconds']:raw=3
        if raw==3 and duration>=limits['serious_to_critical_seconds']:raw=4
        recovered=0
    elif raw==0:
        if old.get('raw') in (2,3,4):recovered=now
        incident=0
        if recovered and now-recovered<limits['recovery_seconds']:raw=2;reason='Recuperado; período de observação'
        else:recovered=0
    else:incident=0;recovered=0
    # Store the physical severity separately so recovery does not restart forever.
    physical=0 if recovered else raw
    return {**asset,'status':raw,'status_name':CODES[raw],'raw':physical,'reason':reason,'incident_since':incident,'recovered_at':recovered,'checked_at':now,'data':data}

def grouped(assets,by_category=True):
    groups={}
    for a in assets:groups.setdefault((a['CLIENTE'],a['category'] if by_category else 'global'),[]).append(a)
    result=[]
    for (client,kind),rows in groups.items():
        active=[r for r in rows if r['status']!=5]
        # Sem Dados is an anomaly, while paused rows do not influence enabled peers.
        states=[r['status'] for r in active]
        status=max(states) if states else 5
        result.append({'CLIENTE':client,'category':kind,'status':status,'conformity':int(any(s!=0 for s in states)) if states else 2,'assets':len(rows),'enabled_assets':len(active)})
    return result

def domain_probe(cfg):
    now=time.time();row={'name':cfg['name'],'host':cfg['host'],'port':cfg.get('port',443),'tls':cfg.get('tls',True),'checked_at':now,'status':1}
    if cfg.get('enabled',True) is False:return {**row,'status':5}
    try:
        with socket.create_connection((row['host'],row['port']),timeout=5) as sock:
            if row['tls']:
                ctx=ssl.create_default_context(cafile=cfg.get('ca_file') or None)
                try:
                    with ctx.wrap_socket(sock,server_hostname=row['host']) as secure:
                        cert=secure.getpeercert();expiry=ssl.cert_time_to_seconds(cert['notAfter'])
                        row.update(expires_at=expiry,days_remaining=(expiry-now)/86400,issuer=str(cert.get('issuer','')))
                except ssl.SSLCertVerificationError:return {**row,'status':4,'error':'Certificado inválido, expirado ou emissor não confiável'}
        row['status']=0
        limits=settings()
        if row.get('days_remaining',999)<limits['certificate_serious_days']:row['status']=3
        elif row.get('days_remaining',999)<limits['certificate_warning_days']:row['status']=2
    except (OSError,ValueError):row.update(status=1,error='Não foi possível consultar o destino')
    return row

def refresh():
    global CACHE,LAST,ERROR,DOMAINS
    now=time.time();limits=settings()
    rows=json.loads((ROOT/'targets/inventory.json').read_text())
    try:series=prom_values();error=''
    except Exception:series=[];error='Prometheus indisponível; ativos habilitados ficam Sem Dados'
    try:
        token=global_config.get('system','gateway_token','')
        req=urllib.request.Request(os.environ.get('DNK_SP_URL','http://sharepoint:9430')+'/api/tenants',headers={'Authorization':'Bearer '+token})
        with urllib.request.urlopen(req,timeout=5) as r:sp=json.load(r)
    except Exception:
        # Never lose expected SharePoint assets during a collector outage.
        sp=json.loads((ROOT/'history/sharepoint-inventory.json').read_text()) if (ROOT/'history/sharepoint-inventory.json').exists() else []
    else:
        import snmp_manager
        snmp_manager.atomic(ROOT/'history/sharepoint-inventory.json',sp)
    configured=[(r,category(r)) for r in rows if not r.get('deleted_at')]+[(r,'sharepoint') for r in sp if not r.get('deleted_at')]
    assets=[]
    for row,kind in configured:
        if not row.get('id'):continue
        raw,reason,data=evaluate(row,kind,series,now,limits) if row.get('enabled',True) else (5,'Pausado',{})
        a=transition({**asset_labels(row,kind),'enabled':row.get('enabled',True)},raw,reason,data,now,limits,release_state.previous(row['id']))
        release_state.save(a);assets.append(a)
    with LOCK:CACHE=assets;LAST=now;ERROR=error
    if int(now)//300!=int(getattr(refresh,'domain_time',0))//300:
        try:
            cfg=json.loads(global_config.DOMAINS.read_text())
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:domains=list(pool.map(domain_probe,cfg.get('checks',[])))
            with LOCK:DOMAINS=domains
        except Exception:pass
        refresh.domain_time=now;release_state.prune()
def loop():
    while True:
        try:refresh()
        except Exception:
            global ERROR
            ERROR='Falha ao ler inventário ou histórico'
        time.sleep(30)
def snapshot():
    with LOCK:
        assets=list(CACHE);domains=list(DOMAINS);last=LAST;error=ERROR
    try:
        inventory=json.loads((ROOT/'targets/inventory.json').read_text())
        by_id={r['id']:r for r in inventory}
        assets=[a for a in assets if a['category']=='sharepoint' or (a['asset_id'] in by_id and not by_id[a['asset_id']].get('deleted_at'))]
        for a in assets:
            if a['category']!='sharepoint' and not by_id[a['asset_id']].get('enabled',True):a.update(status=5,status_name='Pausado',data={})
    except Exception:pass
    if time.time()-last>120:
        assets=[{**a,'status':1,'status_name':'Sem Dados','reason':'Motor de status sem atualização','data':{}} if a['status']!=5 else a for a in assets]
    return {'assets':assets,'clients':grouped(assets,False),'categories':grouped(assets),'domains':domains,'last_update':last,'error':error}
def metrics():
    state=snapshot();lines=[]
    def emit(name,value,labels):
        if isinstance(value,(float,int)) and math.isfinite(value):lines.append(name+'{'+','.join(k+'='+json.dumps(str(v),ensure_ascii=False) for k,v in labels.items())+'} '+str(value))
    for a in state['assets']:
        lab={k:a[k] for k in ('asset_id','category','CLIENTE','UNIDADE','instance','name')}
        lab['reason']=a['reason']
        emit('dnk_asset_info',1,lab);emit('dnk_asset_status',a['status'],lab)
        emit('dnk_asset_enabled',int(a['status']!=5),lab)
        for k,v in a['data'].items():emit('dnk_asset_'+k,v,lab)
    for key,name in [('clients','dnk_client'),('categories','dnk_client_category')]:
        for row in state[key]:
            lab={'CLIENTE':row['CLIENTE']}
            if key=='categories':lab['category']=row['category']
            for field in ('status','conformity','assets','enabled_assets'):emit(name+'_'+field,row[field],lab)
    for row in state['domains']:
        lab={k:row[k] for k in ('name','host','port')}
        for key in ('status','days_remaining','expires_at','checked_at'):emit('dnk_domain_'+key,row.get(key),lab)
    emit('dnk_status_last_update_timestamp_seconds',state['last_update'],{})
    return ('\n'.join(lines)+'\n').encode()
