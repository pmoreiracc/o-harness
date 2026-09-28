"""Pick the tests a pull request must pass on Windows: OH's platform layer, tests that exercise
platform-specific behavior, and every test the change adds or edits. The full suite runs on Windows
nightly, on demand and before a release (.github/workflows/full.yml).

  python3 integrations/select_tests.py [base]   print the chosen test ids, one per line
"""
import ast
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / 'runtime/oh'
# Modules that test OH's OS layer: locks, process groups, launchers, host binaries, installation.
CORE = {'test_system', 'test_integration', 'test_installation', 'test_controls'}
# Test bodies that touch what differs on Windows: line endings, permissions, deletion, paths, processes.
PLATFORM = re.compile(r"os\.name|sys\.platform|[Ww]indows|\\r\\n|CRLF|newline=|chmod|st_mode|rmtree|symlink|os\.sep|\.cmd\b|\.exe\b|signal\.|kill\(")


def changed_lines(base):
    """Line numbers each test file changed at since `base`, as a set per module name."""
    merge = subprocess.run(['git', '-C', str(ROOT), 'merge-base', base, 'HEAD'], capture_output=True, text=True).stdout.strip()
    if not merge:return {}
    diff = subprocess.run(['git', '-C', str(ROOT), 'diff', '-U0', merge, '--', 'runtime/oh/test_*.py'],
                          capture_output=True, text=True, check=True).stdout
    lines, name = {}, None
    for row in diff.splitlines():
        if row.startswith('+++ '):
            name = Path(row[6:]).stem if row != '+++ /dev/null' else None
        elif row.startswith('@@') and name:
            start, _, count = re.search(r'\+(\d+)(,(\d+))?', row).groups()
            start, count = int(start), int(count if count is not None else 1)
            lines.setdefault(name, set()).update(range(start, start + max(count, 1)))
    return lines


def names(node):
    """What a function uses: `self.x`/`cls.x` members and bare names."""
    return ({n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in ('self', 'cls')}
            | {n.id for n in ast.walk(node) if isinstance(n, ast.Name)})


def spans(node, edits):
    return bool(edits & set(range(node.lineno, node.end_lineno + 1)))


FIXTURES = {'setUp', 'setUpClass', 'tearDown', 'tearDownClass'}


def select(base=None):
    changed = changed_lines(base) if base else {}
    trees = {path.stem: (path.read_text(encoding='utf-8'), ast.parse(path.read_text(encoding='utf-8'))) for path in sorted(TESTS.glob('test_*.py'))}
    # Changed module-level helpers, by name: any test that uses one, in any module, is affected.
    shared = {n.name for module, (_, tree) in trees.items() for n in tree.body
              if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and not n.name.endswith('Test') and spans(n, changed.get(module, set()))}
    chosen = []
    for module, (source, tree) in trees.items():
        rows = source.splitlines()
        # Blank and comment-only lines change nothing a test runs.
        edits = {n for n in changed.get(module, set()) if 0 < n <= len(rows) and rows[n - 1].strip() and not rows[n - 1].strip().startswith('#')}
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):continue
            methods = [n for n in node.body if isinstance(n, ast.FunctionDef)]
            helpers = {n.name: n for n in methods if not n.name.startswith('test_')}
            # A changed fixture or class attribute can break every test of the class; a changed helper only the
            # tests that use it, directly or through another helper.
            inside = set().union(*(set(range(n.lineno, n.end_lineno + 1)) for n in methods)) if methods else set()
            whole = bool(FIXTURES & {n for n, h in helpers.items() if spans(h, edits)}) or bool(edits & (set(range(node.lineno, node.end_lineno + 1)) - inside))
            touched = {n for n, h in helpers.items() if spans(h, edits) or names(h) & shared}
            while True:
                more = {n for n, h in helpers.items() if n not in touched and names(h) & touched}
                if not more:break
                touched |= more
            for test in methods:
                if not test.name.startswith('test_'):continue
                if (module in CORE or whole or PLATFORM.search(ast.get_source_segment(source, test))
                        or spans(test, edits) or names(test) & (touched | shared)):
                    chosen.append(f'oh.{module}.{node.name}.{test.name}')
    return chosen


if __name__ == '__main__':
    # Bytes, so Windows never adds \r to the test names the shell passes on.
    sys.stdout.buffer.write(''.join(t + '\n' for t in select(sys.argv[1] if len(sys.argv) > 1 else None)).encode())
