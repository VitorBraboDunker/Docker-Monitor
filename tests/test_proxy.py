import base64,http.server,json,sys,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
PACKAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PACKAGE/'runtime'))
import global_config
import sharepoint_collector as sp,sharepoint_proxy as proxy
class Proxy(unittest.TestCase):
 def test_authenticated_forwarder_and_assets(self):
  with tempfile.TemporaryDirectory() as tmp:
   private=Path(tmp);(private/'gateway_token').write_text('LOCAL-TEST-TOKEN')
   class Backend(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
     body=json.dumps({'path':self.path,'authorized':self.headers.get('Authorization')=='Bearer LOCAL-TEST-TOKEN'}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
   backend=http.server.ThreadingHTTPServer(('127.0.0.1',0),Backend)
   class Front(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def json_response(self,data,status=200):
     self.send_response(status);self.end_headers();self.wfile.write(json.dumps(data).encode())
    def do_GET(self):
     if self.headers.get('Authorization')!='Basic TEST':return self.json_response({'error':'Unauthorized'},401)
     proxy.handle(self)
   front=http.server.ThreadingHTTPServer(('127.0.0.1',0),Front)
   threads=[threading.Thread(target=s.serve_forever,daemon=True) for s in (backend,front)]
   for t in threads:t.start()
   try:
    with patch.object(global_config,'get',return_value='LOCAL-TEST-TOKEN'),patch.object(proxy,'PRIVATE',private),patch.object(proxy,'UPSTREAM',f'http://127.0.0.1:{backend.server_port}'),patch.dict('os.environ',{'DNK_ADMIN_PAGE':str(PACKAGE/'config/admin/index.html')}):
     url=f'http://127.0.0.1:{front.server_port}'
     with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(url+'/api/sharepoint/tenants')
     with urllib.request.urlopen(urllib.request.Request(url+'/api/sharepoint/tenants',headers={'Authorization':'Basic TEST'})) as r:data=json.load(r)
     self.assertEqual(data,{'path':'/api/tenants','authorized':True})
     with urllib.request.urlopen(urllib.request.Request(url+'/sharepoint/',headers={'Authorization':'Basic TEST'})) as r:self.assertIn(b'SharePoint',r.read())
   finally:
    for s in (backend,front):s.shutdown();s.server_close()
    for t in threads:t.join()
if __name__=='__main__':unittest.main()
