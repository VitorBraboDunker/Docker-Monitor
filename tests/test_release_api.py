import http.server,json,sys,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'runtime'))
import admin_monitor as a,global_config as gc,release_state as hist,grafana_access as access,status_engine as status
class Api(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.addCleanup(self.tmp.cleanup);self.addCleanup(patch.stopall)
  for module,key,value in [(a,'DATA_DIR',self.root/'targets'),(a,'INVENTORY',self.root/'targets/inventory.json'),(gc,'DOMAINS',self.root/'domains.json'),(gc,'FILE',self.root/'credentials.json'),(hist,'DB',self.root/'history.sqlite3'),(access,'POLICY_FILE',self.root/'policy.json')]:patch.object(module,key,value).start()
  gc.DOMAINS.write_text(json.dumps({'access':{'public_url':'http://monitor:8443'}}));a.persist([])
  patch.object(access,'identity',return_value={'id':1,'login':'admin','role':'Admin','org_id':1,'cookie':'x'}).start()
  self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),a.Handler);threading.Thread(target=self.server.serve_forever,daemon=True).start();self.base=f'http://127.0.0.1:{self.server.server_port}'
  self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
 def request(self,path,method='GET',data=None):
  req=urllib.request.Request(self.base+path,method=method,data=json.dumps(data).encode() if data is not None else None,headers={'Cookie':'session','Origin':self.base,'Content-Type':'application/json'})
  with urllib.request.urlopen(req) as r:return json.load(r)
 def test_alloy_server_pause_delete_restore_export(self):
  result=self.request('/api/alloy','POST',{'CLIENTE':'Customer','UNIDADE':'HQ','instance':'SRV','os':'windows','items':['cpu','memory','disk']});ident=result['asset_id']
  self.assertNotIn('secret',result['config']);self.assertEqual(a.load_inventory()[0]['id'],ident)
  with self.assertRaises(urllib.error.HTTPError):self.request('/api/alloy','POST',{'CLIENTE':'Customer','UNIDADE':'HQ','instance':'SRV','items':['cpu']})
  self.request('/api/servers/servidores/'+ident,'POST',{'enabled':False});self.assertFalse(a.load_inventory()[0]['enabled'])
  self.request('/api/servers/servidores/'+ident,'POST',{'delete':True});self.assertTrue(self.request('/api/deleted/servidores')[0]['deleted_at'])
  self.request('/api/restore/servidores/'+ident,'POST',{});self.assertFalse(a.load_inventory()[0]['enabled']);self.assertEqual(self.request('/api/deleted/servidores'),[])
  exported=self.request('/api/history/servidores');self.assertEqual(exported['inventory'][0]['id'],ident);self.assertEqual(len(exported['events']),4)
 def test_links_archive_restore_and_history(self):
  row=self.request('/api/monitors','POST',{'name':'Link','CLIENTE':'C','UNIDADE':'HQ','Provedor':'ISP','instance':'127.0.0.1'})
  self.request('/api/monitors/'+row['id'],'DELETE');self.assertEqual(self.request('/api/monitors'),[])
  self.assertEqual(self.request('/api/deleted/links')[0]['id'],row['id'])
  self.request('/api/restore/links/'+row['id'],'POST',{});self.assertEqual(self.request('/api/monitors')[0]['id'],row['id'])
  self.assertEqual(len(self.request('/api/history/links')['events']),3)
 def test_read_only_profile_cannot_generate_or_restore(self):
  with patch.object(access,'identity',return_value={'id':2,'login':'viewer','role':'Viewer','org_id':1,'cookie':'x'}):
   self.assertEqual(self.request('/api/deleted/servidores'),[])
   with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/alloy','POST',{'CLIENTE':'C'})
   self.assertEqual(error.exception.code,403)
