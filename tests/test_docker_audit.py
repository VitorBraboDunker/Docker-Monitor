import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('docker_audit',ROOT/'scripts/docker_audit.py');a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
class Audit(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'server';self.report=Path(self.tmp.name)/'report'
 def tearDown(self):self.tmp.cleanup()
 def data(self,working=None,override=None):
  return {'Name':'/grafana','Config':{'Image':'grafana/grafana:13.2.2','Env':['PASSWORD=must-never-appear'],'Labels':{'com.docker.compose.project':'dunker-actual-name','com.docker.compose.project.working_dir':working or str(self.root),'com.docker.compose.service':'grafana','com.docker.compose.project.config_files':override or str(self.root/'compose.separado.yaml'),'custom.secret':'must-never-appear'}},'State':{'Status':'running','Health':{'Status':'healthy'}},'Mounts':[{'Type':'volume','Source':'/var/lib/docker/volumes/real-volume/_data','Destination':'/var/lib/grafana','Name':'real-volume','RW':True}],'NetworkSettings':{'Ports':{'3000/tcp':[{'HostIp':'127.0.0.1','HostPort':'3000'}]}}}
 def mock(self,obj):return patch.object(a,'run',side_effect=['container-id',json.dumps([obj])])
 def test_reports_preserve_volume_identity_without_environment_or_secret_labels(self):
  with self.mock(self.data()):a.audit(self.root,self.report,'antes',True)
  raw=(self.report/'docker-antes.json').read_text();self.assertNotIn('must-never-appear',raw);self.assertIn('real-volume',raw);self.assertEqual((self.report/'compose-project-name.txt').read_text().strip(),'dunker-actual-name')
 def test_wrong_folder_stops_with_report_and_real_path(self):
  with self.mock(self.data('/actual/server')):
   with self.assertRaisesRegex(ValueError,'/actual/server'):a.audit(self.root,self.report,'antes',True)
  self.assertTrue((self.report/'docker-antes.json').is_file())
 def test_unmanaged_override_stops_before_apply(self):
  with self.mock(self.data(override='/actual/custom.yaml')):
   with self.assertRaisesRegex(ValueError,'custom.yaml'):a.audit(self.root,self.report,'antes',True)
