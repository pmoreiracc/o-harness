import importlib.util
import unittest
from .config import HOME

spec = importlib.util.spec_from_file_location('select_tests', HOME / 'integrations/select_tests.py')
selector = importlib.util.module_from_spec(spec);spec.loader.exec_module(selector)

SOURCE = '''import unittest
LIMIT = 3


def fixture():
    return 1


def wrapper():
    return fixture()


class SampleTest(unittest.TestCase):
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
        self.assertLess(wrapper(), LIMIT)
'''
OTHER = '''import unittest


class OtherTest(unittest.TestCase):
    def test_reuses(self):
        from .test_sample import wrapper
        self.assertEqual(wrapper(), 1)
'''


def picked(changed=(), anchors=(), source=SOURCE):
    chosen = selector.pick({'test_sample': source, 'test_other': OTHER}, {'test_sample': set(changed)}, {'test_sample': set(anchors)})
    return {t.rsplit('.', 1)[1] for t in chosen}


class SelectTestsTest(unittest.TestCase):
    everything = {'test_one', 'test_two', 'test_three', 'test_reuses'}

    def test_a_changed_helper_picks_the_tests_that_use_it_and_a_fixture_all_of_them(self):
        self.assertEqual(picked([20]), {'test_two'})  # a helper method
        self.assertEqual(picked([16]), {'test_one', 'test_two', 'test_three'})  # setUp itself
        # A module helper, through the helper that calls it, in this module and in one that imports it; setUp calls it too.
        self.assertEqual(picked([6]), self.everything)
        self.assertEqual(picked([2]), {'test_three'})  # a module constant

    def test_an_edited_line_counts_even_as_a_comment_but_spacing_between_definitions_never_does(self):
        commented = SOURCE.replace('        self.value = fixture()', '        # self.value = fixture()')
        self.assertEqual(picked([16], source=commented), {'test_one', 'test_two', 'test_three'})
        self.assertEqual(picked([12, 18, 21]), set())  # blank lines between definitions
        self.assertEqual(picked(anchors=[15]), {'test_one', 'test_two', 'test_three'})  # a line deleted after setUp's comment
