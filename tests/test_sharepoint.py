import base64,csv,datetime as dt,importlib.util,io,json,os,sqlite3,sys,tempfile,threading,time,unittest,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
PACKAGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PACKAGE/'runtime'))
import global_config,release_state
import sharepoint_collector as sp
TENANT='11111111-1111-1111-1111-111111111111';CLIENT='22222222-2222-2222-2222-222222222222'
def payload(**extra): return dict(name='Microsoft 365',Cliente='Cliente Teste',tenant_id=TENANT,client_id=CLIENT,client_secret='SECRET-TEST-ONLY',capacity_gib=100,**extra)
def report(day=None):
 day=day or dt.datetime.now(dt.timezone.utc).date().isoformat()
 out=io.StringIO();w=csv.writer(out);w.writerow(['Report Refresh Date','Site Id','Site URL','Is Deleted','Storage Used (Byte)','Storage Allocated (Byte)','File Count'])
 w.writerow([day,'site-a','https://cliente.sharepoint.com/sites/Financeiro','False',85*sp.GIB,25*1024*sp.GIB,42])
 w.writerow([day,'site-b','CONCEALED','False',2*sp.GIB,25*1024*sp.GIB,2])
 w.writerow([day,'deleted','https://cliente.sharepoint.com/sites/Deleted','True',20*sp.GIB,25*1024*sp.GIB,1])
 return ('\ufeff'+out.getvalue()).encode()
def csv_rows(lines):
 out=io.StringIO();writer=csv.DictWriter(out,fieldnames=list(lines[0]));writer.writeheader();writer.writerows(lines)
 return ('\ufeff'+out.getvalue()).encode()
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.old=(sp.PRIVATE,sp.DB_PATH,sp.TOKEN_FILE)
  self.addCleanup(patch.stopall)
  patch.object(global_config,'FILE',Path(self.temp.name)/'credentials.json').start();patch.object(release_state,'DB',Path(self.temp.name)/'history.sqlite3').start()
  sp.PRIVATE=Path(self.temp.name);sp.DB_PATH=sp.PRIVATE/'sp.sqlite';sp.TOKEN_FILE=sp.PRIVATE/'gateway_token';sp.TOKEN_FILE.write_text('PRIVATE-TEST-TOKEN');global_config.put('system','gateway_token','PRIVATE-TEST-TOKEN');sp.JOBS.clear();sp.BUSY.clear();sp.init_db()
 def tearDown(self):
  deadline=time.time()+5
  while sp.BUSY and time.time()<deadline:time.sleep(.01)
  sp.PRIVATE,sp.DB_PATH,sp.TOKEN_FILE=self.old;self.temp.cleanup()
 def save_report(self,day=None):
  cfg=sp.save(payload());row=sp.get_row(cfg['id']);day,sites=sp.parse_report(report(day));sp.commit_report(row,day,sites);return cfg,day,sites
 def test_csv_deleted_and_concealed(self):
  day,sites=sp.parse_report(report());self.assertEqual(len(sites),2);self.assertTrue(sites[1]['concealed']);self.assertEqual(sites[0]['used_bytes'],85*sp.GIB)
 def test_bad_reports(self):
  for raw in [b'error HTML',report().replace(str(85*sp.GIB).encode(),b'-1'),report().replace(b'site-b,',b',')]:
   with self.assertRaises(sp.SafeError):sp.parse_report(raw)
 def test_repeated_site_rows_do_not_double_storage_or_metrics(self):
  lines=list(csv.DictReader(io.StringIO(report().decode('utf-8-sig'))))
  day,sites=sp.parse_report(csv_rows(lines+[lines[0],lines[1]]))
  self.assertEqual(len(sites),2);self.assertEqual(sum(s['used_bytes'] for s in sites),87*sp.GIB)
  self.assertTrue(all(s['report_rows']==2 for s in sites));self.assertIn('2 linha(s)',sp.report_warning(sites))
  cfg=sp.save(payload());sp.commit_report(sp.get_row(cfg['id']),day,sites)
  self.assertIn('2 linha(s)',sp.public(sp.get_row(cfg['id']))['report_warning'])
  metric=next(l for l in sp.metrics().decode().splitlines() if l.startswith('dnk_sharepoint_tenant_used_bytes{'))
  self.assertEqual(float(metric.rsplit(' ',1)[-1]),87*sp.GIB)
 def test_shared_site_ids_with_different_urls_are_stable_and_not_dropped(self):
  lines=list(csv.DictReader(io.StringIO(report().decode('utf-8-sig'))))
  other=dict(lines[0]);other['Site URL']='https://cliente.sharepoint.com/sites/Comercial';other['Storage Used (Byte)']=str(3*sp.GIB)
  raw=lines+[other,lines[0]]
  _,sites=sp.parse_report(csv_rows(raw));_,reversed_sites=sp.parse_report(csv_rows(list(reversed(raw))))
  self.assertEqual(len(sites),3);self.assertEqual(sum(s['used_bytes'] for s in sites),90*sp.GIB)
  self.assertEqual(sites,reversed_sites);self.assertEqual(len({s['site_id'] for s in sites}),3)
  self.assertIn('URLs diferentes',sp.report_warning(sites))
  cfg,secret=sp.normalize(payload(selected_sites=[s['site_id'] for s in sites]));self.assertEqual(len(cfg['selected_sites']),3)
 def test_conflicting_repeated_site_rows_select_one_complete_row_and_warn(self):
  lines=list(csv.DictReader(io.StringIO(report().decode('utf-8-sig'))))
  high=dict(lines[0]);high['Storage Used (Byte)']=str(90*sp.GIB);high['Storage Allocated (Byte)']=str(100*sp.GIB);high['File Count']='7'
  _,sites=sp.parse_report(csv_rows(lines+[high]));_,reversed_sites=sp.parse_report(csv_rows([high]+lines))
  site=next(s for s in sites if s['site_id']=='site-a')
  self.assertEqual(sites,reversed_sites);self.assertEqual(site['used_bytes'],90*sp.GIB)
  self.assertEqual(site['quota_bytes'],100*sp.GIB);self.assertEqual(site['files'],7)
  self.assertTrue(site['report_conflict']);self.assertIn('valores divergentes',sp.report_warning(sites))
 def test_repeated_rows_still_validate_each_row_and_report_date(self):
  lines=list(csv.DictReader(io.StringIO(report().decode('utf-8-sig'))))
  invalid=dict(lines[0]);invalid['Storage Used (Byte)']='-1'
  with self.assertRaises(sp.SafeError):sp.parse_report(csv_rows(lines+[invalid]))
  invalid=dict(lines[0]);invalid['Report Refresh Date']=(dt.datetime.now(dt.timezone.utc).date()-dt.timedelta(days=1)).isoformat()
  with self.assertRaises(sp.SafeError):sp.parse_report(csv_rows(lines+[invalid]))
 def test_secret_never_public_and_no_returned_token(self):
  cfg=sp.save(payload());public=json.dumps(sp.public(sp.get_row(cfg['id'])));self.assertNotIn('SECRET-TEST-ONLY',public)
  self.assertTrue(cfg['secret_configured']);self.assertEqual(os.stat(sp.DB_PATH).st_mode&0o777,0o600)
  self.assertNotIn('SECRET-TEST-ONLY',sp.metrics().decode())
 def test_validation_and_secret_retention(self):
  cfg=sp.save(payload());sp.save({'name':'Novo nome'},cfg['id']);self.assertEqual(sp.get_row(cfg['id'])['secret'],'SECRET-TEST-ONLY')
  for field,val in [('tenant_id','../bad'),('capacity_gib',float('nan')),('enabled','yes'),('interval_hours',1),('selected_sites','bad')]:
   with self.assertRaises(sp.SafeError):sp.save({field:val},cfg['id'])
  with self.assertRaises(sp.SafeError):sp.save({'critical_percent':80},cfg['id'])
  with self.assertRaises(sp.SafeError):sp.save(payload())
 def test_report_dedup_growth_and_persistence(self):
  cfg,day,sites=self.save_report();old=(dt.date.fromisoformat(day)-dt.timedelta(days=7)).isoformat()
  previous=[dict(s,used_bytes=s['used_bytes']//2) for s in sites]
  sp.commit_report(sp.get_row(cfg['id']),old,previous);sp.commit_report(sp.get_row(cfg['id']),day,sites)
  with sp.connect() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0],2)
  self.assertEqual(sp.growth(cfg['id'],day,sites,7),43.5*sp.GIB)
  sp.init_db();self.assertEqual(sp.latest(cfg['id'])['report_date'],day)
 def test_quota_not_sum_and_selection_does_not_change_tenant(self):
  cfg,day,sites=self.save_report();sp.save({'selected_sites':['site-b']},cfg['id']);m=sp.metrics().decode()
  for name,val in [('capacity_bytes',100*sp.GIB),('tenant_used_bytes',87*sp.GIB),('selected_used_bytes',2*sp.GIB),('state',2)]:
   line=next(l for l in m.splitlines() if l.startswith('dnk_sharepoint_'+name+'{'));self.assertEqual(float(line.rsplit(' ',1)[-1]),val)
  self.assertNotIn('site_id="site-a"',m);self.assertIn('site_id="site-b"',m)
 def test_failure_and_stale_cannot_be_green(self):
  cfg,day,sites=self.save_report();self.assertIn('dnk_sharepoint_state',sp.metrics().decode())
  m=sp.metrics(now=time.time()+6*86400).decode();line=next(l for l in m.splitlines() if l.startswith('dnk_sharepoint_state{'));self.assertTrue(line.endswith(' 1'))
  with sp.connect() as db:db.execute('UPDATE tenants SET error=?',('Falha segura',))
  line=next(l for l in sp.metrics().decode().splitlines() if l.startswith('dnk_sharepoint_state{'));self.assertTrue(line.endswith(' 1'))
 def test_unknown_capacity_and_paused(self):
  cfg,day,sites=self.save_report();sp.save({'capacity_gib':0},cfg['id']);m=sp.metrics().decode()
  self.assertTrue(next(l for l in m.splitlines() if l.startswith('dnk_sharepoint_state{')).endswith(' 2'));self.assertNotIn('dnk_sharepoint_utilization_percent{',m)
  sp.save({'enabled':False},cfg['id']);self.assertTrue(next(l for l in sp.metrics().decode().splitlines() if l.startswith('dnk_sharepoint_state{')).endswith(' 5'))
 def test_soft_delete_restore_credentials_and_same_history(self):
  cfg,day,sites=self.save_report();ident=cfg['id'];row=sp.get_row(ident)
  value=json.loads(row['config']);value.update(deleted_at=time.time(),previous_enabled=True,enabled=False)
  with sp.connect() as db:db.execute('UPDATE tenants SET config=?,revision=? WHERE id=?',(json.dumps(value),'deleted-revision',ident))
  self.assertEqual(sp.rows(),[]);self.assertEqual(sp.rows(True)[0]['id'],ident);self.assertEqual(sp.get_row(ident)['secret'],'SECRET-TEST-ONLY')
  self.assertNotIn('dnk_sharepoint_enabled{',sp.metrics().decode());self.assertIsNotNone(sp.latest(ident))
  with self.assertRaises(sp.SafeError):sp.commit_report(row,day,sites)
  value.pop('deleted_at');value['enabled']=value.pop('previous_enabled')
  with sp.connect() as db:db.execute('UPDATE tenants SET config=?,revision=? WHERE id=?',(json.dumps(value),'restore-revision',ident))
  self.assertEqual(sp.rows()[0]['id'],ident);self.assertIsNotNone(sp.latest(ident))
 def test_revision_guard(self):
  cfg=sp.save(payload());row=sp.get_row(cfg['id']);sp.save({'name':'Alterado'},cfg['id']);day,sites=sp.parse_report(report())
  with self.assertRaises(sp.SafeError):sp.commit_report(row,day,sites)
  self.assertIsNone(sp.latest(cfg['id']))
 def test_graph_redirect_removes_bearer(self):
  cfg,secret=sp.normalize(payload());calls=[]
  def fake(url,headers=None,data=None):
   calls.append((url,headers,data))
   if 'login.microsoftonline' in url:return 200,{},b'{"access_token":"TOKEN-TEST-ONLY"}'
   if 'graph.microsoft' in url:return 302,{'Location':'https://reports.office.com/data/download/test'},b''
   return 200,{},report()
  with patch.object(sp,'request',fake):day,sites=sp.fetch_report(cfg,secret)
  self.assertEqual(len(sites),2);self.assertEqual(calls[1][1]['Authorization'],'Bearer TOKEN-TEST-ONLY');self.assertIsNone(calls[2][1])
  with patch.object(sp,'request',side_effect=[(200,{},b'{"access_token":"token"}'),(302,{'Location':'http://127.0.0.1:9090/private'},b'')]):
   with self.assertRaises(sp.SafeError):sp.fetch_report(cfg,secret)
 def test_report_download_chain_validates_each_hop_and_never_sends_token(self):
  cfg,secret=sp.normalize(payload());calls=[]
  replies=[(200,{},b'{"access_token":"TOKEN-PRIVATE"}'),
   (302,{'location':' HTTPS://REPORTS.OFFICE.COM:443/data/download/one?secret=PRIVATE '},b''),
   (307,{'LOCATION':'/data/download/two?secret=PRIVATE'},b''),(200,{},report())]
  def fake(url,headers=None,data=None):calls.append((url,headers));return replies.pop(0)
  with patch.object(sp,'request',fake):self.assertEqual(len(sp.fetch_report(cfg,secret)[1]),2)
  self.assertEqual(calls[1][1]['Authorization'],'Bearer TOKEN-PRIVATE')
  self.assertTrue(all(headers is None for _,headers in calls[2:]))
  with patch.object(sp,'request',return_value=(302,{'Location':'https://evil.example/data/download/PRIVATE'},b'')) as req:
   with self.assertRaises(sp.SafeError) as error:sp.download_report({'Location':'https://reports.office.com/data/download/test'})
   self.assertEqual(req.call_count,1);self.assertNotIn('PRIVATE',str(error.exception))
 def test_ncu_regional_report_download_preserves_signed_url_without_bearer(self):
  cfg,secret=sp.normalize(payload())
  for target in ['https://reportsncu.office.com/data/v1.0/download?token=SIGNED-PRIVATE&format=csv',
                 'https://reportsncu.office.com/data/download/SIGNED-PRIVATE',
                 'https://reports.office.com/data/v1.0/download?token=SIGNED-PRIVATE']:
   with self.subTest(target=target):
    replies=[(200,{},b'{"access_token":"GRAPH-PRIVATE"}'),(302,{'Location':target},b''),(200,{},report())]
    with patch.object(sp,'request',side_effect=replies) as req:
     self.assertEqual(len(sp.fetch_report(cfg,secret)[1]),2)
     self.assertEqual(req.call_args_list[1].args[1]['Authorization'],'Bearer GRAPH-PRIVATE')
     self.assertEqual(req.call_args_list[2].args,(target,))
     self.assertEqual(req.call_args_list[2].kwargs,{})
  for target in ['https://reportsncu.office.com.evil.example/data/v1.0/download?token=SIGNED-PRIVATE',
                 'https://evil.reportsncu.office.com/data/v1.0/download?token=SIGNED-PRIVATE',
                 'https://reportsncu.office.com/data/v1.0/download/extra?token=SIGNED-PRIVATE',
                 'https://reportsncu.office.com/internal/ux?token=SIGNED-PRIVATE',
                 'http://reportsncu.office.com/data/v1.0/download?token=SIGNED-PRIVATE']:
   with self.subTest(target=target),self.assertRaises(sp.SafeError) as error:
    sp.report_location({'Location':target})
   self.assertNotIn('SIGNED-PRIVATE',str(error.exception))
 def test_report_destinations_missing_malformed_lookalike_and_loops(self):
  invalid=['http://reports.office.com/data/download/test','https://127.0.0.1/data/download/test',
   'https://reports.office.com.evil.example/data/download/PRIVATE',
   'https://evil.reports.office.com/data/download/PRIVATE',
   'https://user:PRIVATE@reports.office.com/data/download/test',
   'https://reports.office.com:444/data/download/test','https://reports.office.com:bad/data/download/PRIVATE',
   'https://reports.office.com/other/PRIVATE','https://reports.office.com/data/download/test#PRIVATE',
   'https://reports.office.com/data/download/\nPRIVATE','https://reports.office.com\\@evil.example/data/download/PRIVATE']
  for target in invalid:
   with self.subTest(target=target),self.assertRaises(sp.SafeError) as error:sp.report_location({'Location':target})
   self.assertNotIn('PRIVATE',str(error.exception))
  for headers in [{},{'Location':''},{'Location':None}]:
   with self.assertRaises(sp.SafeError):sp.report_location(headers)
  with patch.object(sp,'request',return_value=(302,{'Location':'/data/download/test'},b'')) as req:
   with self.assertRaises(sp.SafeError):sp.download_report({'Location':'https://reports.office.com/data/download/test'})
   self.assertEqual(req.call_count,4)
 def test_http_transport_returns_redirect_without_following_it(self):
  calls=[]
  class RedirectServer(sp.http.server.BaseHTTPRequestHandler):
   def do_GET(self):
    calls.append((self.path,self.headers.get('Authorization')))
    self.send_response(302);self.send_header('Location','/private');self.end_headers()
   def log_message(self,*args):pass
  server=sp.http.server.ThreadingHTTPServer(('127.0.0.1',0),RedirectServer)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   status,headers,raw=sp.request(f'http://127.0.0.1:{server.server_port}/graph',{'Authorization':'Bearer TEST'})
   self.assertEqual(status,302);self.assertEqual(headers['Location'],'/private')
   self.assertEqual(calls,[('/graph','Bearer TEST')])
  finally:server.shutdown();server.server_close();thread.join()
 def test_tb_capacity_persistence_legacy_and_metrics(self):
  cfg=sp.save(payload());sp.save({'capacity_value':1.5,'capacity_unit':'TB'},cfg['id'])
  fresh=sp.public(sp.get_row(cfg['id']));self.assertEqual(fresh['capacity_value'],1.5)
  self.assertEqual(fresh['capacity_gib'],1536);self.assertEqual(fresh['capacity_unit'],'TB')
  self.assertEqual(float(next(l for l in sp.metrics().decode().splitlines() if l.startswith('dnk_sharepoint_capacity_bytes{')).rsplit(' ',1)[-1]),1.5*2**40)
  sp.save({'name':'Mesmo valor'},cfg['id']);self.assertEqual(sp.public(sp.get_row(cfg['id']))['capacity_value'],1.5)
  sp.save({'capacity_gib':2048},cfg['id']);self.assertEqual(sp.public(sp.get_row(cfg['id']))['capacity_value'],2)
  for p in [{'capacity_unit':'PB'},{'capacity_value':float('nan')},{'capacity_value':-1},{'capacity_value':100000000,'capacity_unit':'TB'}]:
   with self.assertRaises(sp.SafeError):sp.save(p,cfg['id'])
  with sp.connect() as db:
   old=json.loads(sp.get_row(cfg['id'])['config']);old.pop('capacity_unit');db.execute('UPDATE tenants SET config=? WHERE id=?',(json.dumps(old),cfg['id']))
  self.assertEqual(sp.public(sp.get_row(cfg['id']))['capacity_unit'],'GB')
 def test_async_jobs_redact_unexpected_errors(self):
  cfg=sp.save(payload());event=threading.Event()
  def fake(*args):event.wait(2);raise RuntimeError('SECRET-TEST-ONLY https://private-token')
  with patch.object(sp,'fetch_report',fake):
   job=sp.enqueue(tenant=cfg['id'])
   with self.assertRaises(sp.SafeError):sp.enqueue(tenant=cfg['id'])
   event.set()
   for _ in range(100):
    if sp.JOBS[job['job_id']]['state']!='running':break
    time.sleep(.01)
  self.assertEqual(sp.JOBS[job['job_id']]['state'],'error');self.assertNotIn('SECRET-TEST-ONLY',json.dumps(sp.JOBS))
 def test_http_crud_auth_csv_and_history_preserved(self):
  server=sp.http.server.ThreadingHTTPServer(('127.0.0.1',0),sp.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
  def req(path,method='GET',data=None,auth=True):
   headers={'Content-Type':'application/json'}
   if auth:headers['Authorization']='Bearer PRIVATE-TEST-TOKEN'
   with urllib.request.urlopen(urllib.request.Request(base+path,headers=headers,method=method,data=json.dumps(data).encode() if data is not None else None)) as r:return r.read()
  try:
   with self.assertRaises(urllib.error.HTTPError) as e:req('/api/tenants',auth=False)
   self.assertEqual(e.exception.code,401)
   cfg=json.loads(req('/api/tenants','POST',payload()));day,sites=sp.parse_report(report());sp.commit_report(sp.get_row(cfg['id']),day,sites)
   self.assertEqual(json.loads(req('/api/tenants/'+cfg['id']+'/sites'))['sites'][0]['site_id'],'site-a')
   exported=req('/api/tenants/'+cfg['id']+'/export');self.assertIn(b'Uso bytes',exported);self.assertNotIn(b'SECRET-TEST-ONLY',exported)
   req('/api/tenants/'+cfg['id'],'DELETE');self.assertEqual(json.loads(req('/api/tenants')),[]);self.assertIsNotNone(sp.latest(cfg['id']))
  finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':unittest.main()
