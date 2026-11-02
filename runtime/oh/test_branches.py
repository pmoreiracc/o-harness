import subprocess
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from . import test_workflow as fixtures
from .storage import Refused


class BranchIdentityTest(unittest.TestCase):
    setUp=fixtures.WorkflowTest.setUp
    git=fixtures.WorkflowTest.git

    def origin(self):
        origin=Path(self.temp.name)/'origin.git'
        self.git('clone','--bare',str(self.root),str(origin))
        self.git('remote','add','origin',str(origin))
        self.git('fetch','origin','main')
        return origin

    def test_entry_fetches_stale_base_without_changing_local_work_on_both_interfaces(self):
        from .cli import main
        from .mcp_server import command
        self.origin();old=self.git('rev-parse','HEAD')
        (self.root/'product.txt').write_text('merged decisions and progress',newline='\n')
        self.git('commit','-qam','remote progress');new=self.git('rev-parse','HEAD')
        self.git('push','origin','HEAD:main');self.git('reset','--hard',old)
        self.git('update-ref','refs/remotes/origin/main',old)
        (self.root/'product.txt').write_text('valuable local edit',newline='\n')
        (self.root/'notes.txt').write_text('untracked work',newline='\n')
        nested=self.root/'.claude/worktrees/held'
        self.git('worktree','add','-qb','held',str(nested))
        before=self.git('status','--porcelain');branch=self.git('branch','--show-current')
        for arguments in (['entry'],command('entry',{},self.root)):
            with patch('sys.stdout',new=io.StringIO()) as output:main(['--root',str(self.root),*arguments])
            facts=json.loads(output.getvalue())
            self.assertEqual(facts['base']['freshness'],'fetched')
            self.assertEqual(facts['base']['commit'],new)
            self.assertEqual(facts['checkout']['head'],old)
            self.assertEqual(facts['checkout']['behind'],1)
            self.assertEqual(set(facts['checkout']['paths']),{'product.txt','notes.txt'})
            self.assertEqual(facts['checkout']['nested_worktrees'],['.claude/worktrees/held'])
            self.assertEqual(facts['saved_work'],[])
        self.assertEqual(self.git('status','--porcelain'),before)
        self.assertEqual(self.git('branch','--show-current'),branch)
        self.assertEqual((self.root/'product.txt').read_text(),'valuable local edit')
        self.assertEqual((self.root/'notes.txt').read_text(),'untracked work')
        self.assertTrue((nested/'product.txt').is_file())

    def test_failed_fetch_exposes_cached_base_without_claiming_freshness(self):
        from .branches import run_git,fetched
        from .entry import inspect
        self.origin();old=self.git('rev-parse','HEAD')
        def offline(root,*args,**kwargs):
            return subprocess.CompletedProcess(args,1,'','offline fixture') if args[0]=='fetch' else run_git(root,*args,**kwargs)
        with patch('oh.branches.run_git',side_effect=offline):
            facts=inspect(self.root)
            self.assertEqual(facts['base']['freshness'],'unavailable')
            self.assertEqual(facts['base']['commit'],old)
            self.assertIn('offline fixture',facts['base']['reason'])
            with self.assertRaisesRegex(Refused,'Could not refresh.*offline fixture'):fetched(self.root,'main')
        self.assertEqual(self.git('rev-parse','HEAD'),old)

    def test_entry_keeps_large_observations_external_and_local_only_is_explicit(self):
        from .entry import inspect
        from .storage import read_json,digest,encode
        fixtures.configure(self.root,context={'result_chars':1000})
        for number in range(40):(self.root/(str(number)+'x'*90)).write_text('local',newline='\n')
        facts=inspect(self.root)
        self.assertLessEqual(len(encode(facts)),1000)
        reference=facts['observation'];full=read_json(reference['path'])
        self.assertEqual(digest(full),reference['hash'])
        self.assertEqual(full['checkout']['path_count'],40)
        self.assertEqual(full['base']['freshness'],'local_only')
        self.assertFalse(Path(reference['path']).is_relative_to(self.root))

    def test_base_branch_precedence_remote_only_checkout_and_checks(self):
        # docs/usage.md: detect origin/HEAD, allow project/global overrides, and explain the source.
        from .branches import base_branch,from_main,main_ref,trunk
        from .checks import selected
        from .config import change,describe
        self.assertEqual(base_branch(self.root),{'name':'main','ref':'main','source':'fallback'})
        for name in ('main','master','team/develop'):
            self.git('update-ref','refs/remotes/origin/'+name,'HEAD')
        self.git('symbolic-ref','refs/remotes/origin/HEAD','refs/remotes/origin/master')
        self.assertEqual(base_branch(self.root),{'name':'master','ref':'origin/master','source':'origin/HEAD'})
        self.assertEqual(describe(self.root)['base_branch']['source'],'origin/HEAD')
        change(self.root,'base_branch','main',scope='global')
        self.assertEqual(describe(self.root)['base_branch']['source'],'global')
        change(self.root,'base_branch','team/develop')
        self.assertEqual(describe(self.root)['base_branch'],{'name':'team/develop','ref':'origin/team/develop','source':'project'})
        fixtures.configure(self.root,base_branch='team/develop',checks=[{'name':'base','command':['git','diff','{base}']}])
        self.assertEqual(selected(self.root)[0]['command'],['git','diff','origin/team/develop'])
        self.assertEqual(selected(self.root,'main')[0]['command'],['git','diff','main'])
        from_main(self.root)
        self.assertEqual(self.git('branch','--show-current'),'team/develop')
        self.assertEqual(self.git('rev-parse','HEAD'),self.git('rev-parse','origin/team/develop'))
        for invalid in ('-bad','refs/heads/main','a..b','@{-1}','origin/HEAD:bad'):
            with self.subTest(invalid),self.assertRaises(Refused):change(self.root,'base_branch',invalid)
        change(self.root,'base_branch','missing')
        with self.assertRaisesRegex(Refused,'fetch origin missing'):trunk(self.root)
        change(self.root,'base_branch',None)
        self.assertEqual(trunk(self.root),'main')  # unsetting inherits the global override
        change(self.root,'base_branch',None,scope='global')
        self.assertEqual(trunk(self.root),'master')
        self.git('symbolic-ref','refs/remotes/origin/HEAD','refs/remotes/origin/missing')
        self.assertEqual(main_ref(self.root),'origin/main')
        self.git('update-ref','-d','refs/remotes/origin/main');self.git('branch','-D','main')
        self.assertEqual(main_ref(self.root),'origin/master')
