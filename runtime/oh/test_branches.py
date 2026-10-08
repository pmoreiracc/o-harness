import subprocess
import unittest
from . import test_workflow as fixtures
from .storage import Refused


class BranchIdentityTest(unittest.TestCase):
    setUp=fixtures.WorkflowTest.setUp
    git=fixtures.WorkflowTest.git
    def test_external_identity_survives_appends_and_rejects_recreation_with_identical_creation_record(self):
        from .branches import incarnation
        path=self.root/'.git/logs/refs/heads/work'
        first=path.read_text().splitlines()[0]
        original=incarnation(self.root,'work',create=True)
        self.assertEqual(path.read_text(),first+'\n')
        self.git('commit','--allow-empty','-qm','ordinary commit')
        self.assertEqual(incarnation(self.root,'work'),original)
        self.git('switch','main');self.git('branch','-D','work');self.git('switch','-c','work')
        # Force the exact timestamp/identity bytes that made the Linux failure possible.
        path.write_text(first+'\n')
        self.assertNotEqual(incarnation(self.root,'work',create=True),original)

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
