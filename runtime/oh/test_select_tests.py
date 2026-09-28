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
        unittest.defaultTestLoader.loadTestsFromNames(chosen)  # an id unittest cannot load raises here
