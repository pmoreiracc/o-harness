"""Run unittest's full discovery through the existing module-parallel test runner."""
import argparse
import sys
import unittest

from select_tests import ROOT, cases, run


def discover(patterns=()):
    loader = unittest.TestLoader()
    loader.testNamePatterns = [p if '*' in p else f'*{p}*' for p in patterns] or None
    suite = loader.discover(str(ROOT / 'runtime'), 'test_*.py')
    if loader.errors:
        raise ValueError('Full test discovery failed:\n' + '\n'.join(loader.errors))
    return [case.id() for case in cases(suite)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, choices=(1, 4), default=4)
    parser.add_argument('-k', action='append', default=[], dest='patterns')
    args = parser.parse_args(argv)
    try:
        names = discover(args.patterns)
        if not names:raise ValueError('No test matches')
    except ValueError as exc:
        parser.error(str(exc))
    return 0 if run(names, workers=args.workers, report=True) else 1


if __name__ == '__main__':
    sys.exit(main())
