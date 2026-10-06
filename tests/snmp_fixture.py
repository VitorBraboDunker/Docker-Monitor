"""Local SNMPv2c fixture for integration tests; never use as a production agent."""
import socket
import threading

def tlv(tag,value):
    length=len(value)
    if length<128: header=bytes([length])
    else:
        b=length.to_bytes((length.bit_length()+7)//8,'big');header=bytes([128|len(b)])+b
    return bytes([tag])+header+value

def integer(value,tag=2):
    b=value.to_bytes(max(1,(value.bit_length()+7)//8),'big')
    if b[0]&128:b=b'\0'+b
    return tlv(tag,b)

def oid(value):
    parts=[int(x) for x in value.split('.')];result=bytearray()
    for n in [40*parts[0]+parts[1]]+parts[2:]:
        chunk=[n&127];n>>=7
        while n:chunk.insert(0,128|(n&127));n>>=7
        result.extend(chunk)
    return tlv(6,bytes(result))

def decode_oid(value):
    result=[];n=0
    for b in value:
        n=(n<<7)|(b&127)
        if not b&128:result.append(n);n=0
    first=result.pop(0);return tuple([min(first//40,2),first-40*min(first//40,2)]+result)

def unpack(data):
    result=[];pos=0
    while pos<len(data):
        tag=data[pos];length=data[pos+1];pos+=2
        if length&128:
            count=length&127;length=int.from_bytes(data[pos:pos+count],'big');pos+=count
        result.append((tag,data[pos:pos+length]));pos+=length
    return result

class Agent:
    def __init__(self):
        self.sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.sock.bind(('127.0.0.1',0));self.sock.settimeout(.2)
        self.port=self.sock.getsockname()[1];self.stopped=threading.Event();self.error=None
        mib={
          '1.3.6.1.2.1.1.1.0':tlv(4,b'Test firewall'),
          '1.3.6.1.2.1.1.2.0':oid('1.3.6.1.4.1.8741'),
          '1.3.6.1.2.1.1.3.0':integer(8640000,0x43),
          '1.3.6.1.2.1.1.5.0':tlv(4,b'FW fixture'),
          '1.3.6.1.2.1.2.2.1.1.2':integer(2),
          '1.3.6.1.2.1.2.2.1.2.2':tlv(4,b'WAN'),
          '1.3.6.1.2.1.2.2.1.7.2':integer(1),
          '1.3.6.1.2.1.2.2.1.8.2':integer(1),
          '1.3.6.1.2.1.2.2.1.10.2':integer(123456,0x41),
          '1.3.6.1.2.1.2.2.1.16.2':integer(456789,0x41),
          '1.3.6.1.2.1.31.1.1.1.1.2':tlv(4,b'X1'),
          '1.3.6.1.2.1.31.1.1.1.6.2':integer(12345678,0x46),
          '1.3.6.1.2.1.31.1.1.1.10.2':integer(45678901,0x46),
          '1.3.6.1.2.1.31.1.1.1.15.2':integer(1000,0x42),
          '1.3.6.1.2.1.31.1.1.1.18.2':tlv(4,b'ISP'),
          '1.3.6.1.4.1.8741.1.3.1.3.0':integer(18,0x42),
          '1.3.6.1.4.1.8741.1.3.1.4.0':integer(42,0x42),
        }
        self.mib={tuple(map(int,k.split('.'))):v for k,v in mib.items()};self.keys=sorted(self.mib)
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def next(self,name):
        nxt=next((x for x in self.keys if x>name),None)
        return (nxt,self.mib[nxt]) if nxt else (name,tlv(0x82,b''))
    def response(self,data):
        root=unpack(unpack(data)[0][1]);version,community,pdu=root;fields=unpack(pdu[1])
        rid,first,second,vbl=fields;names=[decode_oid(unpack(v[1])[0][1]) for v in unpack(vbl[1])]
        bindings=[]
        if pdu[0]==0xa5:
            non=int.from_bytes(first[1],'big');repeat=min(int.from_bytes(second[1],'big'),25)
            bindings.extend(self.next(n) for n in names[:non])
            repeaters=names[non:]
            for _ in range(repeat):
                row=[self.next(n) for n in repeaters];bindings.extend(row);repeaters=[n for n,v in row]
        elif pdu[0]==0xa1:bindings=[self.next(n) for n in names]
        else:bindings=[(n,self.mib.get(n,tlv(0x80,b''))) for n in names]
        vbs=tlv(0x30,b''.join(tlv(0x30,oid('.'.join(map(str,n)))+v) for n,v in bindings))
        return tlv(0x30,tlv(version[0],version[1])+tlv(community[0],community[1])+tlv(0xa2,tlv(rid[0],rid[1])+integer(0)+integer(0)+vbs))
    def run(self):
        while not self.stopped.is_set():
            try:data,peer=self.sock.recvfrom(65535)
            except socket.timeout:continue
            except OSError:break
            try:self.sock.sendto(self.response(data),peer)
            except Exception as e:self.error=e;break
    def close(self):self.stopped.set();self.sock.close();self.thread.join(timeout=1)
