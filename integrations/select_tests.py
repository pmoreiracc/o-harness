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
    """What each test file changed since `base`, per module name: the lines a change wrote (`lines`), and for each
    pure deletion the line it followed (`anchors`)."""
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
            else:anchors.setdefault(name, set()).add(start)
    return lines, anchors


def names(node):
    """What code uses: `self.x`/`cls.x` members and bare names (decorators included)."""
    return ({n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in ('self', 'cls')}
            | {n.id for n in ast.walk(node) if isinstance(n, ast.Name)})


def bound(node):
    """The names a statement defines, or None when it defines none (such as a bare call)."""
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):return {node.name}
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
    if isinstance(node, (ast.Import, ast.ImportFrom)):return {(a.asname or a.name).split('.')[0] for a in node.names}
    return None


def touches(node, span, lines, deletions):
    """Whether the change touched a statement: an edited line inside it, a deletion inside it, or a deletion right
    above a function or class (a decorator, such as a skip, removed)."""
    first = min(span)
    return bool(span & lines) or any(
        (p in span and p + 1 in span) or (p + 1 == first and isinstance(node, (ast.FunctionDef, ast.ClassDef))) for p in deletions)


def extent(node, rows):
    """The lines a statement covers: from its first decorator, and any comment lines right above it (such as a
    decorator someone commented out), to its last line."""
    start = min([node.lineno] + [d.lineno for d in getattr(node, 'decorator_list', [])])
    while start > 1 and rows[start - 2].strip().startswith('#'):start -= 1
    return set(range(start, node.end_lineno + 1))


FIXTURES = {'setUp', 'setUpClass', 'tearDown', 'tearDownClass'}


def select(base=None):
    changed, anchors = changed_lines(base) if base else ({}, {})
    return pick({path.stem: path.read_text(encoding='utf-8') for path in sorted(TESTS.glob('test_*.py'))}, changed, anchors)


def pick(sources, changed, anchors):
    """The test ids to run, from each module's source and the lines the change touched in it (edited lines, and
    both sides of each deletion). Any such line inside a statement counts: a test's own lines select it; a
    helper's, a fixture's or a class attribute's select the tests that depend on it; a module-level statement's
    select the tests that use the names it defines, directly, through helpers and derived values, or from a
    module that imports them. Lines outside every statement (blank lines, and comments not right above one)
    never change what runs."""
    trees = {module: (source, ast.parse(source), source.splitlines()) for module, source in sources.items()}
    edits = {module: changed.get(module, set()) for module in trees}
    deleted = {module: anchors.get(module, set()) for module in trees}
    tests = lambda node:isinstance(node, ast.ClassDef) and node.name.endswith('Test')
    changed_names, everything = {module: set() for module in trees}, set()
    for module, (_, tree, rows) in trees.items():
        for node in tree.body:
            if not tests(node) and touches(node, extent(node, rows), edits[module], deleted[module]):
                defined = bound(node)
                if defined is None:everything.add(module)
                else:changed_names[module] |= defined
    def visible(module):
        """The changed names a module sees: its own, and those it imports from another test module."""
        seen = set(changed_names[module])
        for n in ast.walk(trees[module][1]):
            if isinstance(n, ast.ImportFrom) and n.module:
                source = n.module.lstrip('.').split('.')[-1]
                seen |= {a.asname or a.name for a in n.names if a.name in changed_names.get(source, set())}
        return seen
    while True:  # a helper or a value built from a changed name is changed too
        grown = False
        for module, (_, tree, _) in trees.items():
            seen = visible(module)
            for node in tree.body:
                defined = None if tests(node) else bound(node)
                if defined and defined - changed_names[module] and names(node) & seen:
                    changed_names[module] |= defined;grown = True
        if not grown:break
    chosen = []
    for module, (source, tree, rows) in trees.items():
        shared, lines, gone = visible(module), edits[module], deleted[module]
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):continue
            members = [(member, extent(member, rows)) for member in node.body]
            helpers = {m.name: (m, span) for m, span in members if isinstance(m, ast.FunctionDef) and not m.name.startswith('test_')}
            # A helper the change touched, or one using a changed name, affects the tests that use it, directly or
            # through another helper. A fixture runs for every test, and so does anything else in the class body.
            touched = {name for name, (m, span) in helpers.items() if touches(m, span, lines, gone) or names(m) & shared}
            while True:
                more = {name for name, (m, _) in helpers.items() if name not in touched and names(m) & touched}
                if not more:break
                touched |= more
            header = extent(node, rows) - set().union(*(span for _, span in members)) - {n for n in range(1, len(rows) + 1) if not rows[n - 1].strip()}
            body = any((touches(m, span, lines, gone) or names(m) & shared) for m, span in members if not isinstance(m, ast.FunctionDef))
            whole = module in everything or bool(FIXTURES & touched) or body or bool(header & lines) or bool(header & gone)
            for m, span in members:
                if not (isinstance(m, ast.FunctionDef) and m.name.startswith('test_')):continue
                if (module in CORE or whole or PLATFORM.search(ast.get_source_segment(source, m))
                        or touches(m, span, lines, gone) or names(m) & (touched | shared)):
                    chosen.append(f'oh.{module}.{node.name}.{m.name}')
    return chosen


if __name__ == '__main__':
    # Bytes, so Windows never adds \r to the test names the shell passes on.
    sys.stdout.buffer.write(''.join(t + '\n' for t in select(sys.argv[1] if len(sys.argv) > 1 else None)).encode())
