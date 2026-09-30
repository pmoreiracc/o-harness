"""Pick the tests a pull request must pass on Windows: OH's platform layer, tests that exercise platform-specific
behavior, every test module the change edits, and every test module that imports an edited one (directly or
through another). The full suite runs on Windows nightly, on demand and before a release (.github/workflows/full.yml),
which covers changes to runtime code.

A module counts as edited when its code differs before and after the change, compared by syntax tree: blank lines
and comments change nothing. Edited modules run whole. Test ids come from unittest's own loader, so every id loads.

  python3 integrations/select_tests.py [base]   print the chosen test ids, one per line
  python3 integrations/select_tests.py --run-selected [1|4]   run names from stdin (four processes by default)

Windows PR tests run in four processes, keeping each module's selected tests together so class and module fixtures
still run once. Selection is unchanged. `OH_TEST_WORKERS=1 bash integrations/test.sh windows` runs them serially.

Locally (and as the check OH runs on this repository's deliveries, when its `checks` setting names
`integrations/test.sh affected {base}`), `--affected <base>` runs only the test modules a change needs,
learned from the pre-separation harness's verify-change.sh: each changed path maps to what it needs (OWNERS),
explanatory text needs nothing, a runtime module needs the test modules that import it (directly or through other
modules), and a path no rule names stops the run with its name, so its owner is added here rather than guessed.
Two test processes run at a time. The full suite still runs before every push and in CI.

  python3 integrations/select_tests.py --affected [base] [--list]   run (or list) the affected test modules
"""
import ast
import inspect
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / 'runtime/oh'
# Modules that test OH's OS layer: locks, process groups, launchers, host binaries, installation.
CORE = {'test_system', 'test_integration', 'test_installation', 'test_controls'}
# Test bodies that touch what differs on Windows: line endings, permissions, deletion, paths, processes.
PLATFORM = re.compile(r"os\.name|sys\.platform|[Ww]indows|\\r\\n|CRLF|newline=|chmod|st_mode|rmtree|symlink|os\.sep|\.cmd\b|\.exe\b|signal\.|kill\(")


def before(base):
    """Each test module's source at the merge base with `base` ('' for a module the change adds)."""
    git = lambda *a:subprocess.run(['git', '-C', str(ROOT), *a], capture_output=True, text=True)
    merge = git('merge-base', base, 'HEAD').stdout.strip()
    if not merge:sys.exit(f'select_tests: cannot find {base}; fetch it or pass another base')
    listed = git('ls-tree', '--name-only', merge, 'runtime/oh/').stdout.split()
    return {Path(p).stem: git('show', f'{merge}:{p}').stdout for p in listed if re.fullmatch(r'runtime/oh/test_\w+\.py', p)}


def code(source):
    return ast.dump(ast.parse(source)) if source else ''


def imports(source, known):
    """The test modules a module imports, anywhere in it: `from . import test_x`, `from .test_x import y`,
    `import oh.test_x`, `from oh import test_x`."""
    found = set()
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, ast.ImportFrom):
            found.add((n.module or '').split('.')[-1])
            found |= {a.name for a in n.names}
        elif isinstance(n, ast.Import):
            found |= {a.name.split('.')[-1] for a in n.names}
    return found & known


def edited(old, new):
    """Test modules whose code changed, and the modules importing them, until nothing more is added."""
    chosen = {m for m, source in new.items() if code(old.get(m, '')) != code(source)}
    users = {m: imports(source, new.keys()) for m, source in new.items()}
    while more := {m for m, used in users.items() if used & chosen} - chosen:
        chosen |= more
    return chosen


def cases(suite):
    for item in suite:
        yield from cases(item) if isinstance(item, unittest.TestSuite) else [item]


def select(base=None):
    new = {path.stem: path.read_text(encoding='utf-8') for path in sorted(TESTS.glob('test_*.py'))}
    whole = (CORE | (edited(before(base), new) if base else set())) & new.keys()
    sys.path.insert(0, str(ROOT / 'runtime'))
    chosen = [f'oh.{m}' for m in sorted(whole)]
    for case in cases(unittest.defaultTestLoader.discover(str(TESTS), 'test_*.py', str(ROOT / 'runtime'))):
        if isinstance(case, unittest.loader._FailedTest):  # a module that fails to import runs, so its error shows
            chosen.append(case._testMethodName);continue
        package, _, module = type(case).__module__.rpartition('.')
        if package != 'oh' or module in whole:continue
        try:source = inspect.getsource(getattr(type(case), case._testMethodName))
        except (OSError, TypeError):continue
        if PLATFORM.search(source):chosen.append(case.id())
    return chosen


# Each changed path's needs, first match wins: runtime modules (their importing tests run) or test modules.
OWNERS = [
    ('docs/*', ()), ('README.md', ()), ('CONTRIBUTING.md', ()), ('SECURITY.md', ()), ('LICENSE', ()), ('AGENTS.md', ()),
    ('CLAUDE.md', ()), ('.github/*', ()), ('.gitignore', ()), ('.claude/*', ()), ('.codex/*', ()), ('config/invariants.json', ()),
    ('.gitattributes', ('test_windows',)),
    ('integrations/select_tests.py', ('test_select_tests',)), ('integrations/test.sh', ('test_select_tests',)),
    ('integrations/windows-*.ps1', ('test_windows',)), ('integrations/*', ()),  # the rest run only in CI
    ('prompts/*', ('runner',)), ('workflows/*', ('installation', 'mcp_server')), ('config/*', ('config',)),
    ('plugins/*', ('installation', 'test_gates', 'test_plugin_transitions', 'test_windows')),
    ('dashboard/*', ('server', 'test_installation')), ('oh', ('installation', 'test_plugin_transitions', 'test_windows')),
]


def changed(base):
    """Paths that differ between `base` and the working tree, including new untracked files."""
    def git(*a):
        done = subprocess.run(['git', '-C', str(ROOT), *a], capture_output=True, text=True)
        if done.returncode:sys.exit(f'select_tests: git {a[0]} failed ({done.stderr.strip()}); fetch {base} or pass another base')
        return done.stdout.split('\n')
    return sorted({p for p in git('diff', '--name-only', '--no-renames', base) + git('ls-files', '--others', '--exclude-standard') if p})


def needs(path):
    """The modules a changed path needs; None when no rule names it."""
    import fnmatch
    if re.fullmatch(r'runtime/oh/\w+\.py', path):return {Path(path).stem}
    return next((set(modules) for pattern, modules in OWNERS if fnmatch.fnmatchcase(path, pattern)), None)


def affected(paths, sources):
    """The test modules that exercise these paths. A runtime module needs the test modules that use it directly (an
    import, or a patch of `oh.<module>`); one that no test uses needs the tests of the modules that import it. A
    needed test module brings the test modules built on it (a shared fixture). Following every import instead would
    select the whole suite: OH's modules import each other inside functions. `sources` maps each module under
    runtime/oh to its source."""
    unowned = [p for p in paths if needs(p) is None]
    if unowned:
        sys.exit('select_tests: no owner for ' + ', '.join(unowned) + '; add what it needs to OWNERS in integrations/select_tests.py')
    gone = [p for p in paths if re.fullmatch(r'runtime/oh/\w+\.py', p) and (Path(p).stem not in sources or Path(p).stem == '__init__')]
    if gone:  # a deleted or renamed module, or the package itself: whatever used it can break anywhere
        return sorted(m for m in sources if m.startswith('test_'))
    uses = {m: imports(source, sources.keys()) | ({n for n in sources if re.search(rf'\boh\.{n}\b', source)} if m.startswith('test_') else set())
            for m, source in sources.items()}
    tests, seen, todo = set(), set(), sorted(set().union(*[needs(p) for p in paths]) & sources.keys())
    while todo:
        module = todo.pop()
        if module in seen:continue
        seen.add(module)
        if module.startswith('test_'):tests.add(module);continue
        users = {m for m, used in uses.items() if module in used and m != module}
        direct = {m for m in users if m.startswith('test_')}
        tests |= direct
        if not direct:todo += sorted(users)
    while more := {m for m, used in uses.items() if m.startswith('test_') and used & tests} - tests:
        tests |= more
    return sorted(tests)


def run(names, workers=2, report=False):
    """Run the exact selected names, grouped by module, in separate processes; True when every group passed."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import os
    groups = {}
    for name in names:groups.setdefault('.'.join(name.split('.')[:2]), []).append(name)
    if not groups:raise ValueError('No selected tests')
    def one(names):
        command = [sys.executable, '-m', 'unittest', '--durations', '15', *names]
        try:
            return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                  env=os.environ | {'PYTHONPATH': str(ROOT / 'runtime'), 'PYTHONUTF8': '1'})
        except OSError as exc:
            return subprocess.CompletedProcess(command, 1, '', str(exc))
    if report:print(f'Running {sum(map(len, groups.values()))} selected names in {len(groups)} module groups with {workers} workers', flush=True)
    passed = True
    with ThreadPoolExecutor(workers) as pool:
        pending = {pool.submit(one, names): module for module, names in groups.items()}
        for future in as_completed(pending):
            module, result = pending[future], future.result()
            print(f"{'ok' if not result.returncode else 'FAILED'}  {module}", flush=True)
            if result.returncode:passed = False
            if report or result.returncode:print(result.stdout + result.stderr, flush=True)
    return passed


if __name__ == '__main__' and sys.argv[1:2] == ['--affected']:
    base = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != '--list' else 'origin/main'
    sources = {p.stem: p.read_text(encoding='utf-8') for p in sorted(TESTS.glob('*.py'))}
    modules = affected(changed(base), sources)
    if '--list' in sys.argv:print('\n'.join(modules));sys.exit()
    if not modules:print('No test module is affected by this change');sys.exit()
    print(f'Running {len(modules)} affected test modules: {" ".join(modules)}', flush=True)
    sys.exit(0 if run(['oh.' + module for module in modules]) else 1)
elif __name__ == '__main__' and sys.argv[1:2] == ['--run-selected']:
    import argparse
    parser = argparse.ArgumentParser(description='Run selected Windows PR tests without changing their selection')
    parser.add_argument('--run-selected', action='store_true')
    parser.add_argument('workers', type=int, choices=(1, 4), nargs='?', default=4)
    args = parser.parse_args()
    names = sys.stdin.read().splitlines()
    if not names:parser.error('No selected tests')
    sys.exit(0 if run(names, workers=args.workers, report=True) else 1)
elif __name__ == '__main__':
    # Bytes, so Windows never adds \r to the test names the shell passes on.
    sys.stdout.buffer.write(''.join(t + '\n' for t in select(sys.argv[1] if len(sys.argv) > 1 else None)).encode())
