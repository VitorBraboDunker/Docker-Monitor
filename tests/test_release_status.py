import json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'runtime'))
import status_engine as s,alloy_builder as b,release_state as history
class Status(unittest.TestCase):
 def asset(self,status,category='links',client='Customer'):
  return {'asset_id':'a','category':category,'CLIENTE':client,'UNIDADE':'HQ','instance':'host','name':'Host','status':status}
 def series(self,values,now=1000):return [({'__name__':k,'monitor_id':'a'},v,now) for k,v in values.items()]
 def test_any_enabled_anomaly_marks_entire_client_and_paused_is_ignored(self):
  for state in (1,2,3,4):
   rows=[self.asset(0),self.asset(state,'sharepoint')];self.assertEqual(s.grouped(rows,False)[0]['conformity'],1)
  self.assertEqual(s.grouped([self.asset(0),self.asset(5,'servidores')],False)[0]['conformity'],0)
  self.assertEqual(s.grouped([self.asset(5)],False)[0]['conformity'],2)
 def test_complete_outage_distinct_from_missing_collector(self):
  row={'id':'a','tipo':'icmp'}
  series=self.series({'dnk_check_timestamp_seconds':1000,'dnk_check_success':0,'dnk_ping_collector_success':1,'dnk_ping_loss_percent':100})
  self.assertEqual(s.evaluate(row,'links',series,1000,s.DEFAULTS)[0],4)
  self.assertEqual(s.evaluate(row,'links',series,2000,s.DEFAULTS)[0],1)
  series=self.series({'dnk_check_timestamp_seconds':1000,'dnk_check_success':0,'dnk_ping_collector_success':0})
  self.assertEqual(s.evaluate(row,'links',series,1000,s.DEFAULTS)[0],1)
 def test_durations_recovery_and_restart_state(self):
  a=self.asset(0);a.pop('status')
  first=s.transition(dict(a),2,'latency',{},1000,s.DEFAULTS,{})
  second=s.transition(dict(a),2,'latency',{},1601,s.DEFAULTS,first);self.assertEqual(second['status'],3)
  third=s.transition(dict(a),2,'latency',{},2801,s.DEFAULTS,second);self.assertEqual(third['status'],4)
  recovered=s.transition(dict(a),0,'healthy',{},2900,s.DEFAULTS,third);self.assertEqual(recovered['status'],2)
  recovered2=s.transition(dict(a),0,'healthy',{},3000,s.DEFAULTS,recovered);self.assertEqual(recovered2['status'],2)
  healthy=s.transition(dict(a),0,'healthy',{},3501,s.DEFAULTS,recovered2);self.assertEqual(healthy['status'],0)
  with tempfile.TemporaryDirectory() as tmp,patch.object(history,'DB',Path(tmp)/'history.sqlite3'):
   history.save(first);self.assertEqual(history.previous('a')['incident_since'],1000)
   history.save(third);export=history.export('links');self.assertEqual(len(export['events']),2);self.assertEqual(len(export['samples']),2)
 def test_partial_server_metrics_are_not_green(self):
  row={'id':'a','items':['cpu','memory']};series=self.series({'dnk:server_observed_timestamp_seconds':1000,'dnk:server_cpu_percent':20})
  self.assertEqual(s.evaluate(row,'servidores',series,1000,s.DEFAULTS)[0],1)
 def test_alloy_selection_labels_and_dependencies(self):
  for osname in ('windows','linux'):
   cfg=b.build({'CLIENTE':'Customer','UNIDADE':'HQ','instance':'HOST-1','os':osname,'items':['cpu','memory','logs']},'https://monitor.example.com')
   text=cfg['config'];self.assertIn('target_label = "CLIENTE"',text);self.assertIn('target_label = "UNIDADE"',text);self.assertIn('prometheus.remote_write.dunker.receiver',text)
   self.assertIn('sys.env("DNK_INGEST_PASSWORD")',text);self.assertNotIn('password_file',text);self.assertIn('loki.write.dunker.receiver',text);self.assertNotIn('logical_disk',text)
  with self.assertRaises(ValueError):b.build({'items':['bad']},'http://host')
 def test_deleted_asset_immediately_absent_and_pause_is_black(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'targets').mkdir();(root/'targets/inventory.json').write_text(json.dumps([{'id':'a','deleted_at':1}]))
   with patch.object(s,'ROOT',root),patch.object(s,'CACHE',[{**self.asset(0),'reason':'OK','data':{}}]),patch.object(s,'LAST',time.time()):self.assertEqual(s.snapshot()['assets'],[])
   (root/'targets/inventory.json').write_text(json.dumps([{'id':'a','enabled':False}]))
   with patch.object(s,'ROOT',root),patch.object(s,'CACHE',[{**self.asset(0),'reason':'OK','data':{}}]),patch.object(s,'LAST',time.time()):self.assertEqual(s.snapshot()['assets'][0]['status'],5)
