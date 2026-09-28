"""Pick the tests a pull request must pass on Windows: OH's platform layer, tests that exercise
platform-specific behavior, and every test the change adds or edits. The full suite runs on Windows
nightly and before a release.

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


def select(base=None):
    changed = changed_lines(base) if base else {}
    chosen = []
    for path in sorted(TESTS.glob('test_*.py')):
        module, source = path.stem, path.read_text(encoding='utf-8')
        edits = changed.get(module, set())
        for node in ast.parse(source).body:
            if not isinstance(node, ast.ClassDef):continue
            methods = [n for n in node.body if isinstance(n, ast.FunctionDef)]
            tests = [n for n in methods if n.name.startswith('test_')]
            # A changed helper or fixture can break any test of its class.
            shared = any(edits & set(range(n.lineno, n.end_lineno + 1)) for n in methods if not n.name.startswith('test_'))
            for test in tests:
                body = ast.get_source_segment(source, test)
                if (module in CORE or shared or PLATFORM.search(body)
                        or edits & set(range(test.lineno, test.end_lineno + 1))):
                    chosen.append(f'oh.{module}.{node.name}.{test.name}')
    return chosen


if __name__ == '__main__':
    # Bytes, so Windows never adds \r to the test names the shell passes on.
    sys.stdout.buffer.write(''.join(t + '\n' for t in select(sys.argv[1] if len(sys.argv) > 1 else None)).encode())
