import subprocess
import unittest
from . import test_workflow as fixtures
from .storage import Refused


class BranchIdentityTest(unittest.TestCase):
    setUp=fixtures.WorkflowTest.setUp
    git=fixtures.WorkflowTest.git
    def test_external_identity_survives_appends_and_rejects_recreation_with_identical_creation_record(self):
        from .initial import incarnation
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
