"""Docker command contracts; no daemon, registry, or application data is used."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ContainerScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.bin = self.root/'bin'; self.bin.mkdir()
        self.log = self.root/'commands.jsonl'
        for name in ['docker','python3','curl']:
            script = self.bin/name
            script.write_text('#!'+os.path.realpath(os.sys.executable)+'\nimport json,os,sys\nfrom pathlib import Path\nwith open(os.environ["COMMAND_LOG"],"a") as stream: stream.write(json.dumps([Path(sys.argv[0]).name,*sys.argv[1:]])+"\\n")\nraise SystemExit(1 if sys.argv[1:3]==["container","inspect"] else 0)\n')
            script.chmod(0o700)
        self.env = {k:v for k,v in os.environ.items() if not k.startswith(('DASHBOARD_','WIDGETDECK_'))}
        self.env.update(PATH=str(self.bin)+os.pathsep+self.env['PATH'],COMMAND_LOG=str(self.log),
                        DASHBOARD_DATA_DIR=str(self.root/'data'),DASHBOARD_SECRET_KEY='invented-fixture-secret')

    def run_script(self, script, **variables):
        result = subprocess.run(['bash',str(ROOT/'tools'/script)],cwd=self.root,env={**self.env,**variables},
                                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_push_defaults_use_widgetdeck_namespace(self):
        commands=self.run_script('push_zot.sh')
        self.assertEqual(commands,[['docker','build','--tag','widgetdeck:latest',str(ROOT)],
            ['docker','tag','widgetdeck:latest','192.168.0.245:8568/widgetdeck:latest'],
            ['docker','push','192.168.0.245:8568/widgetdeck:latest']])

    def test_legacy_image_and_registry_overrides_remain_supported(self):
        commands=self.run_script('push_zot.sh',DASHBOARD_IMAGE='legacy:reviewed',DASHBOARD_ZOT_IMAGE='registry.invalid/legacy:reviewed')
        self.assertEqual(commands[-1],['docker','push','registry.invalid/legacy:reviewed'])
        self.assertEqual(commands[0][3],'legacy:reviewed')

    def test_widgetdeck_overrides_take_precedence(self):
        commands=self.run_script('push_zot.sh',DASHBOARD_IMAGE='legacy:old',DASHBOARD_ZOT_IMAGE='registry.invalid/old:tag',
            WIDGETDECK_IMAGE='widgetdeck:reviewed',WIDGETDECK_ZOT_IMAGE='registry.invalid/widgetdeck:reviewed')
        self.assertEqual(commands[0][3],'widgetdeck:reviewed')
        self.assertEqual(commands[-1],['docker','push','registry.invalid/widgetdeck:reviewed'])

    def test_default_deploy_builds_this_checkout_without_private_autodiscovery(self):
        commands=self.run_script('redeploy_local.sh')
        self.assertFalse(any(c[0]=='python3' for c in commands))
        self.assertIn(['docker','build','-t','widgetdeck:local',str(ROOT)],commands)
        run=next(c for c in commands if c[:2]==['docker','run'])
        self.assertEqual(run[run.index('--name')+1],'widgetdeck-local')
        self.assertIn('type=bind,source='+str(self.root/'data')+',target=/app/instance',run)
        self.assertEqual(run[-1],'widgetdeck:local')

    def test_existing_deployment_names_and_storage_overrides_are_preserved(self):
        commands=self.run_script('redeploy_local.sh',DASHBOARD_IMAGE='legacy:local',DASHBOARD_CONTAINER='existing-install',DASHBOARD_PORT='18020')
        run=next(c for c in commands if c[:2]==['docker','run'])
        self.assertEqual(run[run.index('--name')+1],'existing-install')
        self.assertIn('127.0.0.1:18020:8000',run)
        self.assertEqual(run[-1],'legacy:local')

    def test_explicit_private_tool_is_supported_and_core_only_skips_it(self):
        tool=self.root/'manage.py';tool.write_text('')
        commands=self.run_script('redeploy_local.sh',DASHBOARD_PERSONAL_TOOL=str(tool))
        self.assertEqual(commands[0][:3],['python3',str(tool),'up'])
        self.assertIn('widgetdeck-local',commands[0])
        self.log.unlink()
        commands=self.run_script('redeploy_local.sh',DASHBOARD_PERSONAL_TOOL=str(tool),DASHBOARD_CORE_ONLY='1')
        self.assertFalse(any(c[0]=='python3' for c in commands))

if __name__=='__main__':unittest.main()
