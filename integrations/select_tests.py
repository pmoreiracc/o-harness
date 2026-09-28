"""Pick the tests a pull request must pass on Windows: OH's platform layer, tests that exercise
platform-specific behavior, and every test the change adds or edits or whose shared code it changes. The full
suite runs on Windows nightly, on demand and before a release (.github/workflows/full.yml).

The change is read by comparing each test module's code before and after it, part by part (each module-level
statement, each test class's header and members), not by diff line numbers: a commented-out, blanked or deleted
line changes the code wherever it sits, while blank lines and comments change nothing. Changed parts reach
every part that uses them, in the same module or through imports from another test module.

  python3 integrations/select_tests.py [base]   print the chosen test ids, one per line
"""
import ast
import copy
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
FIXTURES = {'setUp', 'setUpClass', 'tearDown', 'tearDownClass'}


def before(base):
    """Each test module's source at the merge base with `base` ('' for a module the change adds)."""
    git = lambda *a:subprocess.run(['git', '-C', str(ROOT), *a], capture_output=True, text=True)
    merge = git('merge-base', base, 'HEAD').stdout.strip()
    if not merge:sys.exit(f'select_tests: cannot find {base}; fetch it or pass another base')
    listed = git('ls-tree', '--name-only', merge, 'runtime/oh/').stdout.split()
    return {Path(p).stem: git('show', f'{merge}:{p}').stdout for p in listed if re.fullmatch(r'runtime/oh/test_\w+\.py', p)}


def is_test_class(node):
    """A class holding tests, whatever its name."""
    return isinstance(node, ast.ClassDef) and any(isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name.startswith('test_') for m in node.body)


def bound(node):
    """The names a statement defines, or None when it defines none (such as a bare call)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):return {node.name}
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
    if isinstance(node, (ast.Import, ast.ImportFrom)):return {(a.asname or a.name).split('.')[0] for a in node.names}
    return None


def parts(source):
    """A module's parts, each with a fingerprint of its code (ast.dump leaves out positions, blank lines and
    comments): ('name',) per module-level name, ('!',) for statements that bind none, (Class, '') for a test
    class's header and (Class, member) for each of its members."""
    found = {}
    for node in ast.parse(source).body if source else []:
        if is_test_class(node):
            header = copy.copy(node);header.body = []  # the class line and its decorators
            found[(node.name, '')] = ast.dump(header)
            for member in node.body:
                for name in bound(member) or {'!'}:found[(node.name, name)] = found.get((node.name, name), '') + ast.dump(member)
        else:
            for name in bound(node) or {'!'}:found[(name,)] = found.get((name,), '') + ast.dump(node)
    return found


def uses(node, module, cls, aliases, imported):
    """The parts a piece of code uses: its module's names, its class's members (`self.x`, `cls.x`), and another
    test module's parts reached through `from . import test_x as alias` or `from .test_x import name`."""
    used = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            used.add((module, n.id))
            if n.id in imported:used.add(imported[n.id])
        elif isinstance(n, ast.Attribute):
            chain, value = [n.attr], n.value
            while isinstance(value, ast.Attribute):chain.insert(0, value.attr);value = value.value
            if isinstance(value, ast.Name):
                if value.id in ('self', 'cls') and cls:used.add((module, cls, chain[0]))
                elif value.id in aliases:
                    used.add((aliases[value.id], chain[0]))
                    if len(chain) > 1:used.add((aliases[value.id], chain[0], chain[1]))
    return used


def links(tree, known):
    """This module's aliases for other test modules, and the names it imports from them."""
    aliases, imported = {}, {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            source = (n.module or '').lstrip('.').split('.')[-1]
            for a in n.names:
                if not n.module and a.name in known:aliases[a.asname or a.name] = a.name
                elif source in known:imported[a.asname or a.name] = (source, a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split('.')[-1] in known and a.asname:aliases[a.asname] = a.name.split('.')[-1]
    return aliases, imported


def pick(old, new):
    """The test ids to run, from each test module's source before (`old`) and after (`new`) the change."""
    trees = {module: ast.parse(source) for module, source in new.items()}
    changed = set()
    for module, source in new.items():
        a, b = parts(old.get(module, '')), parts(source)
        changed |= {(module, *key) for key in a.keys() | b.keys() if a.get(key) != b.get(key)}
    # Grow to every part that uses a changed part, in any module, until nothing more changes.
    pieces = []
    for module, tree in trees.items():
        aliases, imported = links(tree, trees.keys())
        for node in tree.body:
            if is_test_class(node):
                for member in node.body:
                    for name in bound(member) or {'!'}:
                        pieces.append(((module, node.name, name), uses(member, module, node.name, aliases, imported)))
            else:
                for name in bound(node) or {'!'}:pieces.append(((module, name), uses(node, module, None, aliases, imported)))
    while True:
        more = {key for key, used in pieces if key not in changed and used & changed}
        if not more:break
        changed |= more
    chosen = []
    for module, tree in trees.items():
        everything = (module, '!') in changed
        for node in tree.body:
            if not is_test_class(node):continue
            members = {(module, node.name, name) for member in node.body for name in bound(member) or {'!'}}
            # The class's header, a fixture, or anything in its body other than a method runs for every test.
            whole = everything or (module, node.name, '') in changed or any(
                key in changed and (key[2] in FIXTURES or not key[2].startswith('test_') and not callable_member(node, key[2])) for key in members)
            for member in node.body:
                if not (isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name.startswith('test_')):continue
                source = ast.get_source_segment(new[module], member) or ''
                if module in CORE or whole or PLATFORM.search(source) or (module, node.name, member.name) in changed:
                    chosen.append(f'oh.{module}.{node.name}.{member.name}')
    return chosen


def callable_member(cls, name):
    """Whether a class member is a method (which affects only the tests that use it)."""
    return any(isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name == name for m in cls.body)


def select(base=None):
    new = {path.stem: path.read_text(encoding='utf-8') for path in sorted(TESTS.glob('test_*.py'))}
    return pick(before(base) if base else new, new)


if __name__ == '__main__':
    # Bytes, so Windows never adds \r to the test names the shell passes on.
    sys.stdout.buffer.write(''.join(t + '\n' for t in select(sys.argv[1] if len(sys.argv) > 1 else None)).encode())
