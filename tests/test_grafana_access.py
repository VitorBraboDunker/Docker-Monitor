import http.server,json,tempfile,threading,unittest,urllib.request,urllib.error,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
import grafana_access as g,admin_monitor as a

class Access(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name);self.role='Viewer';self.outage=False;self.rotate=False
  owner=self
  class Grafana(http.server.BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    cookie=self.headers.get('Cookie','');role=owner.role
    if owner.outage:return self.send(503,{})
    if 'grafana_session=valid' not in cookie and not (owner.rotate and 'grafana_session=rotated' in cookie):return self.send(401,{})
    if owner.rotate and self.path=='/api/user/orgs' and 'grafana_session=rotated' not in cookie:return self.send(401,{})
    if self.path=='/api/user':return self.send(200,{'id':7,'login':'vitor','orgId':1})
    if self.path=='/api/user/orgs':return self.send(200,[{'orgId':1,'role':role}])
    if self.path=='/api/org/users':return self.send(200,[{'userId':7,'login':'vitor','role':role}])
    return self.send(404,{})
   def send(self,status,data):
    self.send_response(status)
    if owner.rotate and self.path=='/api/user':self.send_header('Set-Cookie','grafana_session=rotated; Path=/; HttpOnly; SameSite=Lax')
    self.end_headers();self.wfile.write(json.dumps(data).encode())
  self.gf=http.server.ThreadingHTTPServer(('127.0.0.1',0),Grafana)
  self.front=http.server.ThreadingHTTPServer(('127.0.0.1',0),a.Handler)
  self.patches=[patch.object(g,'GRAFANA_URL',f'http://127.0.0.1:{self.gf.server_port}'),patch.object(g,'POLICY_FILE',self.path/'policy.json'),patch.object(a,'DATA_DIR',self.path),patch.object(a,'INVENTORY',self.path/'inventory.json'),patch.object(a,'ICMP_TARGETS',self.path/'icmp.json')]
  for p in self.patches:p.start()
  a.persist([])
  self.threads=[]
  for s in [self.gf,self.front]:
   t=threading.Thread(target=s.serve_forever,daemon=True);t.start();self.threads.append(t)
  self.base=f'http://127.0.0.1:{self.front.server_port}'
 def tearDown(self):
  for s in [self.front,self.gf]:s.shutdown();s.server_close()
  for t in self.threads:t.join()
  for p in reversed(self.patches):p.stop()
  self.tmp.cleanup()
 def req(self,path,method='GET',data=None,cookie='valid',origin=True,headers=None):
  h={'Content-Type':'application/json'}
  if cookie:h['Cookie']='grafana_session='+cookie
  if origin:h['Origin']=self.base
  h.update(headers or {})
  req=urllib.request.Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers=h,method=method)
  try:
   with urllib.request.urlopen(req) as r:return r.status,json.loads(r.read() or b'{}')
  except urllib.error.HTTPError as e:return e.code,json.loads(e.read() or b'{}')
 def row(self):return {'name':'Local','instance':'127.0.0.1','Cliente':'Dunker','Unidade':'LAB','Provedor':'Interno'}
 def test_sessions_and_spoofing_fail_closed(self):
  self.assertEqual(self.req('/api/monitors',cookie=None,headers={'Authorization':'Basic YWRtaW46cGFzcw==','X-Grafana-User':'admin','X-Grafana-Role':'Admin'})[0],401)
  self.assertEqual(self.req('/api/access/me',cookie='invalid')[0],401)
  self.assertEqual(self.req('/api/access/me')[1]['role'],'Viewer')
  self.outage=True;self.assertEqual(self.req('/api/monitors')[0],503)
 def test_viewer_cannot_write_or_manage_and_role_is_fresh(self):
  for endpoint in ['/api/monitors','/api/test','/api/devices','/api/devices/test','/api/sharepoint/test']:
   self.assertEqual(self.req(endpoint,'POST',self.row())[0],403)
  self.assertEqual(self.req('/api/access/policy')[0],403)
  self.assertEqual(self.req('/api/monitors')[0],200)
  self.role='Editor';status,row=self.req('/api/monitors','POST',self.row());self.assertEqual(status,201)
  self.role='Viewer';self.assertEqual(self.req('/api/monitors/'+row['id'],'DELETE')[0],403)
  self.role='Editor';self.assertEqual(self.req('/api/monitors/'+row['id'],'DELETE')[0],200)
 def test_admin_profiles_and_immediate_revocation(self):
  self.role='Admin';self.assertEqual(self.req('/api/access/users')[1][0]['id'],7)
  policy=self.req('/api/access/policy')[1]
  policy['profiles']['links_only']={'name':'Somente links','permissions':{'links':'edit','snmp':'none','sharepoint':'none'}}
  policy['users']['7']='links_only'
  self.assertEqual(self.req('/api/access/policy','PUT',policy)[0],200)
  self.role='Viewer';self.assertEqual(self.req('/api/monitors','POST',self.row())[0],201)
  self.assertEqual(self.req('/api/devices')[0],403)
  self.assertEqual(self.req('/api/sharepoint/tenants')[0],403)
  policy['profiles']['links_only']['permissions']['links']='none';g.save_policy(policy)
  self.assertEqual(self.req('/api/monitors')[0],403)
  self.role='Admin';self.assertTrue(self.req('/api/access/me')[1]['manage_access'])
 def test_default_profiles_apply_to_new_users(self):
  policy=g.load_policy();policy['role_profiles']['Viewer']='paineis';g.save_policy(policy)
  self.assertEqual(self.req('/api/monitors')[0],403)
  self.assertEqual(self.req('/api/access/me')[1]['profile'],'Somente dashboards')
 def test_csrf_and_corrupt_policy(self):
  self.role='Admin'
  self.assertEqual(self.req('/api/monitors','POST',self.row(),origin=False)[0],403)
  self.assertEqual(self.req('/api/monitors','POST',self.row(),headers={'Origin':'https://evil.example'})[0],403)
  self.assertEqual(self.req('/api/monitors','POST',self.row(),headers={'Sec-Fetch-Site':'cross-site'})[0],403)
  g.POLICY_FILE.write_text('{bad');self.assertEqual(self.req('/api/monitors')[0],503)
 def test_invalid_policy_does_not_replace_saved_policy(self):
  self.role='Admin';g.save_policy(g.DEFAULT_POLICY);old=g.POLICY_FILE.read_bytes()
  invalid=g.load_policy();invalid['profiles']['consulta']['permissions']['snmp']='admin'
  self.assertEqual(self.req('/api/access/policy','PUT',invalid)[0],400)
  self.assertEqual(g.POLICY_FILE.read_bytes(),old)
 def test_links_endpoint_cannot_mutate_snmp(self):
  self.role='Editor'
  id='c7c3b378-037b-49a8-b7d6-bb6e83159a00'
  a.persist([{'id':id,'tipo':'snmp','managed_snmp':True,'instance':'127.0.0.1'}])
  self.assertEqual(self.req('/api/monitors/'+id,'PUT',self.row())[0],404)
  self.assertEqual(self.req('/api/monitors/'+id,'DELETE')[0],404)
  self.assertEqual(a.load_inventory()[0]['id'],id)
  self.assertEqual(self.req('/api/monitors','POST',dict(self.row(),managed_snmp=True))[0],400)
 def test_grafana_session_rotation_is_relayed(self):
  self.rotate=True
  with urllib.request.urlopen(urllib.request.Request(self.base+'/api/access/me',headers={'Cookie':'grafana_session=valid'})) as r:
   self.assertIn('grafana_session=rotated',r.headers['Set-Cookie'])
   data=json.load(r);self.assertNotIn('cookie',data);self.assertNotIn('_cookies',data)
 def test_legacy_page_redirects_into_native_app(self):
  class NoRedirect(urllib.request.HTTPRedirectHandler):
   def redirect_request(self,*args):return None
  for path,target in [('/', 'links'),('/sharepoint/', 'sharepoint')]:
   with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.build_opener(NoRedirect).open(self.base+path)
   self.assertEqual(e.exception.code,302)
   self.assertEqual(e.exception.headers['Location'],'/a/dunker-integracoes-app/'+target)
 def test_bootstrap_preserves_supported_legacy_metadata(self):
  row=a.bootstrap_row(dict(self.row(),tipo='icmp',job='old-job',probe='SaoPaulo'))
  self.assertEqual(row['tipo'],'icmp');self.assertTrue(row['id'])

 def test_wrong_org_is_denied(self):
  with patch.object(g,'ORG_ID',2):self.assertEqual(self.req('/api/monitors')[0],403)
 def test_unknown_and_query_alias_routes_denied(self):
  self.role='Admin'
  self.assertEqual(self.req('/api/monitors?anything')[0],404)
  self.assertEqual(self.req('/api/secrets')[0],404)

if __name__=='__main__':unittest.main()
