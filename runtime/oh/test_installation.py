import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from .installation import build, verify_package
from .storage import Refused
# POSIX users run OH's scripts directly, so tests do too; Windows needs the interpreter.
RUN=[sys.executable,'-I'] if os.name=='nt' else []


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
                result=subprocess.run([*RUN,str(entry),'setup','--development'],cwd=consumer,env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
            launcher=base/'state/bin/oh'
            status=subprocess.run([*RUN,str(launcher),'resource','workflows/deliver/SKILL.md'],cwd=consumer,env=env,capture_output=True,text=True)
            self.assertEqual(status.returncode,0,status.stderr)
            self.assertTrue((first/'core/dashboard/app.js').is_file())
            self.assertEqual([p.name for p in consumer.iterdir()],['manual.txt'])
            self.assertEqual((consumer/'manual.txt').read_text(),'unchanged')
            self.assertEqual(len(list((base/'state/versions').iterdir())),1)
            self.assertEqual(verify_package(first/'core'),a['revision'])
            (first/'core/runtime/oh/cli.py').write_text('changed')
            with self.assertRaises(Refused):verify_package(first/'core')

    @staticmethod
    def package(path,revision,version):
        from .installation import inventory
        from .storage import atomic_json
        build(path,'codex');core=path/'core'
        atomic_json(core/'revision.json',{'revision':revision,'version':version})
        atomic_json(core/'package.json',{'schema_version':1,'revision':revision,'files':inventory(core)})
        return path/'scripts'

    def test_plugin_update_activates_only_a_newer_core(self):
        from .storage import read_json
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);env=os.environ|{'OH_DATA_HOME':str(base/'state')}
            plugins={n:self.package(base/f'v{n}/o-harness',str(n)*40,f'0.{n}.0') for n in (1,2,3)}
            def use(n):
                result=subprocess.run([*RUN,str(plugins[n]/'oh'),'--root',tmp,'resource','workflows/oh/SKILL.md'],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                return read_json(base/'state/runtime/active.json')['revision'][0]
            self.assertEqual(use(1),'1')
            self.assertEqual(use(3),'3')
            # An older plugin still installed in another host never downgrades the shared core.
            self.assertEqual(use(2),'3')
            self.assertEqual(use(1),'3')
            # The same rule holds under the install lock, for hosts racing the launcher's check.
            older=subprocess.run([*RUN,str(plugins[2].parent/'core/oh'),'setup','--if-newer'],env=env,capture_output=True,text=True)
            self.assertEqual(older.returncode,0,older.stderr)
            self.assertEqual(read_json(base/'state/runtime/active.json')['revision'][0],'3')

    def test_bare_choices_never_install_the_bundled_core(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);env=os.environ|{'OH_DATA_HOME':str(base/'state')}
            scripts=self.package(base/'v1/o-harness','1'*40,'0.1.0')
            def send(prompt):
                return subprocess.run([sys.executable,str(scripts/'human-event.py'),'claude'],input=json.dumps({'prompt':prompt,'cwd':tmp}),
                    env=env,capture_output=True,text=True,check=True).stdout
            self.assertEqual(send('continue'),'')
            self.assertFalse((base/'state').exists())
            self.assertIn('not registered',send('/oh-propose a plan'))
            self.assertTrue((base/'state/runtime/active.json').is_file())

    def test_ordinary_prompt_hook_has_no_setup_or_project_side_effects(self):
        from .config import HOME
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            result=subprocess.run([sys.executable,str(HOME/'plugins/o-harness/scripts/human-event.py'),'codex'],
                input=json.dumps({'prompt':'Fix the button styling','cwd':tmp}),cwd=root,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'')
            self.assertEqual(list(root.iterdir()),[])

    def test_a_plain_message_reaches_oh_only_while_oh_waits_for_it(self):
        import io,runpy
        from unittest.mock import patch
        from .config import HOME
        with tempfile.TemporaryDirectory() as tmp:
            def launched(session,prompt='Search my notes',recognized=False):
                stdin=io.TextIOWrapper(io.BytesIO(json.dumps({'prompt':prompt,'cwd':tmp,'session_id':session}).encode()))
                with patch.dict(os.environ,{'OH_DATA_HOME':tmp}),patch('sys.stdin',stdin),patch('sys.argv',['hook','claude']),\
                        patch('subprocess.run') as run:
                    run.return_value.returncode,run.return_value.stdout=0,''
                    with self.assertRaises(SystemExit) if not recognized and not (Path(tmp)/'waiting'/(session+'.json')).exists() else contextlib.nullcontext():
                        runpy.run_path(str(HOME/'plugins/o-harness/scripts/human-event.py'),run_name='__main__')
                    return run.called
            (Path(tmp)/'waiting').mkdir();(Path(tmp)/'waiting/s.json').write_text('{}')
            self.assertTrue(launched('s'))
            self.assertFalse(launched('other'))
            from .entry import CHOICES
            for choice in CHOICES:self.assertTrue(launched('other',choice,recognized=True),choice)
            for removed in ('fix scope','fix findings'):self.assertFalse(launched('other',removed),removed)
