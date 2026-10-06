#!/usr/bin/env python3
"""Client summaries and expandable technical asset rows, with one status contract."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'config/grafana/dashboards'
COLORS=['#299c46','#8e959f','#f2cc0c','#e02f44','#a64dd8','#000000']
NAMES=['OK','Sem Dados','Atenção','Grave','Crítico','Pausado']
DS={'type':'prometheus','uid':'dnk-prometheus'}
TITLES={'links':'Links','firewalls':'Firewalls e Roteadores','servidores':'Servidores','sharepoint':'SharePoint'}
PLURALS={'links':'Links','firewalls':'Equipamentos','servidores':'Servidores','sharepoint':'Integrações'}
ID=0
NAV=[{'title':title,'url':'/d/'+uid,'type':'link','includeVars':True,'keepTime':True} for title,uid in [('Desempenho geral','dnk-conformidade'),('Links','dnk-links-geral'),('Firewalls','dnk-firewalls-geral'),('Servidores','dnk-servidores-geral'),('SharePoint','dnk-sharepoint-geral'),('Domínios','dnk-dominios')]]
NAV.append({'title':'Configurações','type':'link','url':'/a/dunker-integracoes-app/links'})
def uid():
    global ID
    ID+=1
    return ID

def variable(name,query,multi=True,label=None):
    result={'name':name,'label':label or name,'type':'query','datasource':DS,'query':{'query':query,'refId':name},'definition':query,'refresh':2,'sort':1,'multi':multi,'includeAll':multi,'options':[],'current':{'text':'Todos','value':'$__all'} if multi else {}}
    if multi:result['allValue']='.*'
    return result

def panel(title,expr,x,y,w=12,h=7,kind='stat',unit='none',status=False,legend='{{name}}',link=None,display=None):
    fields={'unit':unit,'color':{'mode':'thresholds' if kind=='stat' else 'palette-classic'},'thresholds':{'mode':'absolute','steps':[{'color':COLORS[0],'value':None}]},'mappings':[],'noValue':'Sem Dados'}
    if status:
        fields['color']={'mode':'thresholds'}
        fields['mappings']=[{'type':'value','options':{str(i):{'text':n,'color':COLORS[i],'index':i} for i,n in enumerate(NAMES)}}]
        fields['mappings'].append({'type':'special','options':{'match':'null','result':{'text':'Sem Dados','color':COLORS[1]}}})
        fields['thresholds']['steps']=[{'color':c,'value':None if i==0 else i} for i,c in enumerate(COLORS)]
    if display:fields['displayName']=display
    if link:fields['links']=[{'title':'Abrir detalhes do cliente','url':link,'targetBlank':False}]
    result={'id':uid(),'type':kind,'title':title,'datasource':DS,'gridPos':{'x':x,'y':y,'w':w,'h':h},'fieldConfig':{'defaults':fields,'overrides':[]},'targets':[{'expr':expr,'refId':'A','legendFormat':legend,'instant':kind in ('stat','table'),'format':'table' if kind=='table' else 'time_series'}]}
    if kind=='stat':result['options']={'colorMode':'background' if status else 'value','graphMode':'none','textMode':'value_and_name' if status else 'value','orientation':'auto','reduceOptions':{'calcs':['lastNotNull'],'values':True,'fields':''},'wideLayout':True}
    elif kind=='timeseries':
        fields['custom']={'drawStyle':'line','lineWidth':2,'fillOpacity':8,'showPoints':'never','spanNulls':False,'axisLabel':'','axisPlacement':'auto','thresholdsStyle':{'mode':'off'}}
        result['options']={'legend':{'displayMode':'table','placement':'bottom','calcs':['lastNotNull','mean','max']},'tooltip':{'mode':'multi','sort':'desc'}}
    elif kind=='state-timeline':
        fields['custom']={'lineWidth':0,'fillOpacity':85,'spanNulls':False}
        result['options']={'showValue':'auto','rowHeight':0.8,'legend':{'displayMode':'list','placement':'bottom'},'tooltip':{'mode':'single'}}
    elif kind=='table':result['options']={'showHeader':True,'cellHeight':'sm','footer':{'show':False}}
    return result

def text(title,body,y,h=3):return {'id':uid(),'type':'text','title':title,'gridPos':{'x':0,'y':y,'w':24,'h':h},'options':{'mode':'markdown','content':body}}

def save(key,title,variables,panels,description,links=None):
    data={'uid':key,'title':title,'schemaVersion':39,'version':2,'editable':False,'tags':['Dunker','v1.0','CLIENTE','UNIDADE'],'timezone':'browser','refresh':'30s','time':{'from':'now-6h','to':'now'},'links':links or NAV,'templating':{'list':variables},'panels':panels,'description':description,'annotations':{'list':[]}}
    (OUT/(key+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

def active_info(selector):return f'dnk_asset_info{{{selector}}} @ end()'

def metric(field,selector):
    # reason changes during incidents: keep one curve per asset instead of splitting it.
    return f'max by (asset_id,CLIENTE,UNIDADE,instance,name) (dnk_asset_{field}{{{selector}}}) and on(asset_id) {active_info(selector)}'

def count_status(selector,condition):return f'count(dnk_asset_status{{{selector}}} {condition}) or vector(0)'

def healthy_percent(selector):
    denominator=f'count(dnk_asset_status{{{selector}}} != 5)'
    # No enabled assets: display Sem Dados rather than a fictitious 100%.
    return f'100 * ({count_status(selector,"== 0")}) / ({denominator} > 0)'

def collapsed_row(title,children,y):return {'id':uid(),'type':'row','title':title,'collapsed':True,'repeat':'asset_id','gridPos':{'x':0,'y':y,'w':24,'h':1},'panels':children}

def table_ident(selector,x=0,y=0,w=24,h=5):
    p=panel('Identificação e motivo do estado',f'dnk_asset_info{{{selector}}}',x,y,w,h,kind='table')
    p['transformations']=[{'id':'organize','options':{'excludeByName':{'Time':True,'__name__':True,'Value':True,'asset_id':True,'category':True},'indexByName':{'CLIENTE':0,'UNIDADE':1,'name':2,'instance':3,'reason':4},'renameByName':{'CLIENTE':'Cliente','UNIDADE':'Unidade','name':'Ativo','instance':'Destino / servidor','reason':'Motivo'}}}]
    return p

DETAILS={
'links':[('RTT atual','latency_ms','ms'),('Perda de pacotes','loss_percent','percent'),('Disponibilidade no período','available','percentunit'),('Duração da verificação','duration_seconds','s'),('Código HTTP','http_status_code','none'),('Respostas DNS','dns_answers','none')],
'firewalls':[('Processamento','cpu_percent','percent'),('Memória RAM','ram_percent','percent'),('Download WAN','download_bps','bps'),('Upload WAN','upload_bps','bps')],
'servidores':[('Processamento','cpu_percent','percent'),('Memória RAM','ram_percent','percent'),('Disco ocupado (maior volume)','disk_percent','percent'),('Tráfego de rede','network_bps','bps'),('Serviços automáticos com falha','failed_services','none')],
'sharepoint':[('Armazenamento utilizado','used_bytes','bytes'),('Capacidade configurada','capacity_bytes','bytes'),('Armazenamento disponível','free_bytes','bytes'),('Ocupação','utilization_percent','percent'),('Crescimento em 7 dias','growth_7d_bytes','bytes'),('Crescimento em 30 dias','growth_30d_bytes','bytes'),('Sites','site_count','none'),('Dias até expirar o segredo','secret_days_remaining','d')]
}
LEGEND='**Verde:** OK · **Cinza:** Sem Dados · **Amarelo:** Atenção · **Vermelho:** Grave · **Roxo:** Crítico · **Preto:** Pausado.'

OUT.mkdir(parents=True,exist_ok=True)
for f in OUT.glob('*.json'):f.unlink()
for category,title in TITLES.items():
    # Overview is one clickable tile per customer; technical details belong in the next screen.
    variables=[variable('CLIENTE',f'label_values(dnk_client_category_status{{category="{category}"}}, CLIENTE)',label='Cliente')]
    csel=f'category="{category}",CLIENTE=~"${{CLIENTE:regex}}"'
    to_detail=f'/d/dnk-{category}-detalhes?var-CLIENTE=${{__field.labels.CLIENTE:percentencode}}&var-UNIDADE=All&var-asset_id=All&from=${{__from}}&to=${{__to}}'
    panels=[text(title+' por cliente','Clique no cartão de um cliente para abrir **todos os seus '+PLURALS[category].lower()+'**, com seções expansíveis e gráficos individuais.\n\n'+LEGEND,0)]
    for i,(name,code) in enumerate(zip(NAMES,[0,1,2,3,4,5])):
        p=panel('Clientes · '+name,f'count(dnk_client_category_status{{{csel}}} == {code}) or vector(0)',i*4,3,4,4)
        p['fieldConfig']['defaults']['color']={'mode':'fixed','fixedColor':COLORS[code]};panels.append(p)
    cards=panel('Clientes — clique para abrir todos os ativos',f'dnk_client_category_status{{{csel}}}',0,7,24,9,status=True,legend='{{CLIENTE}}',link=to_detail)
    panels.append(cards)
    save('dnk-'+category+'-geral','Dunker | '+title+' — Visão Geral por Cliente',variables,panels,'Um cartão por cliente, consolidando todos os ativos habilitados da categoria em todas as unidades. Qualquer anomalia altera o estado do cliente. Clique para abrir o dashboard técnico completo.')

    variables=[variable('CLIENTE',f'label_values(dnk_asset_info{{category="{category}"}}, CLIENTE)',multi=False,label='Cliente'),variable('UNIDADE',f'label_values(dnk_asset_info{{category="{category}",CLIENTE=~"${{CLIENTE:regex}}"}}, UNIDADE)',label='Unidade')]
    selector=f'category="{category}",CLIENTE=~"${{CLIENTE:regex}}",UNIDADE=~"${{UNIDADE:regex}}"'
    avar=variable('asset_id',f'query_result(max by (asset_id,name) (dnk_asset_info{{{selector}}}))',label=PLURALS[category])
    avar['regex']='/asset_id="(?<value>[^"]+)".*name="(?<text>[^"]+)"/'
    variables.append(avar)
    panels=[text('Cliente — '+title,'Resumo de **todas as unidades do cliente** no topo. Os filtros Unidade e '+PLURALS[category]+' controlam as seções abaixo; por padrão todos os ativos são exibidos. Expanda cada seção para ver os gráficos.\n\n'+LEGEND,0,4)]
    header=[('Estado do cliente',f'dnk_client_category_status{{category="{category}",CLIENTE=~"${{CLIENTE:regex}}"}}',True),
            (PLURALS[category]+' cadastrados',f'dnk_client_category_assets{{category="{category}",CLIENTE=~"${{CLIENTE:regex}}"}}',False),
            (PLURALS[category]+' com problemas',count_status(csel,'>= 2')+'',False)]
    # exclude paused (5) from incident counters.
    header[2]=(header[2][0],f'count((dnk_asset_status{{{csel}}} >= 2) < 5) or vector(0)',False)
    header.extend([(PLURALS[category]+' sem dados',count_status(csel,'== 1'),False)])
    for i,(caption,expr,status) in enumerate(header):panels.append(panel(caption,expr,i*6,4,6,4,status=status,legend='{{CLIENTE}}'))
    panels.append(panel('Ativos habilitados em OK',healthy_percent(csel),0,8,8,4,unit='percent'))
    panels.append(panel('Monitoramento pausado',count_status(csel,'== 5'),8,8,8,4))
    panels.append(panel('Ativos habilitados',count_status(csel,'!= 5'),16,8,8,4))
    select=selector+',asset_id=~"${asset_id:regex}"'
    child=[panel('Estado do ativo',metric('status',select),0,13,6,5,status=True,legend='{{UNIDADE}} · {{name}} · {{instance}}'),table_ident(select,6,13,18,5)]
    # Current values, then full-width technical graphs in pairs.
    measures=DETAILS[category]
    cols=6 if len(measures) in (5,6) else 4
    for i,(caption,field,unit) in enumerate(measures):
        expr=metric(field,select)
        if category=='links' and field=='available':expr=f'avg_over_time((max by (asset_id,CLIENTE,UNIDADE,instance,name) (dnk_asset_available{{{select}}}))[$__range:30s]) and on(asset_id) {active_info(select)}'
        child.append(panel(caption,expr,(i%cols)*(24//cols),18+(i//cols)*4,24//cols,4,unit=unit))
    y=18+((len(measures)+cols-1)//cols)*4
    for i,(caption,field,unit) in enumerate(measures):
        child.append(panel(caption+' — histórico',metric(field,select),(i%2)*12,y+(i//2)*8,12,8,kind='timeseries',unit=unit))
    y+=((len(measures)+1)//2)*8
    child.append(panel('Histórico de status',metric('status',select),0,y,24,5,kind='state-timeline',status=True));y+=5
    bridge=f'label_replace({active_info(select)}, "monitor_id", "$1", "asset_id", "(.+)")'
    extras=[]
    if category=='links':
        for caption,metric_name,unit in [('Pacotes enviados e recebidos','dnk_ping_packets_sent','none'),('Última coleta','dnk_check_timestamp_seconds','dateTimeAsIso')]:
            expr=f'{metric_name}{{monitor_id=~"${{asset_id:regex}}"}} and on(monitor_id) {bridge}'
            if metric_name=='dnk_ping_packets_sent':
                extras.append(panel(caption,expr,0,y,12,8,kind='timeseries',legend='Enviados'))
                extras[-1]['targets'].append({'expr':f'dnk_ping_packets_received{{monitor_id=~"${{asset_id:regex}}"}} and on(monitor_id) {bridge}','refId':'B','legendFormat':'Recebidos','instant':False,'format':'time_series'})
                y+=8
            elif metric_name=='dnk_check_timestamp_seconds':extras.append(panel(caption,expr,12,y-8,12,8,unit=unit))
    if category=='firewalls':
        for i,(caption,metric_name,unit) in enumerate([('Download por interface','dnk:snmp_in_selected_bps','bps'),('Upload por interface','dnk:snmp_out_selected_bps','bps'),('Estado das interfaces','ifOperStatus','none'),('Tempo ligado','sysUpTime','s')]):
            expr=f'{metric_name}{{monitor_id=~"${{asset_id:regex}}"}} and on(monitor_id) {bridge}'
            if metric_name=='sysUpTime':expr='('+expr+') / 100'
            extras.append(panel(caption,expr,(i%2)*12,y+(i//2)*8,12,8,kind='timeseries',unit=unit,legend='{{ifName}} {{ifDescr}} {{ifIndex}}'))
        y+=16
    if category=='sharepoint':
        bridge=f'label_replace({active_info(select)}, "integration_id", "$1", "asset_id", "(.+)")'
        for i,(caption,field,unit) in enumerate([('Armazenamento por site','site_used_bytes','bytes'),('Limite de cada site','site_quota_bytes','bytes'),('Arquivos por site','site_files','none'),('Crescimento por site em 7 dias','site_growth_7d_bytes','bytes')]):
            expr=f'dnk_sharepoint_{field}{{integration_id=~"${{asset_id:regex}}"}} and on(integration_id) {bridge}'
            extras.append(panel(caption,expr,(i%2)*12,y+(i//2)*8,12,8,kind='timeseries',unit=unit,legend='{{site_name}}'))
        y+=16
    if category=='servidores':
        # Host-scoped inventory gate supports already deployed Alloy agents without asset_id.
        host=f'CLIENTE=~"${{CLIENTE:regex}}",UNIDADE=~"${{UNIDADE:regex}}"'
        gate=f'max by (CLIENTE,UNIDADE,instance) ({active_info(select)})'
        disk=f'(100 * (1 - windows_logical_disk_free_bytes{{{host}}} / (windows_logical_disk_size_bytes{{{host}}} > 0))) or (100 * (1 - node_filesystem_avail_bytes{{{host},fstype!~"tmpfs|overlay|squashfs"}} / (node_filesystem_size_bytes{{{host}}} > 0)))'
        extras.append(panel('Ocupação por disco / volume',f'({disk}) and on(CLIENTE,UNIDADE,instance) {gate}',0,y,12,8,kind='timeseries',unit='percent',legend='{{volume}} {{mountpoint}}'))
        rx=f'8 * (rate(windows_net_bytes_received_total{{{host}}}[3m]) or rate(node_network_receive_bytes_total{{{host},device!="lo"}}[3m]))'
        tx=f'8 * (rate(windows_net_bytes_sent_total{{{host}}}[3m]) or rate(node_network_transmit_bytes_total{{{host},device!="lo"}}[3m]))'
        network=panel('Rede por interface',f'({rx}) and on(CLIENTE,UNIDADE,instance) {gate}',12,y,12,8,kind='timeseries',unit='bps',legend='Recebido · {{nic}} {{device}}')
        network['targets'].append({'expr':f'({tx}) and on(CLIENTE,UNIDADE,instance) {gate}','refId':'B','legendFormat':'Enviado · {{nic}} {{device}}','instant':False,'format':'time_series'});extras.append(network)
        y+=8
    child.extend(extras)
    panels.append(collapsed_row('${asset_id:text} — detalhes técnicos',child,12))
    links=[{'title':'← Todos os clientes · '+title,'url':'/d/dnk-'+category+'-geral','type':'link','keepTime':True}]+NAV
    save('dnk-'+category+'-detalhes','Dunker | Cliente — '+title+' Detalhados',variables,panels,'Todos os ativos do cliente, com resumo consolidado e uma seção expansível por ativo. CLIENTE seleciona uma empresa; UNIDADE e ativos permitem filtrar sem limitar por padrão a um único ativo. Métricas sem suporte ou desabilitadas aparecem Sem Dados. Ativos excluídos não aparecem.',links)

variables=[variable('CLIENTE','label_values(dnk_client_status, CLIENTE)',label='Cliente')]
csel='CLIENTE=~"${CLIENTE:regex}"'
to_global='/d/dnk-conformidade?var-CLIENTE=${__field.labels.CLIENTE:percentencode}&from=${__from}&to=${__to}'
panels=[text('Desempenho geral e conformidade do cliente','Abrange **Links, Firewalls/Roteadores, Servidores e SharePoint**. Um ativo habilitado com anomalia ou Sem Dados torna o cliente Fora de Conformidade; pausados ficam fora da avaliação.\n\n**Ativos habilitados em OK (%)** mede a proporção de ativos saudáveis agora, sem substituir o status de conformidade e sem representar SLA ou disponibilidade histórica.\n\n'+LEGEND,0,5)]
for i,(name,code) in enumerate(zip(NAMES,[0,1,2,3,4,5])):
    p=panel('Clientes · '+name,f'count(dnk_client_status{{{csel}}} == {code}) or vector(0)',i*4,5,4,4)
    p['fieldConfig']['defaults']['color']={'mode':'fixed','fixedColor':COLORS[code]};panels.append(p)
panels.append(panel('Estado geral por cliente',f'dnk_client_status{{{csel}}}',0,9,24,9,status=True,legend='{{CLIENTE}}',link=to_global))
p=panel('Conformidade por cliente',f'dnk_client_conformity{{{csel}}}',0,18,12,6,status=True,legend='{{CLIENTE}}')
p['fieldConfig']['defaults']['mappings']=[{'type':'value','options':{'0':{'text':'Conforme','color':COLORS[0]},'1':{'text':'Fora de Conformidade','color':COLORS[3]},'2':{'text':'Pausado','color':COLORS[5]}}}]
p['fieldConfig']['defaults']['links']=[{'title':'Abrir '+title,'url':'/d/dnk-'+cat+'-detalhes?var-CLIENTE=${__field.labels.CLIENTE:percentencode}&var-UNIDADE=All&var-asset_id=All&from=${__from}&to=${__to}'} for cat,title in TITLES.items()];panels.append(p)
score=f'100 * ((count by (CLIENTE) (dnk_asset_status{{{csel}}} == 0)) or (0 * count by (CLIENTE) (dnk_asset_status{{{csel}}} != 5))) / (count by (CLIENTE) (dnk_asset_status{{{csel}}} != 5) > 0)'
panels.append(panel('Ativos habilitados em OK por cliente',score,12,18,12,6,unit='percent',legend='{{CLIENTE}}',display='${__field.labels.CLIENTE}'))
for i,(cat,title) in enumerate(TITLES.items()):
    link='/d/dnk-'+cat+'-detalhes?var-CLIENTE=${__field.labels.CLIENTE:percentencode}&var-UNIDADE=All&var-asset_id=All&from=${__from}&to=${__to}'
    panels.append(panel(title+' — estado por cliente',f'dnk_client_category_status{{{csel},category="{cat}"}}',(i%2)*12,24+(i//2)*7,12,7,status=True,legend='{{CLIENTE}}',link=link))
panels.append(panel('Histórico do estado geral',f'dnk_client_status{{{csel}}} and on(CLIENTE) dnk_client_status{{{csel}}} @ end()',0,38,24,7,kind='state-timeline',status=True,legend='{{CLIENTE}}'))
panels.append(table_ident(csel,0,45,24,8))
save('dnk-conformidade','Dunker | Clientes — Desempenho Geral e Conformidade',variables,panels,'Desempenho geral de cada cliente entre todas as categorias, preservando a regra de qualquer anomalia => Fora de Conformidade. Indicador em percentual é a fração atual de ativos habilitados em OK; não é um SLA.')
panels=[panel('Domínios e certificados','dnk_domain_status',0,0,12,7,status=True,legend='{{name}} · {{host}}'),panel('Dias até a expiração','dnk_domain_days_remaining',12,0,12,7,unit='d',legend='{{name}}'),panel('Consulta mais recente','dnk_domain_checked_at',0,7,24,6,kind='table')]
save('dnk-dominios','Dunker | Plataforma — Domínios e Certificados',[],panels,'Consultas online a cada 5 minutos. TLS é validado; certificado inválido ou expirado é Crítico. Configure os destinos em config/global/domains.json.')
print('10 dashboards: 4 visões gerais por cliente, 4 técnicos por cliente, desempenho global e domínios.')
