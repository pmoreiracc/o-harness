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


def test_classes(tree):
    """The module's test classes, whatever their names: those holding tests, those built on a TestCase, and those
    built on another test class, here or imported from a test module."""
    imported = {a.asname or a.name for n in tree.body if isinstance(n, ast.ImportFrom) and (n.module or '').split('.')[-1].startswith('test_')
                for a in n.names}
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    def base(b):
        name = b.attr if isinstance(b, ast.Attribute) else b.id if isinstance(b, ast.Name) else ''
        return name
    found = set()
    while True:
        more = {c.name for c in classes if c.name not in found and (
            any(isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name.startswith('test_') for m in c.body)
            or any(base(b).endswith('TestCase') or base(b) in found or base(b) in imported for b in c.bases))}
        if not more:return found
        found |= more


def bound(node):
    """The names a module statement defines (for a compound statement such as `if`, those defined inside it), or
    None when it defines none (such as a bare call)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):return {node.name}
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
    if isinstance(node, (ast.Import, ast.ImportFrom)):return {(a.asname or a.name).split('.')[0] for a in node.names}
    inner = set()
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.stmt):inner |= bound(child) or set()
    return inner or None


def parts(source):
    """A module's parts, each with a fingerprint of its code (ast.dump leaves out positions, blank lines and
    comments): ('name',) per module-level name, ('!',) for statements that bind none, (Class, '') for a test
    class's header (its line, bases and decorators) and (Class, member) for each of its members."""
    found, tree = {}, ast.parse(source)
    testing = test_classes(tree)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in testing:
            found[(node.name, '')] = ast.dump(header(node))
            for member in node.body:
                for name in bound(member) or {'!'}:found[(node.name, name)] = found.get((node.name, name), '') + ast.dump(member)
        else:
            for name in bound(node) or {'!'}:found[(name,)] = found.get((name,), '') + ast.dump(node)
    return found


def header(node):
    """A class without its body: its line, bases, keywords and decorators."""
    top = copy.copy(node);top.body = []
    return top


def uses(node, module, cls, aliases, imported, classes, testing):
    """The parts a piece of code uses: its module's names, its class's members (`self.x`, `cls.x`), a test class
    and its members by name (`W`, `W.setUp`), and another test module's parts reached through
    `from . import test_x as alias`, `import ...test_x as alias` or `from .test_x import name`."""
    used = set()
    # A class named before a dot (`W.setUp`) means that member, not the whole class.
    dotted = {id(n.value) for n in ast.walk(node) if isinstance(n, ast.Attribute) and isinstance(n.value, (ast.Name, ast.Attribute))}
    def target(name, whole=True):
        """What a bare name means here: another module's part, and a test class when it names one."""
        found = {imported[name]} if name in imported else {(module, name)}
        return found | {classes[name]} if name in classes and whole else found
    for n in ast.walk(node):
        if isinstance(n, ast.Name):used |= target(n.id, id(n) not in dotted)
        elif isinstance(n, ast.Attribute) and id(n) not in dotted:  # the whole chain, once
            chain, value = [n.attr], n.value
            while isinstance(value, ast.Attribute):chain.insert(0, value.attr);value = value.value
            if not isinstance(value, ast.Name):continue
            if value.id in ('self', 'cls') and cls:used.add((module, cls, chain[0]))
            elif value.id in aliases:
                other = aliases[value.id]
                if len(chain) > 1 and chain[0] in testing.get(other, ()):used.add((other, chain[0], chain[1]))
                else:used.add((other, chain[0]))
            elif value.id in classes:used.add((*classes[value.id], chain[0]))
    return used


def links(tree, module, known, testing):
    """This module's aliases for other test modules, the names it imports from them, and the test classes it can
    name (its own, and those it imports), each as (module, Class)."""
    aliases, imported = {}, {}
    classes = {name: (module, name) for name in testing.get(module, ())}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            source = (n.module or '').lstrip('.').split('.')[-1]
            for a in n.names:
                if not n.module and a.name in known:aliases[a.asname or a.name] = a.name
                elif source in known:
                    imported[a.asname or a.name] = (source, a.name)
                    if a.name in testing.get(source, ()):classes[a.asname or a.name] = (source, a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split('.')[-1] in known and a.asname:aliases[a.asname] = a.name.split('.')[-1]
    return aliases, imported, classes


# Hooks unittest runs around every test of a class, or of a module.
FIXTURES |= {'asyncSetUp', 'asyncTearDown', 'run', 'debug', '__init__', '__call__'}
MODULE_FIXTURES = {'setUpModule', 'tearDownModule', 'load_tests', '!'}


def pick(old, new):
    """The test ids to run, from each test module's source before (`old`) and after (`new`) the change. A class
    or module whose every test must run is named whole, so unittest also runs the tests it inherits."""
    trees = {module: ast.parse(source) for module, source in new.items()}
    testing = {module: test_classes(tree) for module, tree in trees.items()}
    changed = set()
    for module, source in new.items():
        a, b = parts(old.get(module, '')), parts(source)
        changed |= {(module, *key) for key in a.keys() | b.keys() if a.get(key) != b.get(key)}
    # Grow to every part that uses a changed part, in any module, until nothing more changes. A test class counts
    # as changed, as (module, Class), when any part of it has.
    pieces = []
    for module, tree in trees.items():
        aliases, imported, classes = links(tree, module, trees.keys(), testing)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name in testing[module]:
                pieces.append(((module, node.name, ''), uses(header(node), module, node.name, aliases, imported, classes, testing)))
                for member in node.body:
                    for name in bound(member) or {'!'}:
                        pieces.append(((module, node.name, name), uses(member, module, node.name, aliases, imported, classes, testing)))
            else:
                for name in bound(node) or {'!'}:pieces.append(((module, name), uses(node, module, None, aliases, imported, classes, testing)))
    while True:
        more = {key for key, used in pieces if key not in changed and used & changed}
        more |= {key[:2] for key in changed if len(key) == 3 and key[1] in testing.get(key[0], ())} - changed
        if not more:break
        changed |= more
    chosen = []
    for module, tree in trees.items():
        if any((module, hook) in changed for hook in MODULE_FIXTURES):
            chosen.append(f'oh.{module}');continue
        for node in tree.body:
            if not (isinstance(node, ast.ClassDef) and node.name in testing[module]):continue
            # The class's header (bases, decorators), a fixture, or anything in its body other than a method runs
            # for every test.
            whole = (module, node.name, '') in changed or any(
                (module, node.name, name) in changed and (name in FIXTURES or not name.startswith('test_') and not callable_member(node, name))
                for member in node.body for name in bound(member) or {'!'})
            if whole:
                chosen.append(f'oh.{module}.{node.name}');continue
            for member in node.body:
                if not (isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name.startswith('test_')):continue
                source = ast.get_source_segment(new[module], member) or ''
                if module in CORE or PLATFORM.search(source) or (module, node.name, member.name) in changed:
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
