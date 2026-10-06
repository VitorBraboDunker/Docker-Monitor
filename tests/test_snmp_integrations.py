import base64
import http.server
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/vendor'))
import yaml
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
import admin_monitor as a
import snmp_manager as s
import ping_exporter as p
from snmp_fixture import Agent

PAYLOAD={'name':'Firewall Matriz','Cliente':'Dunker','Unidade':'SP','host':'127.0.0.1','vendor':'sonicwall','version':'2','credentials':{'community':'unit-test-secret'},'interfaces':[{'ifIndex':'2','name':'X1','download_mbps':300,'upload_mbps':100}]}

class Integrations(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.dir=Path(self.tmp.name)
  self.previous=(a.DATA_DIR,a.INVENTORY,a.PASSWORD_FILE,s.PRIVATE,s.MODULES,p.INVENTORY)
  a.DATA_DIR=self.dir/'targets';a.INVENTORY=a.DATA_DIR/'inventory.json';a.PASSWORD_FILE=self.dir/'password'
  a.PASSWORD_FILE.write_text('test-only');s.PRIVATE=self.dir/'private';s.MODULES=ROOT/'config/integracoes/modules.json'
  a.persist([]);self.mock=patch.object(s,'reload_exporter');self.mock.start()
  self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),a.Handler)
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.base=f'http://127.0.0.1:{self.server.server_port}'
  import grafana_access as g
  self.identity=patch.object(g,'identity',return_value={'id':1,'login':'admin','role':'Admin','org_id':1,'cookie':'test-only'});self.identity.start()
  self.policy=patch.object(g,'POLICY_FILE',self.dir/'policy.json');self.policy.start()
 def tearDown(self):
  self.server.shutdown();self.server.server_close();self.thread.join();self.mock.stop();self.identity.stop();self.policy.stop()
  a.DATA_DIR,a.INVENTORY,a.PASSWORD_FILE,s.PRIVATE,s.MODULES,p.INVENTORY=self.previous;self.tmp.cleanup()
 def req(self,path,method='GET',data=None,origin=None):
  headers={'Cookie':'grafana_session=test-only','Content-Type':'application/json'}
  headers['Origin']=origin or self.base
  req=urllib.request.Request(self.base+path,headers=headers,method=method,data=json.dumps(data).encode() if data is not None else None)
  with urllib.request.urlopen(req) as r:return json.load(r)
 def test_crud_preserves_links_and_credentials_never_leak(self):
  a.persist([a.normalize({'name':'Link','instance':'127.0.0.1','Cliente':'Dunker','Unidade':'SP','Provedor':'Link'})])
  legacy=[{'targets':['10.0.0.1'],'labels':{'snmp_auth':'existing','snmp_module':'if_mib'}}]
  a.atomic_json(a.DATA_DIR/'snmp.json',legacy)
  device=self.req('/api/devices','POST',PAYLOAD);identifier=device['id']
  for content in (device,self.req('/api/devices'),a.load_inventory()):self.assertNotIn('unit-test-secret',json.dumps(content))
  self.assertEqual(len(self.req('/api/monitors')),1)
  targets=json.loads((a.DATA_DIR/'snmp.json').read_text())
  self.assertIn(legacy[0],targets);self.assertEqual(len(targets),3)
  self.assertEqual(targets[2]['labels']['job'],'snmp_health')
  self.assertEqual(targets[1]['labels']['__scrape_interval__'],'60s')
  updated=self.req('/api/devices/'+identifier,'PUT',{'name':'Novo nome','credentials':{'community':''}})
  self.assertEqual(a.snmp_auths()[identifier]['community'],'unit-test-secret')
  p.INVENTORY=str(a.INVENTORY);metrics=p.render_metrics().decode()
  self.assertIn('dnk_snmp_contracted_download_bits',metrics);self.assertIn('300000000.0',metrics)
  self.req('/api/devices/'+identifier,'PUT',{'enabled':False})
  self.assertEqual(json.loads((a.DATA_DIR/'snmp.json').read_text()),legacy)
  self.req('/api/devices/'+identifier,'DELETE')
  self.assertEqual(self.req('/api/devices'),[]);self.assertEqual(a.snmp_auths(),{})
  self.assertEqual(len(self.req('/api/monitors')),1)
 def test_rejected_reload_rolls_back(self):
  before=a.INVENTORY.read_bytes()
  with patch.object(s,'reload_exporter',side_effect=ValueError('coletor indisponível')):
   with self.assertRaises(urllib.error.HTTPError):self.req('/api/devices','POST',PAYLOAD)
  self.assertEqual(a.INVENTORY.read_bytes(),before);self.assertEqual(a.snmp_auths(),{})
  self.assertEqual(yaml.safe_load((s.PRIVATE/'snmp-managed.yml').read_text())['auths'],{})
 def test_unsaved_test_cleanup_on_probe_failure(self):
  with patch.object(s,'discover',side_effect=ValueError('timeout')):
   with self.assertRaises(urllib.error.HTTPError):self.req('/api/devices/test','POST',PAYLOAD)
  self.assertEqual(a.snmp_auths(),{});self.assertEqual(a.load_inventory(),[])
  self.assertEqual(yaml.safe_load((s.PRIVATE/'snmp-managed.yml').read_text())['auths'],{})
 def test_validation_and_origin(self):
  for changes in ({'interval_seconds':30,'timeout_seconds':30},{'host':'x; touch bad'},{'cpu_oid':'anything'},{'interfaces':[{'ifIndex':float('nan')}]},{'version':'3','credentials':{'username':'snmp','password':'short','priv_password':'short'}}):
   with self.assertRaises(ValueError):s.normalize(dict(PAYLOAD,**changes))
  with self.assertRaises(urllib.error.HTTPError):self.req('/api/devices','POST',PAYLOAD,origin='https://other.example')
 def test_discovery_handles_missing_vendor_health(self):
  row,_=s.normalize(PAYLOAD)
  samples=s.parse_metrics('ifOperStatus{ifIndex="2",ifName="X1"} 1\nifHCInOctets{ifIndex="2",ifName="X1"} 200\n')
  with patch.object(s,'scrape',side_effect=[samples,ValueError('unsupported')]):
   result=s.discover(row)
  self.assertTrue(result['success']);self.assertEqual(result['interfaces'][0]['name'],'X1');self.assertEqual(result['health'],{});self.assertTrue(result['warning'])
 def test_v3_credential_rotation_preserves_other_secrets(self):
  payload=dict(PAYLOAD,version='3',credentials={'username':'monitor','password':'auth-test-only','priv_password':'priv-test-only','auth_protocol':'SHA256','priv_protocol':'AES'})
  row=self.req('/api/devices','POST',payload)
  self.assertNotIn('auth-test-only',json.dumps(row));self.assertNotIn('monitor',json.dumps(row.get('credentials',{})))
  self.req('/api/devices/'+row['id'],'PUT',{'credentials':{'priv_password':'changed-test-only'}})
  auth=a.snmp_auths()[row['id']]
  self.assertEqual(auth['password'],'auth-test-only');self.assertEqual(auth['priv_password'],'changed-test-only');self.assertEqual(auth['auth_protocol'],'SHA256')

class RealExporter(unittest.TestCase):
 def test_multiple_configs_and_native_reload(self):
  binary=os.environ.get('SNMP_EXPORTER_BIN')
  if not binary:self.skipTest('Defina SNMP_EXPORTER_BIN para validar o binário real')
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);base=root/'base.yml';managed=root/'managed.yml'
   base.write_text(json.dumps({'auths':{'legacy':{'version':2,'community':'test'}},'modules':{}}))
   old=s.MODULES;s.MODULES=ROOT/'config/integracoes/modules.json'
   row,auth=s.normalize(PAYLOAD)
   v3,auth3=s.normalize(dict(PAYLOAD,version='3',credentials={'username':'monitor','password':'auth-test-only','priv_password':'priv-test-only','auth_protocol':'SHA256','priv_protocol':'AES'}))
   custom,auth_custom=s.normalize(dict(PAYLOAD,vendor='generico',cpu_oid='1.3.6.1.4.1.8741.1.3.1.3.0',ram_oid='1.3.6.1.4.1.8741.1.3.1.4.0'))
   s.atomic_bytes(managed,(s.exporter_yaml(s.document([row,v3,custom],{row['id']:auth,v3['id']:auth3,custom['id']:auth_custom}))+'\n').encode());s.MODULES=old
   with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
   log=open(root/'exporter.log','w+')
   process=subprocess.Popen([binary,'--config.file='+str(base),'--config.file='+str(managed),f'--web.listen-address=127.0.0.1:{port}'],stdout=log,stderr=log)
   try:
    for _ in range(80):
     if process.poll() is not None:log.seek(0);self.fail(log.read())
     try:
      with urllib.request.urlopen(f'http://127.0.0.1:{port}/metrics',timeout=.2):break
     except Exception:time.sleep(.05)
    else:self.fail('exporter não iniciou')
    with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{port}/-/reload',data=b'',method='POST'),timeout=3) as r:self.assertEqual(r.status,200)
    agent=Agent();old_url=s.EXPORTER
    try:
     s.EXPORTER=f'http://127.0.0.1:{port}'
     row['instance']=f'127.0.0.1:{agent.port}'
     result=s.discover(row)
     self.assertTrue(result['success']);self.assertEqual(result['health'],{'cpu_percent':18,'ram_percent':42})
     self.assertEqual(result['interfaces'][0]['name'],'X1');self.assertTrue(result['interfaces'][0]['up'])
     custom['instance']=row['instance'];self.assertEqual(s.discover(custom)['health'],{'cpu_percent':18,'ram_percent':42})
     self.assertIsNone(agent.error)
    finally:s.EXPORTER=old_url;agent.close()
   finally:process.terminate();process.wait(timeout=5);log.close()

if __name__=='__main__':unittest.main()
