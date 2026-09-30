import http.server,json,socket,struct,sys,threading,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
import admin_monitor as a,monitor_probes as m,ping_exporter as p
BASE={'name':'Teste','Cliente':'Dunker','Unidade':'LAB','Provedor':'Interno','timeout_seconds':1}
class HTTP(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(302 if self.path=='/redirect' else 204)
  if self.path=='/redirect':self.send_header('Location','/ok')
  self.end_headers()
 def log_message(self,*args):pass
class Probes(unittest.TestCase):
 def test_http_status_and_redirect(self):
  server=http.server.ThreadingHTTPServer(('127.0.0.1',0),HTTP);threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   row=a.normalize(dict(BASE,tipo='http',instance=f'http://127.0.0.1:{server.server_port}/redirect'))
   self.assertEqual(m.probe_service(row)['http_status_code'],204)
   row.update(follow_redirects=False,expected_status=302);self.assertEqual(m.probe_service(row)['success'],1)
   row['expected_status']=200;self.assertEqual(m.probe_service(row)['success'],0)
  finally:server.shutdown();server.server_close()
 def test_tcp_connect(self):
  with socket.socket() as server:
   server.bind(('127.0.0.1',0));server.listen()
   row=a.normalize(dict(BASE,tipo='tcp',instance='127.0.0.1',tcp_host='127.0.0.1',tcp_port=server.getsockname()[1]))
   self.assertEqual(m.probe_service(row)['success'],1)
 def test_dns_response(self):
  with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as server:
   server.bind(('127.0.0.1',0));server.settimeout(2)
   def reply():
    query,addr=server.recvfrom(4096)
    response=query[:2]+struct.pack('!HHHHH',0x8180,1,1,0,0)+query[12:]+b'\xc0\x0c'+struct.pack('!HHIH',1,1,30,4)+socket.inet_aton('127.0.0.1')
    server.sendto(response,addr)
   t=threading.Thread(target=reply);t.start()
   row=a.normalize(dict(BASE,tipo='dns',instance='127.0.0.1',dns_name='example.com',dns_port=server.getsockname()[1]))
   result=m.probe_service(row);t.join();self.assertEqual(result['success'],1);self.assertEqual(result['dns_answers'],1)
 def test_protocol_inventory_and_metrics(self):
  with tempfile.TemporaryDirectory() as tmp:
   a.DATA_DIR=Path(tmp);a.INVENTORY=a.DATA_DIR/'inventory.json'
   rows=[a.normalize(dict(BASE,tipo='http',instance='https://example.com')),a.normalize(dict(BASE,tipo='dns',instance='1.1.1.1',dns_name='example.com'))]
   a.persist(rows);p.INVENTORY=str(a.INVENTORY)
   self.assertEqual(len(p.inventory()),2);self.assertEqual(json.loads((a.DATA_DIR/'http.json').read_text()),[])
   p.RESULTS={p.label_string(rows[0]):{'success':1,'duration':.05,'timestamp':10,'http_status_code':204}}
   metrics=p.render_metrics().decode();self.assertIn('dnk_check_success{',metrics);self.assertIn('dnk_check_http_status_code{',metrics)
   self.assertNotIn('criticidade',metrics)
 def test_invalid_values(self):
  for payload in [dict(BASE,tipo='http',instance='ftp://example.com'),dict(BASE,tipo='tcp',instance='example.com',tcp_port=0,tcp_host='example.com'),dict(BASE,tipo='dns',instance='1.1.1.1',dns_name='bad name')]:
   with self.assertRaises(ValueError):a.normalize(payload)
if __name__=='__main__':unittest.main()
