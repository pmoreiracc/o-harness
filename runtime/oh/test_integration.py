import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from .config import HOME
from .storage import atomic_json,identifier,Refused
from .integration import generate

class IntegrationTest(unittest.TestCase):
    def test_isolated_pinned_launcher_rejects_dirty_pin_and_shadow_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'consumer';harness=Path(tmp)/'installed'
            for p in [root,harness]:
                p.mkdir();self.git(p,'init','-qb','main');self.git(p,'config','user.name','Fixture');self.git(p,'config','user.email','fixture@example.invalid')
            (harness/'oh').write_text('print("PINNED_RUNTIME")\n');self.git(harness,'add','.');self.git(harness,'commit','-qm','fixture')
            revision=self.git(harness,'rev-parse','HEAD')
            atomic_json(root/'.oh/harness.lock.json',{'revision':revision,'repository':'https://github.com/example/harness.git'})
            shutil.copy2(HOME/'integrations/project/oh',root/'.oh/oh')
            (root/'.oh/json.py').write_text('raise RuntimeError("SHADOW IMPORT EXECUTED")')
            self.git(root,'add','.');self.git(root,'commit','-qm','pin')
            env=os.environ|{'OH_HOME':str(harness),'PYTHONPATH':str(root/'.oh')}
            first=subprocess.run([str(root/'.oh/oh'),'status'],cwd=root,env=env,capture_output=True,text=True)
            self.assertEqual(first.returncode,0,first.stderr);self.assertIn('PINNED_RUNTIME',first.stdout)
            (root/'.oh/harness.lock.json').write_text('{}')
            second=subprocess.run([str(root/'.oh/oh'),'status'],cwd=root,env=env,capture_output=True,text=True)
            self.assertNotEqual(second.returncode,0);self.assertIn('uncommitted',second.stderr)
    def test_generated_discovery_delegates_to_one_neutral_entrypoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);atomic_json(root/'.oh/project.json',{'id':identifier(),'kind':'product','name':'Fixture'})
            generate(root)
            for file,host in [('.codex/hooks.json','codex'),('.claude/settings.json','claude')]:
                hooks=json.loads((root/file).read_text())['hooks']
                self.assertTrue(all('.oh/oh' in h['command'] and '--host '+host in h['command'] for groups in hooks.values() for g in groups for h in g['hooks']))
            self.assertTrue((root/'.agents/skills/oh/SKILL.md').is_file())
    def test_existing_discovery_conflict_refuses_without_partial_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);atomic_json(root/'.oh/project.json',{'id':identifier(),'kind':'product','name':'Fixture'})
            atomic_json(root/'.claude/settings.json',{'permissions':{'deny':['Bash(rm:*)']}})
            original=(root/'.claude/settings.json').read_bytes()
            with self.assertRaises(Refused):generate(root)
            self.assertEqual((root/'.claude/settings.json').read_bytes(),original)
            self.assertFalse((root/'.codex/config.toml').exists())
            (root/'.claude/settings.json').unlink();generate(root);generate(root)
            (root/'.codex/config.toml').write_text('model = "custom"')
            with self.assertRaises(Refused):generate(root)
            self.assertEqual((root/'.codex/config.toml').read_text(),'model = "custom"')

    def test_path_spoof_cannot_select_host_executable(self):
        from .hosts import executable,trust
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'OH_DATA_HOME':tmp,'PATH':tmp}):
            fake=Path(tmp)/'codex';fake.write_text('#!/bin/sh\necho codex-cli fake\n');fake.chmod(0o755)
            with self.assertRaises(Refused):executable('codex')
            with self.assertRaises(Refused):trust('codex',fake)

    @staticmethod
    def git(root,*args):return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.DEVNULL,text=True).strip()

    def test_discovery_rejects_parent_symlinks_and_retires_only_unchanged_owned_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'consumer';external=Path(tmp)/'external';external.mkdir()
            atomic_json(root/'.oh/project.json',{'id':identifier(),'kind':'product','name':'Fixture'})
            (root/'.codex').symlink_to(external,target_is_directory=True)
            with self.assertRaises(Refused):generate(root)
            self.assertEqual(list(external.iterdir()),[]);self.assertFalse((root/'.claude').exists())
            (root/'.codex').unlink();generate(root)
            self.assertFalse((root/'.agents/skills/design').exists())
            from .storage import read_json
            identity=read_json(root/'.oh/project.json');identity['design_profile']='consumer-v1';atomic_json(root/'.oh/project.json',identity)
            for name in ('design','propose','deliver'):atomic_json(root/'.oh/policy'/f'{name}.md',{'policy':'fixture'})
            generate(root);retired=root/'.agents/skills/design/SKILL.md';original=retired.read_text();retired.write_text('my edit')
            del identity['design_profile'];atomic_json(root/'.oh/project.json',identity)
            with self.assertRaises(Refused):generate(root)
            self.assertEqual(retired.read_text(),'my edit')
            retired.write_text(original);generate(root);self.assertFalse(retired.exists())

    def test_first_pin_and_pin_upgrade_commit_use_installed_hook_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'consumer';installed=Path(tmp)/'installed'
            for p in (root,installed):
                p.mkdir();self.git(p,'init','-qb','main');self.git(p,'config','user.name','Fixture');self.git(p,'config','user.email','fixture@example.invalid')
            (installed/'oh').write_text('import sys\nassert "git-hook" in sys.argv\nprint("REVIEWED_HOOK")\n')
            self.git(installed,'add','.');self.git(installed,'commit','-qm','runtime');old=self.git(installed,'rev-parse','HEAD')
            atomic_json(root/'.oh/harness.lock.json',{'revision':old,'repository':'https://github.com/example/harness.git'})
            shutil.copy2(HOME/'integrations/project/oh',root/'.oh/oh')
            hooks=root/'.oh/git-hooks';hooks.mkdir()
            for name in ('commit-msg','prepare-commit-msg'):
                file=hooks/name;file.write_text('#!/bin/sh\nexec "$(git rev-parse --show-toplevel)/.oh/oh" git-hook '+name+' "$@"\n');file.chmod(0o755)
            self.git(root,'config','core.hooksPath','.oh/git-hooks')
            self.git(root,'add','.')
            env=os.environ|{'OH_HOME':str(installed)}
            def commit():
                result=subprocess.run(['git','-C',str(root),'commit','-qm','pin'],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
            commit()
            atomic_json(root/'.oh/harness.lock.json',{'revision':'a'*40,'repository':'https://github.com/example/harness.git'})
            refused=subprocess.run([str(root/'.oh/oh'),'status'],env=env,capture_output=True,text=True);self.assertNotEqual(refused.returncode,0)
            self.git(root,'add','.');commit() # old committed runtime enforces the pin-update commit

    def test_enabling_worktree_hooks_preserves_sibling_hook_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'main';other=Path(tmp)/'other';root.mkdir()
            self.git(root,'init','-qb','main');self.git(root,'config','user.name','Fixture');self.git(root,'config','user.email','fixture@example.invalid')
            self.git(root,'commit','--allow-empty','-qm','base');self.git(root,'config','core.hooksPath','.old-hooks');self.git(root,'worktree','add','-qb','other',str(other))
            (other/'.oh/git-hooks').mkdir(parents=True)
            result=subprocess.run(['/bin/bash',str(HOME/'core/hooks/enable-githooks.sh')],env=os.environ|{'CLAUDE_PROJECT_DIR':str(other),'OH_HOME':str(HOME)},capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(self.git(root,'config','--get','core.hooksPath'),'.old-hooks');self.assertEqual(self.git(other,'config','--get','core.hooksPath'),'.oh/git-hooks')

    def test_generic_deliver_branch_does_not_require_numbered_product_design(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'OH_DATA_HOME':tmp+'/state'}):
            root=Path(tmp)/'consumer';root.mkdir();self.git(root,'init','-qb','deliver/release');self.git(root,'config','user.name','Fixture');self.git(root,'config','user.email','fixture@example.invalid')
            atomic_json(root/'.oh/project.json',{'id':identifier(),'name':'Generic','kind':'product'})
            self.git(root,'add','.');self.git(root,'commit','-qm','initial')
            message=Path(tmp)/'message';message.write_text('Release ordinary work\n')
            from .legacy import environment
            result=subprocess.run(['/bin/bash',str(HOME/'integrations/git/commit-msg'),str(message)],cwd=root,env=environment(root),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_setup_refuses_existing_corrupt_install_with_recovery(self):
        import runpy
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'consumer';home=Path(tmp)/'home';root.mkdir();self.git(root,'init','-qb','main');self.git(root,'config','user.name','Fixture');self.git(root,'config','user.email','fixture@example.invalid')
            revision='a'*40;atomic_json(root/'.oh/harness.lock.json',{'revision':revision,'repository':'https://github.com/example/harness.git'})
            shutil.copy2(HOME/'integrations/project/setup.py',root/'.oh/setup.py')
            self.git(root,'add','.');self.git(root,'commit','-qm','pin')
            broken=home/'.local/share/o-harness/versions'/revision;broken.mkdir(parents=True);(broken/'valuable.txt').write_text('preserve')
            with patch('pathlib.Path.home',return_value=home):
                with self.assertRaises(SystemExit) as failure:runpy.run_path(str(root/'.oh/setup.py'))
            self.assertIn('Preserve it',str(failure.exception));self.assertEqual((broken/'valuable.txt').read_text(),'preserve')

            shutil.rmtree(broken);broken.symlink_to(home/'missing-install',target_is_directory=True)
            with patch('pathlib.Path.home',return_value=home):
                with self.assertRaises(SystemExit) as failure:runpy.run_path(str(root/'.oh/setup.py'))
            self.assertIn('Preserve it',str(failure.exception));self.assertTrue(broken.is_symlink())

    @unittest.skipUnless(os.uname().sysname=='Darwin','macOS read-only sandbox regression')
    def test_legacy_series_lookup_does_not_write_heredoc_scratch_files(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'OH_DATA_HOME':tmp+'/state'}):
            root=Path(tmp)/'consumer';root.mkdir();self.git(root,'init','-qb','work');self.git(root,'config','user.name','Fixture');self.git(root,'config','user.email','fixture@example.invalid')
            atomic_json(root/'.oh/project.json',{'id':identifier(),'name':'Fixture','kind':'product'})
            self.git(root,'add','.');self.git(root,'commit','-qm','base')
            from .legacy import environment
            env=environment(root)
            start='source "$OH_HOME/core/review-workflow.sh"; review_series_ensure "$OH_PROJECT_ROOT" work 3 invariant-reviewer nd/fixture'
            series=subprocess.check_output(['/bin/bash','-c',start],env=env,text=True).strip()
            command='source "$OH_HOME/core/review-workflow.sh"; review_series_current "$OH_PROJECT_ROOT" work'
            result=subprocess.run(['/usr/bin/sandbox-exec','-p','(version 1)(allow default)(deny file-write*)(allow file-write* (literal "/dev/null"))','/bin/bash','-c',command],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),series)
