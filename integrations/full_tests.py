"""Split full unittest discovery by module across runners, then use the existing test executor."""
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


def shard(names, index, count):
    """Balance test counts while keeping each module and its fixtures on one runner."""
    groups = {}
    for name in names:groups.setdefault('.'.join(name.split('.')[:2]), []).append(name)
    assignments, sizes = {}, [0] * count
    for module in sorted(groups, key=lambda m: (-len(groups[m]), m)):
        target = min(range(count), key=lambda i: sizes[i])
        assignments[module] = target
        sizes[target] += len(groups[module])
    return [name for name in names if assignments['.'.join(name.split('.')[:2])] == index]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, choices=(1, 4), default=4)
    parser.add_argument('-k', action='append', default=[], dest='patterns')
    parser.add_argument('--shards', type=int, choices=(1, 4), default=1)
    parser.add_argument('--shard', type=int, default=0)
    args = parser.parse_args(argv)
    if not 0 <= args.shard < args.shards:parser.error('--shard must be between 0 and --shards minus one')
    try:
        names = discover(args.patterns)
        if not names:raise ValueError('No test matches')
    except ValueError as exc:
        parser.error(str(exc))
    names = shard(names, args.shard, args.shards)
    print(f'Full suite shard {args.shard + 1}/{args.shards}: {len(names)} tests', flush=True)
    if not names:return 0  # A name filter may match only tests assigned to another runner.
    return 0 if run(names, workers=args.workers, report=True) else 1


if __name__ == '__main__':
    sys.exit(main())
