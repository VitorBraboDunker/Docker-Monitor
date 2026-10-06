#!/usr/bin/env python3
"""Five IPv4 ICMP packets per round. Loss is separate from collection errors."""
import concurrent.futures as futures,http.server,ipaddress,json,math,os,secrets,select,socket,struct,threading,time
CONFIG=os.environ.get('DNK_CONFIG','/etc/dunker');INVENTORY=os.environ.get('DNK_INVENTORY',CONFIG+'/targets/inventory.json')
LOCK=threading.Lock();RESULTS={};LAST_ROUND=0.;LAST_ERROR=0;STOP=threading.Event();DUE={}
CONFIG_DEFAULTS={'interval_seconds':30,'timeout_seconds':5,'packet_count':5,'packet_interval_seconds':1,'latency_warning_ms':100,'loss_warning_percent':5}
def checksum(data):
 if len(data)%2:data+=b'\0'
 n=sum(struct.unpack('!%dH'%(len(data)//2),data));n=(n>>16)+(n&65535);n+=n>>16;return ~n&65535
def parse_reply(data,ident,seq,nonce):
 offset=(data[0]&15)*4 if data and data[0]>>4==4 else 0
 if len(data)<offset+8:return False
 kind,code,_,rid,rseq=struct.unpack('!BBHHH',data[offset:offset+8]);return kind==0 and code==0 and rid==ident and rseq==seq and data[offset+8:]==nonce
def probe(address,count=5,timeout=5.,packet_interval=1.):
 result=dict(sent=0,received=0,loss=float('nan'),rtt=float('nan'),success=0,duration=0,timestamp=time.time());started=time.monotonic()
 try:
  ip=str(ipaddress.IPv4Address(address))
  try:sock=socket.socket(socket.AF_INET,socket.SOCK_RAW,socket.IPPROTO_ICMP);ident=secrets.randbelow(65535)+1
  except PermissionError:
   sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM,socket.IPPROTO_ICMP);sock.bind(('0.0.0.0',0));ident=sock.getsockname()[1]
  timings=[]
  with sock:
   sock.setblocking(False)
   for seq in range(count):
    nonce=secrets.token_bytes(24);h=struct.pack('!BBHHH',8,0,0,ident,seq);packet=struct.pack('!BBHHH',8,0,checksum(h+nonce),ident,seq)+nonce;before=time.monotonic();sock.sendto(packet,(ip,0));result['sent']+=1;deadline=before+timeout
    while time.monotonic()<deadline:
     if not select.select([sock],[],[],max(0,deadline-time.monotonic()))[0]:break
     data,source=sock.recvfrom(65535)
     if source[0]==ip and parse_reply(data,ident,seq,nonce):timings.append(time.monotonic()-before);break
    if seq<count-1:STOP.wait(max(0,packet_interval-(time.monotonic()-before)))
  result.update(received=len(timings),loss=100*(1-len(timings)/count),rtt=sum(timings)/len(timings) if timings else float('nan'),success=1)
 except (OSError,ValueError):result['success']=0
 result['timestamp']=time.time();result['duration']=time.monotonic()-started;return result
def inventory():
 with open(INVENTORY,encoding='utf-8') as f:return json.load(f)
def label_string(row):
 values={k:row[k] for k in ['Cliente','Unidade','Provedor','instance','tipo']};values.update(monitor_id=row.get('id',''),monitor_name=row.get('name',row['instance']))
 return '{'+','.join(k+'='+json.dumps(str(v),ensure_ascii=False) for k,v in values.items())+'}'
def row_id(row):return row.get('id') or '|'.join(str(row.get(k,'')) for k in ['Cliente','Unidade','Provedor','instance','tipo'])
def probe_row(row):
 if row['tipo']!='icmp':
  from monitor_probes import probe_service
  return probe_service(row)
 result=probe(row['instance'],int(row.get('packet_count',5)),float(row.get('timeout_seconds',5)),float(row.get('packet_interval_seconds',1)))
 result['check_success']=int(result['success']==1 and result['received']>0)
 return result
def collect():
 global LAST_ROUND,LAST_ERROR
 pending={}
 with futures.ThreadPoolExecutor(max_workers=32) as pool:
  while not STOP.is_set():
   try:
    rows=[r for r in inventory() if r['tipo'] in ('icmp','http','tcp','dns') and r.get('enabled',True)]
    now=time.monotonic();active={row_id(r):r for r in rows}
    with LOCK:
     labels={label_string(r) for r in rows}
     for key in list(RESULTS):
      if key not in labels:RESULTS.pop(key,None)
    for key,(row,task) in list(pending.items()):
     if task.done():
      result=task.result()
      if key in active and active[key]==row:
       with LOCK:RESULTS[label_string(row)]=result
      del pending[key]
    for row in rows:
     key=row_id(row)
     if key not in pending and DUE.get(key,0)<=now:
      pending[key]=(dict(row),pool.submit(probe_row,dict(row)))
      DUE[key]=now+max(10,int(row.get('interval_seconds',30)))
    for key in list(DUE):
     if key not in active:DUE.pop(key,None)
    with LOCK:LAST_ROUND=time.time();LAST_ERROR=0
   except (OSError,ValueError,KeyError):
    with LOCK:LAST_ERROR=1
   STOP.wait(1)
def render_metrics():
 try:rows=[r for r in inventory() if r.get('enabled',True)]
 except (OSError,ValueError):rows=[]
 out=['# TYPE dnk_target_expected gauge']+['dnk_target_expected'+label_string(r)+' 1' for r in rows]
 for r in rows:
  if r.get('managed_snmp'):
   out.append('dnk_snmp_device_info'+label_string(r)+' 1')
   for iface in r.get('interfaces',[]):
    labels=label_string(r)[:-1]+',ifIndex='+json.dumps(iface['ifIndex'])+'}'
    out.append('dnk_snmp_interface_selected'+labels+' 1')
    for direction in ('download','upload'):
     out.append('dnk_snmp_contracted_'+direction+'_bits'+labels+' '+str(float(iface.get(direction+'_mbps',0))*1000000))
 out+=['# TYPE dnk_check_config_interval_seconds gauge']+['dnk_check_config_interval_seconds'+label_string(r)+' '+str(r.get('interval_seconds',30)) for r in rows if r.get('tipo') in ('icmp','http','tcp','dns')]
 out+=['# TYPE dnk_check_config_stale_seconds gauge']+['dnk_check_config_stale_seconds'+label_string(r)+' '+str(2*float(r.get('interval_seconds',30))+max(float(r.get('timeout_seconds',5)),float(r.get('packet_interval_seconds',1)))*int(r.get('packet_count',5))+30) for r in rows if r.get('tipo') in ('icmp','http','tcp','dns')]
 config_fields={'interval_seconds':'interval_seconds','timeout_seconds':'timeout_seconds','packet_count':'packet_count','packet_interval_seconds':'packet_interval_seconds','latency_warning_ms':'latency_warning_milliseconds','loss_warning_percent':'loss_warning_percent'}
 for field,suffix in config_fields.items():
  name='dnk_ping_config_'+suffix;out+=['# TYPE '+name+' gauge']
  out += [name+label_string(r)+' '+str(r.get(field,CONFIG_DEFAULTS[field])) for r in rows if r.get('tipo')=='icmp']
 fields={'sent':'packets_sent','received':'packets_received','loss':'loss_percent','rtt':'rtt_seconds','success':'collector_success','timestamp':'last_measurement_timestamp_seconds','duration':'round_duration_seconds'}
 with LOCK:
  for field,suffix in fields.items():
   name='dnk_ping_'+suffix;out+=['# TYPE '+name+' gauge']
   out += [name+labels+' '+('NaN' if isinstance(data[field],float) and math.isnan(data[field]) else str(data[field])) for labels,data in RESULTS.items() if field in data and 'sent' in data]
  for field,name in [('success','dnk_check_success'),('duration','dnk_check_duration_seconds'),('timestamp','dnk_check_timestamp_seconds'),('http_status_code','dnk_check_http_status_code'),('dns_rcode','dnk_check_dns_rcode'),('dns_answers','dnk_check_dns_answers')]:
   out.append('# TYPE '+name+' gauge')
   out += [name+labels+' '+str(data.get('check_success',data[field]) if field=='success' else data[field]) for labels,data in RESULTS.items() if field in data]
  out+=['# TYPE dnk_ping_last_round_timestamp_seconds gauge','dnk_ping_last_round_timestamp_seconds '+str(LAST_ROUND),'# TYPE dnk_ping_config_error gauge','dnk_ping_config_error '+str(LAST_ERROR)]
 return ('\n'.join(out)+'\n').encode()
class Handler(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path=='/metrics':data=render_metrics();ctype='text/plain; version=0.0.4; charset=utf-8'
  elif self.path=='/healthz':data=b'ok\n';ctype='text/plain'
  else:self.send_error(404);return
  self.send_response(200);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def log_message(self,*_):pass
if __name__=='__main__':
 threading.Thread(target=collect,daemon=True).start();http.server.ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PING_PORT',9427))),Handler).serve_forever()
