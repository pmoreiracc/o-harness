import importlib.util
import unittest
from .config import HOME

spec = importlib.util.spec_from_file_location('select_tests', HOME / 'integrations/select_tests.py')
selector = importlib.util.module_from_spec(spec);spec.loader.exec_module(selector)


class SelectTestsTest(unittest.TestCase):
    def test_an_edited_module_runs_with_its_importers_and_every_id_loads(self):
        old = {'test_base': 'def fixture():\n    return 1\n', 'test_user': 'from . import test_base as fixtures\n',
               'test_far': 'from .test_user import x\n', 'test_other': 'import os\n'}
        new = dict(old, test_base='def fixture():\n    return 2\n')
        self.assertEqual(selector.edited(old, new), {'test_base', 'test_user', 'test_far'})
        commented = dict(old, test_base='# fixtures\ndef fixture():\n\n    return 1  # one\n')
        self.assertEqual(selector.edited(old, commented), set())
        chosen = selector.select()
        self.assertTrue(set(selector.CORE) <= {t.removeprefix('oh.') for t in chosen})
        loader = unittest.TestLoader();loader.loadTestsFromNames(chosen)
        self.assertEqual(loader.errors, [])

    def test_local_runs_only_the_tests_a_change_affects(self):
        sources = {'gates': '', 'issues': '', 'workflow': 'from . import gates\ndef f():\n    from .issues import route\n',
                   'test_gates': 'from .gates import x\n', 'test_workflow': 'from .workflow import y\n',
                   'test_propose': 'from . import test_workflow\n', 'test_other': 'import os\n'}
        self.assertEqual(selector.affected(['docs/usage.md', 'README.md'], sources), [])  # explanatory text needs nothing
        self.assertEqual(selector.affected(['runtime/oh/gates.py'], sources), ['test_gates'])
        # A module no test uses needs its users' tests, and a fixture's users come along.
        self.assertEqual(selector.affected(['runtime/oh/issues.py'], sources), ['test_propose', 'test_workflow'])
        with self.assertRaisesRegex(SystemExit, 'no owner for notes/todo.txt'):selector.affected(['notes/todo.txt'], sources)
        # A deleted or renamed module can break any test: all of them run.
        everything = ['test_gates', 'test_other', 'test_propose', 'test_workflow']
        self.assertEqual(selector.affected(['runtime/oh/old_name.py'], sources), everything)
        self.assertEqual(selector.affected(['runtime/oh/__init__.py'], sources), everything)

    def test_a_renamed_module_counts_as_its_old_path_gone(self):
        import subprocess, tempfile
        from pathlib import Path
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as name:
            git = lambda *a:subprocess.run(['git', '-C', name, *a], check=True, capture_output=True)
            git('init', '-q');git('config', 'user.email', 't@example.invalid');git('config', 'user.name', 't')
            (Path(name) / 'runtime/oh').mkdir(parents=True);(Path(name) / 'runtime/oh/foo.py').write_bytes(b'x = 1\n')
            git('add', '.');git('commit', '-qm', 'base');git('mv', 'runtime/oh/foo.py', 'runtime/oh/bar.py')
            with patch.object(selector, 'ROOT', Path(name)):
                self.assertIn('runtime/oh/foo.py', selector.changed('HEAD'))
