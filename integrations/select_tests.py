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
    """What each test file changed since `base`, per module name: the lines a change wrote (`lines`), and the lines
    on both sides of a pure deletion (`anchors`)."""
    merge = subprocess.run(['git', '-C', str(ROOT), 'merge-base', base, 'HEAD'], capture_output=True, text=True).stdout.strip()
    if not merge:return {}, {}
    diff = subprocess.run(['git', '-C', str(ROOT), 'diff', '-U0', merge, '--', 'runtime/oh/test_*.py'],
                          capture_output=True, text=True, check=True).stdout
    lines, anchors, name = {}, {}, None
    for row in diff.splitlines():
        if row.startswith('+++ '):
            name = Path(row[6:]).stem if row != '+++ /dev/null' else None
        elif row.startswith('@@') and name:
            start, count = re.match(r'@@ -\S+ \+(\d+)(?:,(\d+))? @@', row).groups()
            start, count = int(start), int(count if count is not None else 1)
            if count:lines.setdefault(name, set()).update(range(start, start + count))
            else:anchors.setdefault(name, set()).update((start, start + 1))
    return lines, anchors


def names(node):
    """What code uses: `self.x`/`cls.x` members and bare names."""
    return ({n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in ('self', 'cls')}
            | {n.id for n in ast.walk(node) if isinstance(n, ast.Name)})


def bound(node):
    """The module-level names a statement defines, or None when it defines none (such as a bare call)."""
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):return {node.name}
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
    if isinstance(node, (ast.Import, ast.ImportFrom)):return {(a.asname or a.name).split('.')[0] for a in node.names}
    return None


def spans(node, edits):
    return bool(edits & set(range(node.lineno, node.end_lineno + 1)))


FIXTURES = {'setUp', 'setUpClass', 'tearDown', 'tearDownClass'}


def select(base=None):
    changed, anchors = changed_lines(base) if base else ({}, {})
    return pick({path.stem: path.read_text(encoding='utf-8') for path in sorted(TESTS.glob('test_*.py'))}, changed, anchors)


def pick(sources, changed, anchors):
    """The test ids to run, from each module's source and the lines the change touched in it. Inside a function
    every edited line counts, even one turned into a comment; between definitions, blank and comment lines never
    change what runs. A deletion only counts inside a class: a test that still used a deleted name fails
    everywhere, not only on Windows."""
    trees, edits, loose = {}, {}, {}
    for module, source in sources.items():
        rows = source.splitlines()
        trees[module] = (source, ast.parse(source))
        edits[module] = changed.get(module, set()) | anchors.get(module, set())
        spacing = {n for n in edits[module] if not (0 < n <= len(rows)) or not rows[n - 1].strip() or rows[n - 1].strip().startswith('#')}
        loose[module] = edits[module] - spacing  # what counts between definitions
    # Changed module-level names (a deletion there leaves nothing to use), and the helpers that use them.
    changed_names, everything = {module: set() for module in trees}, set()
    for module, (_, tree) in trees.items():
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name.endswith('Test'):continue
            if spans(node, loose[module] - anchors.get(module, set())):
                defined = bound(node)
                if defined is None:everything.add(module)
                else:changed_names[module] |= defined
    def visible(module):
        """The changed names this module sees: its own, and those it imports from another test module."""
        imported = {a.asname or a.name for n in ast.walk(trees[module][1]) if isinstance(n, ast.ImportFrom) and n.module
                    for a in n.names if n.module.lstrip('.').split('.')[-1] in changed_names and a.name in changed_names[n.module.lstrip('.').split('.')[-1]]}
        return changed_names[module] | imported
    while True:
        grown = False
        for module, (_, tree) in trees.items():
            seen = visible(module)
            for node in tree.body:
                if (isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.endswith('Test')
                        and node.name not in changed_names[module] and names(node) & seen):
                    changed_names[module].add(node.name);grown = True
        if not grown:break
    chosen = []
    for module, (source, tree) in trees.items():
        shared = visible(module)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):continue
            methods = [n for n in node.body if isinstance(n, ast.FunctionDef)]
            members = {n.name: n for n in methods if not n.name.startswith('test_')}
            # A changed helper selects the tests that use it, directly or through another helper; a fixture runs
            # for every test, so one affected by the change selects them all, as does a changed class attribute.
            touched = {n for n, h in members.items() if spans(h, edits[module]) or names(h) & shared}
            while True:
                more = {n for n, h in members.items() if n not in touched and names(h) & touched}
                if not more:break
                touched |= more
            inside = set().union(*(set(range(n.lineno, n.end_lineno + 1)) for n in methods)) if methods else set()
            whole = (module in everything or bool(FIXTURES & touched)
                     or bool(loose[module] & (set(range(node.lineno, node.end_lineno + 1)) - inside)))
            for test in methods:
                if not test.name.startswith('test_'):continue
                if (module in CORE or whole or PLATFORM.search(ast.get_source_segment(source, test))
                        or spans(test, edits[module]) or names(test) & (touched | shared)):
                    chosen.append(f'oh.{module}.{node.name}.{test.name}')
    return chosen


if __name__ == '__main__':
    # Bytes, so Windows never adds \r to the test names the shell passes on.
    sys.stdout.buffer.write(''.join(t + '\n' for t in select(sys.argv[1] if len(sys.argv) > 1 else None)).encode())
