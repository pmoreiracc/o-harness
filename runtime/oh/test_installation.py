import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from .installation import build, verify_package
from .storage import Refused


class InstallationTest(unittest.TestCase):
    def test_both_hosts_share_one_core_and_setup_is_explicit_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);consumer=base/'product';consumer.mkdir()
            (consumer/'manual.txt').write_text('unchanged')
            first=base/'codex/o-harness';second=base/'claude/o-harness'
            a=build(first,'codex');b=build(second,'claude')
            self.assertEqual(a['revision'],b['revision'])
            self.assertNotIn('disable-model-invocation: true',(first/'skills/oh-deliver/SKILL.md').read_text())
            self.assertIn('allow_implicit_invocation: false',(first/'skills/oh-deliver/agents/openai.yaml').read_text())
            self.assertIn('disable-model-invocation: true',(second/'skills/oh-deliver/SKILL.md').read_text())
            env=os.environ|{'OH_DATA_HOME':str(base/'state')}
            entry=first/'core/oh'
            for _ in range(2):
                result=subprocess.run([str(entry),'setup','--development'],cwd=consumer,env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
            launcher=base/'state/bin/oh'
            status=subprocess.run([str(launcher),'resource','workflows/deliver/SKILL.md'],cwd=consumer,env=env,capture_output=True,text=True)
            self.assertEqual(status.returncode,0,status.stderr)
            self.assertTrue((first/'core/dashboard/app.js').is_file())
            self.assertEqual([p.name for p in consumer.iterdir()],['manual.txt'])
            self.assertEqual((consumer/'manual.txt').read_text(),'unchanged')
            self.assertEqual(len(list((base/'state/versions').iterdir())),1)
            self.assertEqual(verify_package(first/'core'),a['revision'])
            (first/'core/runtime/oh/cli.py').write_text('changed')
            with self.assertRaises(Refused):verify_package(first/'core')

    def test_plugin_update_activates_its_new_core_once(self):
        from .installation import inventory
        from .storage import atomic_json,read_json
        def package(path,revision):
            build(path,'codex');core=path/'core'
            atomic_json(core/'revision.json',{'revision':revision})
            atomic_json(core/'package.json',{'schema_version':1,'revision':revision,'files':inventory(core)})
            return path/'scripts/oh'
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);env=os.environ|{'OH_DATA_HOME':str(base/'state')}
            old=package(base/'v1/o-harness','1'*40);new=package(base/'v2/o-harness','2'*40)
            def use(launcher):
                result=subprocess.run([str(launcher),'--root',tmp,'resource','workflows/oh/SKILL.md'],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                return read_json(base/'state/runtime/active.json')['revision']
            self.assertEqual(use(old),'1'*40)
            self.assertEqual(use(new),'2'*40)
            # An older plugin still installed in another host does not switch back.
            self.assertEqual(use(old),'2'*40)

    def test_ordinary_prompt_hook_has_no_setup_or_project_side_effects(self):
        from .config import HOME
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            result=subprocess.run(['python3',str(HOME/'plugins/o-harness/scripts/human-event.py'),'codex'],
                input=json.dumps({'prompt':'Fix the button styling','cwd':tmp}),cwd=root,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'')
            self.assertEqual(list(root.iterdir()),[])
