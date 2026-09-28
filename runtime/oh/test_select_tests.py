import importlib.util
import unittest
from .config import HOME

spec = importlib.util.spec_from_file_location('select_tests', HOME / 'integrations/select_tests.py')
selector = importlib.util.module_from_spec(spec);spec.loader.exec_module(selector)

SAMPLE = '''import sys
import unittest
LIMIT = 3
DERIVED = LIMIT * 2


def fixture():
    value = 1
    return value


def wrapper():
    return fixture()


class SampleTest(unittest.TestCase):
    limit = LIMIT

    def setUp(self):
        # prepare
        self.value = fixture()
        self.other = 2

    def helper(self):
        return 2

    def test_one(self):
        self.assertEqual(self.value, 1)

    def test_two(self):
        self.assertEqual(self.helper(), 2)

    def test_three(self):
        self.assertLess(wrapper(), DERIVED)

    @unittest.skipIf(sys.version_info < (3,), 'old Python')
    def test_four(self):
        self.assertTrue(self.other)
'''
# Another module reusing the sample's fixture and helpers, as OH's tests reuse test_workflow.
REUSER = '''import unittest
from . import test_sample as fixtures
from .test_sample import wrapper


class ReuserTest(unittest.TestCase):
    setUp = fixtures.SampleTest.setUp

    def test_fixture(self):
        self.assertEqual(self.value, 1)


class ImporterTest(unittest.TestCase):
    def test_wrapper(self):
        self.assertEqual(wrapper(), 1)

    def test_constant(self):
        self.assertEqual(fixtures.LIMIT, 3)
'''
SAMPLE_CLASS = {'test_one', 'test_two', 'test_three', 'test_four'}


def picked(old, new, reuser=REUSER):
    chosen = selector.pick({'test_sample': SAMPLE, 'test_reuser': REUSER}, {'test_sample': SAMPLE.replace(old, new, 1), 'test_reuser': reuser})
    return {t.rsplit('.', 1)[1] for t in chosen}


class SelectTestsTest(unittest.TestCase):
    def test_a_change_picks_the_tests_that_depend_on_it_in_any_module(self):
        self.assertEqual(picked('return 2', 'return 3'), {'test_two'})  # a helper method
        self.assertEqual(picked('self.other = 2', 'self.other = 3'), SAMPLE_CLASS | {'test_fixture'})  # setUp, and a class reusing it
        # A module helper: through setUp, a wrapper, and the module importing that wrapper.
        self.assertEqual(picked('value = 1', 'value = 2'), SAMPLE_CLASS | {'test_fixture', 'test_wrapper'})
        self.assertEqual(picked('DERIVED = LIMIT * 2', 'DERIVED = LIMIT * 3'), {'test_three'})
        self.assertEqual(picked('LIMIT = 3', 'LIMIT = 4'), SAMPLE_CLASS | {'test_constant'})  # a class attribute and a derived value use it
        self.assertEqual(picked('self.assertEqual(self.value, 1)', 'self.assertEqual(self.value, 2)'), {'test_one'})

    def test_a_line_commented_out_blanked_or_deleted_counts_wherever_it_sits(self):
        everywhere = SAMPLE_CLASS | {'test_fixture', 'test_wrapper'}
        self.assertEqual(picked('    return value\n', '    # return value\n'), everywhere)  # a helper's last line
        self.assertEqual(picked('    return value\n', '    pass\n'), everywhere)
        self.assertEqual(picked('    value = 1\n', ''), everywhere)
        self.assertEqual(picked("    @unittest.skipIf(sys.version_info < (3,), 'old Python')\n", ''), {'test_four'})
        self.assertEqual(picked("    @unittest.skipIf", "    # @unittest.skipIf"), {'test_four'})
        self.assertEqual(picked('class SampleTest(unittest.TestCase):', '@unittest.skip("later")\nclass SampleTest(unittest.TestCase):'), SAMPLE_CLASS)

    def test_blank_lines_and_comments_change_nothing(self):
        self.assertEqual(picked('\n\ndef wrapper', '\n\n\n# helpers\ndef wrapper'), set())
        self.assertEqual(picked('        # prepare\n', ''), set())
