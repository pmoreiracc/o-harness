from .registry import register
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

    def test_path_spoof_cannot_select_host_executable(self):
        from .hosts import executable,trust
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'OH_DATA_HOME':tmp,'PATH':tmp}):
            fake=Path(tmp)/'codex';fake.write_text('#!/bin/sh\necho codex-cli fake\n');fake.chmod(0o755)
            with self.assertRaises(Refused):executable('codex')
            with self.assertRaises(Refused):trust('codex',fake)

    @staticmethod
    def git(root,*args):return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.DEVNULL,text=True).strip()


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
            register(root,'Generic');(root/'product.txt').write_text('fixture')
            self.git(root,'add','.');self.git(root,'commit','-qm','initial')
            # Ordinary work does not install or call OH Git hooks.
            (root/'manual.txt').write_text('normal coding')
            self.git(root,'add','manual.txt')
            self.git(root,'commit','-qm','Release ordinary work')
            self.assertEqual(self.git(root,'log','-1','--format=%s'),'Release ordinary work')
            self.assertFalse((root/'.oh').exists())

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
            register(root,'Fixture');(root/'product.txt').write_text('fixture')
            self.git(root,'add','.');self.git(root,'commit','-qm','base')
            from .legacy import environment
            env=environment(root)
            start='source "$OH_HOME/core/review-workflow.sh"; review_series_ensure "$OH_PROJECT_ROOT" work 3 invariant-reviewer nd/fixture'
            series=subprocess.check_output(['/bin/bash','-c',start],env=env,text=True).strip()
            command='source "$OH_HOME/core/review-workflow.sh"; review_series_current "$OH_PROJECT_ROOT" work'
            result=subprocess.run(['/usr/bin/sandbox-exec','-p','(version 1)(allow default)(deny file-write*)(allow file-write* (literal "/dev/null"))','/bin/bash','-c',command],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),series)
