"""HTTP, TCP and DNS probes using Python's standard library."""
import ipaddress, secrets, socket, ssl, struct, time, urllib.error, urllib.request

def validate_host(value):
    value=str(value).strip()
    try:return str(ipaddress.ip_address(value))
    except ValueError:
        import re
        if len(value)>253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',p) for p in value.rstrip('.').split('.')):
            raise ValueError('Host ou domínio inválido')
        return value.rstrip('.')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args):return None

def read_exact(sock,n):
    data=b''
    while len(data)<n:
        part=sock.recv(n-len(data))
        if not part:raise OSError('Resposta DNS incompleta')
        data+=part
    return data

def dns_probe(row):
    types={'A':1,'AAAA':28,'CNAME':5,'MX':15,'TXT':16,'NS':2}
    ident=secrets.randbelow(65536)
    name=row['dns_name'].encode('idna').decode('ascii')
    qname=b''.join(bytes([len(p)])+p.encode('ascii') for p in name.split('.'))+b'\0'
    query=struct.pack('!HHHHHH',ident,0x100,1,0,0,0)+qname+struct.pack('!HH',types[row['dns_type']],1)
    deadline=time.monotonic()+row['timeout_seconds']
    host=row['instance'];port=row['dns_port']
    infos=socket.getaddrinfo(host,port,type=socket.SOCK_DGRAM)
    family,_,_,_,address=infos[0]
    with socket.socket(family,socket.SOCK_DGRAM) as sock:
        sock.settimeout(max(.01,deadline-time.monotonic()));sock.connect(address);sock.send(query);reply=sock.recv(65535)
    if len(reply)<12:raise OSError('Resposta DNS inválida')
    rid,flags,_,answers,_,_=struct.unpack('!HHHHHH',reply[:12])
    if rid!=ident or not flags&0x8000:raise OSError('Resposta DNS não corresponde à consulta')
    if flags&0x200:
        with socket.socket(family,socket.SOCK_STREAM) as sock:
            sock.settimeout(max(.01,deadline-time.monotonic()));sock.connect(address);sock.sendall(struct.pack('!H',len(query))+query)
            reply=read_exact(sock,struct.unpack('!H',read_exact(sock,2))[0])
        if len(reply)<12:raise OSError('Resposta DNS inválida')
        rid,flags,_,answers,_,_=struct.unpack('!HHHHHH',reply[:12])
        if rid!=ident or not flags&0x8000:raise OSError('Resposta DNS não corresponde à consulta')
    rcode=flags&15
    return rcode==0 and answers>0,{'dns_rcode':rcode,'dns_answers':answers}

def probe_service(row):
    started=time.monotonic();success=False;extra={};error=''
    try:
        if row['tipo']=='tcp':
            with socket.create_connection((row['tcp_host'],row['tcp_port']),timeout=row['timeout_seconds']):success=True
        elif row['tipo']=='http':
            handlers=[urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl.create_default_context())]
            if not row['follow_redirects']:handlers.append(NoRedirect())
            opener=urllib.request.build_opener(*handlers)
            request=urllib.request.Request(row['instance'],method=row['http_method'],headers={'User-Agent':'DunkerMonitor/1.2'})
            try:
                with opener.open(request,timeout=row['timeout_seconds']) as response:code=response.status
            except urllib.error.HTTPError as exc:code=exc.code;exc.close()
            extra['http_status_code']=code;success=code==row['expected_status'] if row['expected_status'] else 200<=code<300
        elif row['tipo']=='dns':success,extra=dns_probe(row)
        else:raise ValueError('Tipo de teste inválido')
    except Exception as exc:error=str(exc)
    return {'success':int(success),'duration':time.monotonic()-started,'timestamp':time.time(),'error':error,**extra}
