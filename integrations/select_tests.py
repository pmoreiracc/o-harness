"""Pick the tests a pull request must pass on Windows: OH's platform layer, tests that exercise platform-specific
behavior, every test module the change edits, and every test module that imports an edited one (directly or
through another). The full suite runs on Windows nightly, on demand and before a release (.github/workflows/full.yml),
which covers changes to runtime code.

A module counts as edited when its code differs before and after the change, compared by syntax tree: blank lines
and comments change nothing. Edited modules run whole. Test ids come from unittest's own loader, so every id loads.

  python3 integrations/select_tests.py [base]   print the chosen test ids, one per line
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


if __name__ == '__main__':
    # Bytes, so Windows never adds \r to the test names the shell passes on.
    sys.stdout.buffer.write(''.join(t + '\n' for t in select(sys.argv[1] if len(sys.argv) > 1 else None)).encode())
