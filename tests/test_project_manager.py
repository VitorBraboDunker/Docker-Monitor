"""Update safety against an old base, existing extensions and partial failures."""
import importlib.util,json,os,shutil,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('project_manager',ROOT/'scripts/project_manager.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
yaml=m.yaml

class ProjectManager(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'server';self.root.mkdir();self.umask=os.umask(0o022)
 def tearDown(self):os.umask(self.umask);self.tmp.cleanup()
 def put(self,name,body):
  p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body if isinstance(body,bytes) else body.encode());return p
 def old(self):
  c=m.read_yaml(ROOT/'compose.separado.yaml');c['name']='keep-my-data'
  for name in ['sharepoint','sharepoint-prometheus','admin']:c['services'].pop(name)
  c['services']['snmp']['command']=['--config.file=/etc/dunker/snmp.yml']
  c['volumes'].pop('sharepoint_prometheus_data')
  c['services']['grafana']['ports']=['127.0.0.1:3333:3000'];c['services']['grafana']['volumes']=['./config:/etc/dunker:ro','my-existing-grafana:/var/lib/grafana']
  c['volumes']['my-existing-grafana']={'external':True,'name':'real-old-grafana-volume'}
  c['services']['ping']['volumes']=['./config:/etc/dunker:ro','./runtime/ping_exporter.py:/opt/dunker/ping_exporter.py:ro']
  self.put('compose.separado.yaml',m.dump(c))
  self.put('.env','MONITOR_HOST=other-server\nACCESS_PORT=7443\n');self.put('config/secrets/grafana_secret_key','old-key\n');self.put('config/secrets/grafana_admin_password','old-password\n')
  self.put('config/caddy/Caddyfile',(ROOT/'config/caddy/Caddyfile.example').read_text().replace('{$INGEST_HASH}','$2a$EXISTING-HASH'))
  self.put('config/targets/inventory.json',json.dumps([{'tipo':'icmp','name':'Client existing','instance':'192.0.2.1'}]));self.put('config/targets/snmp.json','[{"targets":["192.0.2.2"],"labels":{"snmp_auth":"old-auth"}}]\n')
  self.put('config/snmp.yml','auths:\n  old-auth:\n    community: old-private\nmodules: {}\n')
  self.put('config/integracoes/private/snmp-managed.yml','auths: {}\nmodules: {}\n')
  self.put('config/sharepoint/private/sharepoint.sqlite3',b'existing-private-db')
  self.put('config/access/private/policy.json','{"existing":"untouched"}')
  self.put('config/alertmanager.yml','route: {receiver: my-channel}\nreceivers: [{name: my-channel}]\n')
  self.put('config/grafana/provisioning/datasources/datasources.yml','apiVersion: 1\ndatasources: [{name: Existing, uid: dnk-prometheus}]\n')
  self.put('config/prometheus/rules.yml','groups:\n- name: customer-custom\n  rules: [{record: customer:metric, expr: up}]\n')
  prom=m.read_yaml(ROOT/'config/prometheus/separado.yml');prom['scrape_configs'].append({'job_name':'customer-job','static_configs':[{'targets':['example:9090']}]});self.put('config/prometheus/separado.yml',m.dump(prom))
 def test_old_base_missing_extensions_is_completed_without_losing_data(self):
  self.old();protected=['.env','config/secrets/grafana_secret_key','config/secrets/grafana_admin_password','config/targets/inventory.json','config/targets/snmp.json','config/snmp.yml','config/integracoes/private/snmp-managed.yml','config/sharepoint/private/sharepoint.sqlite3','config/access/private/policy.json','config/caddy/Caddyfile','config/alertmanager.yml','config/grafana/provisioning/datasources/datasources.yml'];before={f:(self.root/f).read_bytes() for f in protected}
  m.apply(self.root,ROOT,compose_name='actual-docker-project')
  for f in protected:self.assertEqual(before[f],(self.root/f).read_bytes(),f)
  c=m.read_yaml(self.root/'compose.separado.yaml');self.assertEqual(c['name'],'actual-docker-project');self.assertEqual(len(c['services']),12)
  self.assertEqual(c['services']['grafana']['ports'],['127.0.0.1:3333:3000']);self.assertIn('my-existing-grafana:/var/lib/grafana',c['services']['grafana']['volumes']);self.assertEqual(c['volumes']['my-existing-grafana']['name'],'real-old-grafana-volume')
  self.assertEqual([v for v in c['services']['ping']['volumes'] if '/opt/dunker' in v],['./runtime:/opt/dunker:ro'])
  self.assertTrue((self.root/'config/sharepoint/private/gateway_token').is_file());self.assertTrue((self.root/'config/grafana/plugins/dunker-integracoes-app/module.js').is_file())
  self.assertIn('customer-custom',[g['name'] for g in m.read_yaml(self.root/'config/prometheus/rules.yml')['groups']]);self.assertIn('customer-job',[g['job_name'] for g in m.read_yaml(self.root/'config/prometheus/separado.yml')['scrape_configs']])
  m.inspect(self.root,ROOT,self.root/'diagnostico','depois');report=(self.root/'diagnostico/arquivos-depois.json').read_text();self.assertNotIn('old-private',report);self.assertNotIn('old-password',report);self.assertNotIn('192.0.2.1',report)
 def test_new_setup_permissions_and_repeat_do_not_rotate_secrets_or_duplicate_rules(self):
  m.apply(self.root,ROOT,new=True)
  secret=(self.root/'config/secrets/grafana_secret_key').read_bytes();token=(self.root/'config/sharepoint/private/gateway_token').read_bytes()
  self.assertEqual((self.root/'config/secrets/grafana_admin_password').stat().st_mode&0o777,0o444)
  self.assertEqual((self.root/'config/grafana/dashboards/dnk-sharepoint-geral.json').stat().st_mode&0o777,0o644)
  self.assertEqual((self.root/'config/sharepoint/private').stat().st_mode&0o777,0o700)
  self.assertEqual((self.root/'config/access/private').stat().st_mode&0o777,0o700)
  m.apply(self.root,ROOT)
  compose=m.read_yaml(self.root/'compose.separado.yaml')
  self.assertIn('./runtime/sharepoint_collector.py:/opt/dunker/sharepoint_collector.py:ro',compose['services']['sharepoint']['volumes'])
  self.assertEqual(secret,(self.root/'config/secrets/grafana_secret_key').read_bytes());self.assertEqual(token,(self.root/'config/sharepoint/private/gateway_token').read_bytes())
  rules=m.read_yaml(self.root/'config/prometheus/rules.yml')['groups'];self.assertEqual(len(rules),len({g['name'] for g in rules}));records=[r['record'] for g in rules for r in g['rules'] if 'record' in r];self.assertEqual(len(records),len(set(records)))
 def test_existing_extension_and_previous_custom_unsigned_plugin_are_folded(self):
  self.old();self.put('compose.integracoes.yaml','services:\n  admin:\n    ports: ["0.0.0.0:8080:8080"]\n    image: vitorbrabodunker/dunker-monitor-separado:1.2.0\n  grafana:\n    environment:\n      GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS: custom-app\n');self.put('compose.sharepoint.yaml','services:\n  sharepoint:\n    environment: {CUSTOM_SETTING: preserved}\n')
  m.apply(self.root,ROOT);c=m.read_yaml(self.root/'compose.separado.yaml');self.assertEqual(c['services']['sharepoint']['environment']['CUSTOM_SETTING'],'preserved');self.assertNotIn('ports',c['services']['admin']);self.assertIn('./config/access/private:/etc/dunker/access/private:rw',c['services']['admin']['volumes']);self.assertIn('custom-app',c['services']['grafana']['environment']['GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS']);self.assertIn('dunker-integracoes-app',c['services']['grafana']['environment']['GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS'])
 def test_invalid_existing_caddy_stops_before_mutation(self):
  self.old();self.put('config/caddy/Caddyfile','unrecognized custom config\n');before=(self.root/'compose.separado.yaml').read_bytes()
  with self.assertRaises(m.Problem):m.apply(self.root,ROOT)
  self.assertEqual(before,(self.root/'compose.separado.yaml').read_bytes());self.assertFalse((self.root/'runtime/admin_monitor.py').exists());self.assertFalse((self.root/'config/sharepoint/private/gateway_token').exists())
 def test_rollback_restores_files_and_keeps_existing_private_data(self):
  self.old();before=(self.root/'compose.separado.yaml').read_bytes();m.apply(self.root,ROOT);m.rollback(self.root)
  self.assertEqual(before,(self.root/'compose.separado.yaml').read_bytes());self.assertEqual((self.root/'config/sharepoint/private/sharepoint.sqlite3').read_bytes(),b'existing-private-db');self.assertFalse((self.root/'config/grafana/plugins/dunker-integracoes-app/module.js').exists());self.assertIn('config/sharepoint/private/',(self.root/'.gitignore').read_text())
 def test_existing_install_and_missing_install_are_not_confused(self):
  with self.assertRaises(m.Problem):m.apply(self.root,ROOT)
  self.old()
  with self.assertRaises(m.Problem):m.apply(self.root,ROOT,new=True)
 def test_payload_integrity_failure_does_not_change_existing_project(self):
  self.old();package=Path(self.tmp.name)/'changed-package';shutil.copytree(ROOT,package,ignore=shutil.ignore_patterns('__pycache__'));(package/'runtime/admin_monitor.py').write_text('modified')
  before=(self.root/'compose.separado.yaml').read_bytes()
  with self.assertRaises(m.Problem):m.apply(self.root,package)
  self.assertEqual(before,(self.root/'compose.separado.yaml').read_bytes())

 def test_legacy_inventory_seeds_missing_file_and_missing_active_inventory_is_protected(self):
  self.old();(self.root/'config/targets/inventory.json').unlink()
  self.put('config/inventory.json','[{"tipo":"icmp","instance":"192.0.2.9","Cliente":"Old","Unidade":"HQ","Provedor":"ISP"}]\n')
  m.apply(self.root,ROOT)
  self.assertEqual((self.root/'config/targets/inventory.json').read_bytes(),(self.root/'config/inventory.json').read_bytes())
  (self.root/'config/targets/inventory.json').unlink();(self.root/'config/inventory.json').unlink();self.put('config/targets/http.json','[{"targets":["https://example.com"],"labels":{}}]')
  before=(self.root/'compose.separado.yaml').read_bytes()
  with self.assertRaises(m.Problem):m.apply(self.root,ROOT)
  self.assertEqual(before,(self.root/'compose.separado.yaml').read_bytes())
