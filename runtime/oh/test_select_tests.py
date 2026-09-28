import importlib.util
import unittest
from .config import HOME

spec = importlib.util.spec_from_file_location('select_tests', HOME / 'integrations/select_tests.py')
selector = importlib.util.module_from_spec(spec);spec.loader.exec_module(selector)

SAMPLE_CODE = '''import sys
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
SAMPLE = 'test_sample.SampleTest'


def picked(old, new, reuser=REUSER):
    """What the picker runs when one piece of the sample module changes, as ids without the `oh.` prefix."""
    chosen = selector.pick({'test_sample': SAMPLE_CODE, 'test_reuser': REUSER}, {'test_sample': SAMPLE_CODE.replace(old, new, 1), 'test_reuser': reuser})
    return {t.removeprefix('oh.') for t in chosen}


def change(before, after):
    """What the picker runs for whole modules before and after a change."""
    return {t.removeprefix('oh.') for t in selector.pick(before, after)}


def module(*classes, top=''):
    return 'import unittest\n' + top + ''.join(classes)


class SelectTestsTest(unittest.TestCase):
    def test_a_change_picks_the_tests_that_depend_on_it_in_any_module(self):
        self.assertEqual(picked('return 2', 'return 3'), {SAMPLE + '.test_two'})  # a helper method
        self.assertEqual(picked('self.other = 2', 'self.other = 3'), {SAMPLE, 'test_reuser.ReuserTest'})  # setUp, and a class reusing it
        # A module helper: through setUp, a wrapper, and the module importing that wrapper.
        self.assertEqual(picked('value = 1', 'value = 2'), {SAMPLE, 'test_reuser.ReuserTest', 'test_reuser.ImporterTest.test_wrapper'})
        self.assertEqual(picked('DERIVED = LIMIT * 2', 'DERIVED = LIMIT * 3'), {SAMPLE + '.test_three'})
        self.assertEqual(picked('LIMIT = 3', 'LIMIT = 4'), {SAMPLE, 'test_reuser.ImporterTest.test_constant'})  # a class attribute and a derived value use it
        self.assertEqual(picked('self.assertEqual(self.value, 1)', 'self.assertEqual(self.value, 2)'), {SAMPLE + '.test_one'})

    def test_a_line_commented_out_blanked_or_deleted_counts_wherever_it_sits(self):
        everywhere = {SAMPLE, 'test_reuser.ReuserTest', 'test_reuser.ImporterTest.test_wrapper'}
        self.assertEqual(picked('    return value\n', '    # return value\n'), everywhere)  # a helper's last line
        self.assertEqual(picked('    return value\n', '    pass\n'), everywhere)
        self.assertEqual(picked('    value = 1\n', ''), everywhere)
        self.assertEqual(picked("    @unittest.skipIf(sys.version_info < (3,), 'old Python')\n", ''), {SAMPLE + '.test_four'})
        self.assertEqual(picked("    @unittest.skipIf", "    # @unittest.skipIf"), {SAMPLE + '.test_four'})
        self.assertEqual(picked('class SampleTest(unittest.TestCase):', '@unittest.skip("later")\nclass SampleTest(unittest.TestCase):'), {SAMPLE})

    def test_blank_lines_and_comments_change_nothing(self):
        self.assertEqual(picked('\n\ndef wrapper', '\n\n\n# helpers\ndef wrapper'), set())
        self.assertEqual(picked('        # prepare\n', ''), set())

    def test_every_way_of_sharing_test_code_is_followed(self):
        test = '    def test_a(self):\n        pass\n'
        # A constant in a class decorator, and a mixin's setUp, run the whole class.
        guarded = lambda flag:module('@unittest.skipIf(SKIP, "x")\nclass T(unittest.TestCase):\n' + test, top=f'SKIP = {flag}\n')
        self.assertEqual(change({'test_m': guarded(False)}, {'test_m': guarded(True)}), {'test_m.T'})
        mixed = lambda v:module(f'class Mixin:\n    def setUp(self):\n        self.v = {v}\n\n', 'class T(Mixin, unittest.TestCase):\n' + test)
        self.assertEqual(change({'test_m': mixed(1)}, {'test_m': mixed(2)}), {'test_m.T'})
        # A fixture borrowed by naming its class, from another module or the same one.
        owner = lambda v:module(f'class W(unittest.TestCase):\n    def setUp(self):\n        self.v = {v}\n\n' + test)
        borrower = 'import unittest\nfrom .test_w import W\n\n\nclass R(unittest.TestCase):\n    setUp = W.setUp\n\n' + test
        self.assertEqual(change({'test_w': owner(1), 'test_r': borrower}, {'test_w': owner(2), 'test_r': borrower}), {'test_w.W', 'test_r.R'})
        both = lambda v:owner(v) + '\n\nclass R(unittest.TestCase):\n    setUp = W.setUp\n\n' + test
        self.assertEqual(change({'test_m': both(1)}, {'test_m': both(2)}), {'test_m.W', 'test_m.R'})
        # A module hook, a run() override and a helper defined under `if`.
        hooked = lambda v:module('class T(unittest.TestCase):\n' + test, top=f'def setUpModule():\n    return {v}\n\n')
        self.assertEqual(change({'test_m': hooked(1)}, {'test_m': hooked(2)}), {'test_m'})
        plain = module('class T(unittest.TestCase):\n' + test)
        self.assertEqual(change({'test_m': plain}, {'test_m': plain.replace('    def test_a', '    def run(self, result=None):\n        return None\n\n    def test_a')}), {'test_m.T'})
        guarded_helper = lambda v:module('class W(unittest.TestCase):\n' + test, top=f'if True:\n    def helper():\n        return {v}\n')
        user = 'import unittest\nfrom .test_w import helper\n\n\nclass R(unittest.TestCase):\n    def test_r(self):\n        helper()\n'
        self.assertEqual(change({'test_w': guarded_helper(1), 'test_r': user}, {'test_w': guarded_helper(2), 'test_r': user}), {'test_r.R.test_r'})
        # A subclass inherits a changed test: it runs whole, with the tests it inherits.
        family = lambda body:module('class T(unittest.TestCase):\n    def test_a(self):\n        ' + body + '\n\n\nclass U(T):\n    pass\n')
        self.assertEqual(change({'test_m': family('pass')}, {'test_m': family('return')}), {'test_m.T.test_a', 'test_m.U'})
