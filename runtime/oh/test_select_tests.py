import importlib.util
import unittest
from .config import HOME

spec = importlib.util.spec_from_file_location('select_tests', HOME / 'integrations/select_tests.py')
selector = importlib.util.module_from_spec(spec);spec.loader.exec_module(selector)

# Line numbers below refer to this sample module.
SOURCE = '''import sys
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
OTHER = '''import unittest


class OtherTest(unittest.TestCase):
    def test_reuses(self):
        from .test_sample import wrapper
        self.assertEqual(wrapper(), 1)
'''
CLASS = {'test_one', 'test_two', 'test_three', 'test_four'}


def picked(changed=(), deleted=(), source=SOURCE):
    chosen = selector.pick({'test_sample': source, 'test_other': OTHER}, {'test_sample': set(changed)}, {'test_sample': set(deleted)})
    return {t.rsplit('.', 1)[1] for t in chosen}


def line(number, text, source=SOURCE):
    rows = source.split('\n');rows[number - 1] = text
    return '\n'.join(rows)


class SelectTestsTest(unittest.TestCase):
    def test_a_change_picks_the_tests_that_depend_on_it(self):
        self.assertEqual(picked([25]), {'test_two'})  # a helper method
        self.assertEqual(picked([22]), CLASS)  # setUp
        self.assertEqual(picked([8]), CLASS | {'test_reuses'})  # a module helper: setUp, a wrapper, a module importing it
        self.assertEqual(picked([4]), {'test_three'})  # a module constant
        self.assertEqual(picked([3]), CLASS)  # a constant a class attribute and a derived constant use

    def test_a_line_commented_out_blanked_or_deleted_still_counts(self):
        everywhere = CLASS | {'test_reuses'}
        self.assertEqual(picked([8], source=line(8, '    # value = 1')), everywhere)
        self.assertEqual(picked([8], source=line(8, '')), everywhere)
        self.assertEqual(picked(deleted=[8]), everywhere)  # a line deleted inside the helper
        self.assertEqual(picked(deleted=[20]), CLASS)  # a line deleted after setUp's comment
        # A skip decorator commented out, or deleted, un-skips that test.
        self.assertEqual(picked([36], source=line(36, "    # @unittest.skipIf(sys.version_info < (3,), 'old Python')")), {'test_four'})
        self.assertEqual(picked(deleted=[35], source=SOURCE.replace("    @unittest.skipIf(sys.version_info < (3,), 'old Python')\n", '')), {'test_four'})

    def test_spacing_between_statements_and_deleted_statements_change_nothing(self):
        self.assertEqual(picked([5, 6, 10, 11, 14, 15, 18, 23, 26]), set())  # blank lines between definitions
        self.assertEqual(picked(deleted=[1]), set())  # an import deleted between two others
