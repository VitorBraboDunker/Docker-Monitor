"""Migration against a real previous release, private SQLite and rollback."""
import json,os,shutil,sqlite3,sys,tempfile,unittest,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import project_manager as m
class Migration(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'server';self.root.mkdir();self.umask=os.umask(0o022)
 def tearDown(self):os.umask(self.umask);self.tmp.cleanup()
 def put(self,name,value):
  p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value);return p
 def existing(self):
  self.put('compose.separado.yaml',(ROOT/'compose.separado.yaml').read_text().replace('name: dunker-separado','name: preserve-volumes'))
  self.put('.env','MONITOR_HOST=172.16.27.51\nACCESS_PORT=7443\n')
  self.put('config/secrets/grafana_admin_password','old-password\n');self.put('config/secrets/grafana_secret_key','old-key\n')
  self.put('config/caddy/Caddyfile',(ROOT/'config/caddy/Caddyfile.example').read_text())
  self.put('config/targets/inventory.json',json.dumps([{'tipo':'icmp','name':'Old link','Cliente':'Customer','Unidade':'HQ','Provedor':'ISP','instance':'192.0.2.1'}]))
  self.put('config/integracoes/private/credentials.json','{"old-id":{"community":"old-snmp-secret","version":2}}')
  self.put('config/sharepoint/private/gateway_token','old-gateway-token')
  dbpath=self.root/'config/sharepoint/private/sharepoint.sqlite3'
  with sqlite3.connect(dbpath) as db:
   db.execute('CREATE TABLE tenants(id TEXT PRIMARY KEY, config TEXT, secret TEXT, revision TEXT)')
   db.execute('INSERT INTO tenants VALUES(?,?,?,?)',('sp-id','{}','old-microsoft-secret','old-revision'))
  self.put('config/grafana/dashboards/dnk-geral.json','{"uid":"dnk-geral"}')
  self.put('config/prometheus/rules.yml','groups: [{name: customer-rules, rules: [{record: customer:metric, expr: up}]}]\n')
 def test_migration_centralizes_without_rotating_and_cleans_legacy(self):
  self.existing();m.apply(self.root,ROOT)
  cfg=json.loads((self.root/'config/global/credentials.json').read_text())
  self.assertEqual(cfg['system']['grafana_admin_password'],'old-password');self.assertEqual(cfg['system']['grafana_secret_key'],'old-key')
  self.assertEqual(cfg['snmp']['old-id']['community'],'old-snmp-secret');self.assertEqual(cfg['sharepoint']['sp-id'],'old-microsoft-secret')
  self.assertFalse((self.root/'config/secrets/grafana_admin_password').exists());self.assertFalse((self.root/'config/integracoes/private/credentials.json').exists())
  self.assertFalse((self.root/'config/grafana/dashboards/dnk-geral.json').exists())
  inventory=json.loads((self.root/'config/targets/inventory.json').read_text());self.assertEqual(inventory[0]['CLIENTE'],'Customer');self.assertTrue(inventory[0]['id']);self.assertNotIn('Cliente',inventory[0])
  c=m.read_yaml(self.root/'compose.separado.yaml');self.assertEqual(c['name'],'preserve-volumes');self.assertNotIn('sharepoint-prometheus',c['services']);self.assertIn('sharepoint_prometheus_data',c['volumes'])
  self.assertIn('customer-rules',[g['name'] for g in m.read_yaml(self.root/'config/prometheus/rules.yml')['groups']])
  m.inspect(self.root,ROOT,self.root/'diagnostico')
  report=(self.root/'diagnostico/arquivos-antes.json').read_text();self.assertNotIn('old-password',report);self.assertNotIn('old-snmp-secret',report)
  m.rollback(self.root);self.assertEqual((self.root/'config/secrets/grafana_admin_password').read_text(),'old-password\n');self.assertTrue((self.root/'config/grafana/dashboards/dnk-geral.json').exists())
 def test_new_install_repeat_preserves_secrets_and_ids(self):
  m.apply(self.root,ROOT,new=True);before=(self.root/'config/global/credentials.json').read_bytes();inventory=(self.root/'config/targets/inventory.json').read_bytes()
  self.assertEqual((self.root/'config/global/credentials.json').stat().st_mode&0o777,0o600)
  self.assertEqual((self.root/'config/generated/grafana_admin_password').stat().st_mode&0o777,0o444)
  m.apply(self.root,ROOT);self.assertEqual(before,(self.root/'config/global/credentials.json').read_bytes());self.assertEqual(inventory,(self.root/'config/targets/inventory.json').read_bytes())
 def test_bad_identification_fails_before_changing_services(self):
  self.existing();self.put('config/targets/inventory.json','[{"tipo":"icmp","instance":"192.0.2.1"}]')
  before=(self.root/'compose.separado.yaml').read_bytes()
  with self.assertRaises(ValueError):m.apply(self.root,ROOT)
  self.assertEqual(before,(self.root/'compose.separado.yaml').read_bytes());self.assertFalse((self.root/'runtime/admin_monitor.py').exists())
 def test_tampered_package_rejected(self):
  self.existing();package=Path(self.tmp.name)/'altered';shutil.copytree(ROOT,package,ignore=shutil.ignore_patterns('__pycache__'));(package/'runtime/status_engine.py').write_text('altered')
  with self.assertRaises(m.Problem):m.apply(self.root,package)
  self.assertFalse((self.root/'runtime/admin_monitor.py').exists())
 def test_new_and_existing_not_confused(self):
  with self.assertRaises(m.Problem):m.apply(self.root,ROOT)
  self.existing()
  with self.assertRaises(m.Problem):m.apply(self.root,ROOT,new=True)
