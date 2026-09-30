import sys,unittest,tempfile,json,threading,urllib.request,urllib.error,base64
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
import admin_monitor as a,ping_exporter as p
class Checks(unittest.TestCase):
 def test_crud_and_auth(self):
  with tempfile.TemporaryDirectory() as tmp:
   a.DATA_DIR=Path(tmp);a.INVENTORY=a.DATA_DIR/'inventory.json';a.ICMP_TARGETS=a.DATA_DIR/'icmp.json';a.PASSWORD_FILE=a.DATA_DIR/'password';a.PASSWORD_FILE.write_text('test-only');a.persist([])
   server=a.http.server.ThreadingHTTPServer(('127.0.0.1',0),a.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
   auth='Basic '+base64.b64encode(b'admin:test-only').decode()
   def req(path,method='GET',body=None,authorized=True):
    headers={'Content-Type':'application/json'}
    if authorized:headers['Authorization']=auth
    with urllib.request.urlopen(urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)) as r:return json.load(r)
   try:
    with self.assertRaises(urllib.error.HTTPError) as error:req('/api/monitors',authorized=False)
    self.assertEqual(error.exception.code,401)
    row=req('/api/monitors','POST',{'name':'Local','instance':'127.0.0.1','Cliente':'Dunker','Unidade':'LAB','Provedor':'Interno','interval_seconds':10})
    self.assertEqual(req('/api/monitors')[0]['id'],row['id']);self.assertEqual(json.loads(a.ICMP_TARGETS.read_text())[0]['targets'],['127.0.0.1'])
    p.INVENTORY=str(a.INVENTORY);self.assertIn(b'dnk_ping_config_interval_seconds',p.render_metrics());self.assertEqual(p.inventory()[0]['id'],row['id'])
    with self.assertRaises(urllib.error.HTTPError):req('/api/monitors','POST',dict(row,instance='bad'))
    req('/api/monitors/'+row['id'],'PUT',{'enabled':False});self.assertEqual(json.loads(a.ICMP_TARGETS.read_text()),[])
    req('/api/monitors/'+row['id'],'DELETE');self.assertEqual(req('/api/monitors'),[])
   finally:server.shutdown();server.server_close();thread.join()
 def test_icmp_reply_validation(self):
  import struct
  nonce=b'test';packet=struct.pack('!BBHHH',0,0,0,42,1)+nonce
  self.assertTrue(p.parse_reply(packet,42,1,nonce));self.assertFalse(p.parse_reply(packet,43,1,nonce));self.assertFalse(p.parse_reply(packet,42,2,nonce))
 def test_real_loopback_ping(self):
  result=p.probe('127.0.0.1',2,1,0.1);
  if not result['success']:self.skipTest('ICMP sockets blocked by execution environment')
  self.assertEqual(result['received'],2);self.assertEqual(result['loss'],0)
if __name__=='__main__':unittest.main()
