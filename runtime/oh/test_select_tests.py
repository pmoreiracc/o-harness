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

    def test_parallel_execution_preserves_selection_and_reports_worker_failures(self):
        # integrations/select_tests.py: keep each module's fixture together and retain every selected name.
        import contextlib, io, subprocess, threading
        from unittest.mock import patch
        names = ['oh.test_a.C.test_one', 'oh.test_b', 'oh.test_c.C.test_one', 'oh.test_a.C.test_two', 'oh.test_d']
        expected = [['oh.test_a.C.test_one', 'oh.test_a.C.test_two'], ['oh.test_b'], ['oh.test_c.C.test_one'], ['oh.test_d']]
        for workers in (1, 4):
            for failure in (None, 1, -9, 'launch'):
                with self.subTest(workers=workers, failure=failure):
                    together = threading.Barrier(workers, timeout=5)
                    def child(command, **kwargs):
                        together.wait()  # four workers must actually execute concurrently
                        self.assertEqual(command[:5], [selector.sys.executable, '-m', 'unittest', '--durations', '15'])
                        self.assertEqual(kwargs['cwd'], selector.ROOT)
                        self.assertEqual(kwargs['env']['PYTHONPATH'], str(selector.ROOT / 'runtime'))
                        if command[-1] == 'oh.test_d' and failure == 'launch':raise OSError('launch failed')
                        code = failure if command[-1] == 'oh.test_d' and isinstance(failure, int) else 0
                        return subprocess.CompletedProcess(command, code, 'worker output\n', 'Ran tests; skipped=1; Slowest test durations\n')
                    output = io.StringIO()
                    with patch.object(selector.subprocess, 'run', side_effect=child) as invoke, contextlib.redirect_stdout(output):
                        self.assertEqual(selector.run(names, workers=workers, report=True), failure is None)
                    self.assertCountEqual([call.args[0][5:] for call in invoke.call_args_list], expected)
                    self.assertIn('worker output', output.getvalue())
                    self.assertIn('skipped=1; Slowest test durations', output.getvalue())
                    if failure is not None:self.assertIn('FAILED  oh.test_d', output.getvalue())
                    if failure == 'launch':self.assertIn('launch failed', output.getvalue())
        with self.assertRaisesRegex(ValueError, 'No selected tests'):selector.run([], workers=4)

    def test_full_parallel_discovery_keeps_every_test_and_fails_closed(self):
        import contextlib, io, sys
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('full_tests', HOME / 'integrations/full_tests.py')
        full = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, select_tests=selector):spec.loader.exec_module(full)
        loader = unittest.TestLoader()
        expected = [case.id() for case in selector.cases(loader.discover(str(HOME / 'runtime'), 'test_*.py'))]
        self.assertFalse(loader.errors)
        self.assertEqual(full.discover(), expected)  # same discovery as the native full suite, including duplicates
        patterns = ['*SelectTestsTest.test_full*', 'test_a_renamed_module']
        from fnmatch import fnmatchcase
        matching = [name for name in expected if fnmatchcase(name, patterns[0]) or patterns[1] in name]
        self.assertEqual(full.discover(patterns), matching)
        for passed in (True, False):
            with patch.object(full, 'run', return_value=passed) as run:
                self.assertEqual(full.main(['--workers', '4']), 0 if passed else 1)
                run.assert_called_once_with(expected, workers=4, report=True)
        with patch.object(full, 'run') as run, contextlib.redirect_stderr(io.StringIO()) as errors:
            with self.assertRaises(SystemExit) as empty:full.main(['-k', 'no_test_has_this_name'])
            self.assertEqual(empty.exception.code, 2)
            self.assertIn('No test matches', errors.getvalue())
            def broken(loader_self, *args):
                loader_self.errors.append('test module import failed')
                return unittest.TestSuite()
            with patch.object(full.unittest.TestLoader, 'discover', broken):
                with self.assertRaises(SystemExit) as failed:full.main([])
            self.assertEqual(failed.exception.code, 2)
            self.assertIn('test module import failed', errors.getvalue())
            run.assert_not_called()
