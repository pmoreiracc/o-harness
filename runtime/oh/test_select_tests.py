import importlib.util
import unittest
from .config import HOME

spec = importlib.util.spec_from_file_location('select_tests', HOME / 'integrations/select_tests.py')
selector = importlib.util.module_from_spec(spec);spec.loader.exec_module(selector)

SOURCE = '''import unittest


def fixture():
    return 1


class SampleTest(unittest.TestCase):
    def setUp(self):
        # prepare
        self.value = fixture()

    def helper(self):
        return 2

    def test_one(self):
        self.assertEqual(self.value, 1)

    def test_two(self):
        self.assertEqual(self.helper(), 2)
'''


def picked(changed=(), anchors=()):
    return {t.rsplit('.', 1)[1] for t in selector.pick({'test_sample': SOURCE}, {'test_sample': set(changed)}, {'test_sample': set(anchors)})}


class SelectTestsTest(unittest.TestCase):
    def test_a_changed_helper_picks_the_tests_that_use_it_and_a_fixture_all_of_them(self):
        self.assertEqual(picked([14]), {'test_two'})  # helper
        self.assertEqual(picked([5]), {'test_one', 'test_two'})  # a module helper that setUp calls
        self.assertEqual(picked([11]), {'test_one', 'test_two'})  # setUp itself

    def test_blank_and_comment_lines_pick_nothing_but_a_deletion_always_counts(self):
        self.assertEqual(picked([10, 12]), set())  # the comment in setUp, the blank line after it
        self.assertEqual(picked(anchors=[10]), {'test_one', 'test_two'})  # a line deleted after that comment
