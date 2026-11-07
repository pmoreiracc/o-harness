"""Pick the tests a pull request must pass on Windows: OH's platform layer, tests that exercise platform-specific
behavior, every test module the change edits, and every test module that imports an edited one (directly or
through another). The full suite runs on Windows nightly, on demand (.github/workflows/full.yml),
which covers changes to runtime code.

A module counts as edited when its code differs before and after the change, compared by syntax tree: blank lines
and comments change nothing. Edited modules run whole. Test ids come from unittest's own loader, so every id loads.

  python3 integrations/select_tests.py [base]   print the chosen test ids, one per line
  python3 integrations/select_tests.py --run-selected [1|4] [--shard 0|1]   run names from stdin

Windows PR CI partitions the same selection across two runners with four processes each. Most cases stay grouped
by module. A few historically slow methods run separately if their module and class have no shared setup.
Local Windows runs use one runner. `OH_TEST_WORKERS=1 bash integrations/test.sh windows` runs them serially.

Locally (and as the check OH runs on this repository's deliveries, when its `checks` setting names
`integrations/test.sh affected {base}`), `--affected <base>` runs only the test modules a change needs,
learned from the pre-separation harness's verify-change.sh: each changed path maps to what it needs (OWNERS),
explanatory text needs nothing, a runtime module needs the test modules that import it (directly or through other
modules), and a path no rule names stops the run with its name, so its owner is added here rather than guessed.
Two test processes run at a time. PR checks combine affected tests with a small core;
full discovery runs nightly. Sanity is a fast deterministic check,
not evidence that the native CLI workflows passed.

  python3 integrations/select_tests.py --affected [base] [--list]   run (or list) the affected test modules
  python3 integrations/select_tests.py --core   run the deterministic core
  python3 integrations/select_tests.py --pr [base] [--list]   run the PR selection
"""
import ast
from hashlib import sha256
import inspect
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / 'runtime/oh'
# Modules that test OH's OS layer: locks, process groups, launchers, host binaries, installation.
CORE = {'test_system', 'test_integration', 'test_installation', 'test_controls', 'test_windows'}
# Test bodies that touch what differs on Windows: line endings, permissions, deletion, paths, processes.
# Writing an LF fixture is ordinary setup. Select CRLF, translation, and real platform behavior.
PLATFORM = re.compile(r"""os\.name|sys\.platform|[Ww]indows|\\r\\n|CRLF|newline\s*=\s*(?!['"]\\n['"])\S|chmod|st_mode|rmtree|symlink|os\.sep|\.cmd\b|\.exe\b|signal\.|kill\(""")
FIXTURE_PREFIX = 'test_fixtures_'

# Existing causal cases: native answers, bounded scope, sequential workers, checks,
# Stop, and exact reviewed completion. Keep this list small; live sanity is separate.
SANITY = (
    'oh.test_gates',
    'oh.test_delivery.DeliveryRequestTest',
    'oh.test_config.ConfigTest.test_every_approval_names_its_limits',
    'oh.test_workflow.NativeWorkflowTest.test_scope_needs_native_approval_and_preserves_its_immutable_task_window',
    'oh.test_workflow.NativeWorkflowTest.test_native_admissions_are_sequential_fresh_and_use_explicit_profiles',
    'oh.test_workflow.NativeWorkflowTest.test_review_requires_completed_work_and_passing_checks_for_the_final_candidate',
    'oh.test_workflow.NativeWorkflowTest.test_stop_refuses_unsettled_native_child_and_resume_never_renews_allowance',
    'oh.test_workflow.NativeWorkflowTest.test_completion_commits_exact_reviewed_tree_once_and_task_grants_do_not_expand',
)

# Relative weights from the broad Windows runs on #142 and #147. Keep module fixtures
# together and start expensive groups while all workers are available.
WINDOWS_PRIORITY = {
    'oh.test_recovery': 7,
    'oh.test_workflow': 6,
    'oh.test_controls': 5,
    'oh.test_delivery': 4,
    'oh.test_cancellation': 3,
    'oh.test_design_adapter': 2,
    'oh.test_planning': 1,
}

# Approximate seconds from broad Windows CI. Assign by cost to eight lanes,
# then run each half on a separate four-worker runner.
WINDOWS_CASE_COST = {
    'oh.test_recovery': 32, 'oh.test_workflow': 24, 'oh.test_controls': 40,
    'oh.test_delivery': 30, 'oh.test_cancellation': 30, 'oh.test_design_adapter': 40,
    'oh.test_planning': 36, 'oh.test_private': 6,
}
WINDOWS_LONG_CASES = {
    'oh.test_recovery.RecoveryTest.test_entry_replay_finishes_both_pointers_and_records_its_initial_grant_once': 350,
    'oh.test_recovery.RecoveryTest.test_selection_replay_repairs_failed_control_write_and_both_host_turn_fences': 161,
    'oh.test_workflow.NativeWorkflowTest.test_completion_commits_exact_reviewed_tree_once_and_task_grants_do_not_expand': 192,
    'oh.test_workflow.NativeWorkflowTest.test_review_attempts_and_findings_survive_repairs_and_spent_window': 85,
    'oh.test_controls.ControlsTest.test_idle_selection_publishes_exact_reviewed_commits_without_stopping_prior_work': 242,
    'oh.test_delivery.DeliveryTest.test_delivery_request_survives_only_its_bound_prerequisite_on_both_hosts': 325,
    'oh.test_delivery.DeliveryTest.test_converged_tracks_finalize_through_native_check_review_and_completion': 143,
    # PR #160: the enlarged workflow/recovery groups otherwise occupied one
    # worker for 851s/661s. Split these measured cases through the existing lanes.
    'oh.test_workflow.NativeWorkflowTest.test_additional_review_reverifies_actual_inputs_and_completes_a_clean_scoped_repair': 145,
    'oh.test_workflow.NativeWorkflowTest.test_publication_reuses_the_existing_pr_and_unknown_discovery_does_not_reopen_work': 65,
    'oh.test_workflow.NativeWorkflowTest.test_legacy_resume_preserves_original_findings_and_consumed_review_allowance': 55,
    'oh.test_workflow.NativeWorkflowTest.test_partial_retention_preserves_stale_selection_and_original_render_boundary': 50,
    'oh.test_workflow.NativeWorkflowTest.test_precommit_intent_rechecks_proof_and_accepts_fresh_reviewed_repair': 48,
    'oh.test_workflow.NativeWorkflowTest.test_interrupted_commit_recovers_without_another_review_or_duplicate_commit': 43,
    'oh.test_recovery.RecoveryTest.test_private_restart_restores_approved_plan_and_completes_with_valid_publication_evidence': 90,
    'oh.test_recovery.RecoveryTest.test_restart_after_merged_task_keeps_completion_evidence_and_selects_next_batch': 56,
    'oh.test_recovery.RecoveryTest.test_continue_clean_delivery_keeps_assessment_and_retries_reported_work': 55,
}


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


def test_cases(names, *, strict=False):
    """Expand modules with the same loader the workers use, preserving duplicates."""
    sys.path.insert(0, str(ROOT / 'runtime'))
    try:
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromNames(names)
        if strict and loader.errors:
            raise ValueError('Could not load the Windows test selection:\n' + '\n'.join(loader.errors))
        return list(cases(suite))
    finally:
        sys.path.pop(0)


def test_ids(names):
    return [case.id() for case in test_cases(names)]


def id_digest(ids):
    return sha256('\n'.join(sorted(ids)).encode()).hexdigest()


def shared_setup(case):
    module = sys.modules[type(case).__module__]
    if any(hasattr(module, name) for name in ('setUpModule', 'tearDownModule')):
        return True
    return any(getattr(getattr(type(case), name), '__func__', None) is not getattr(unittest.TestCase, name).__func__
               for name in ('setUpClass', 'tearDownClass'))


def windows_shards(names, workers):
    """Partition one exact selection. Keep shared setup together on the same worker."""
    groups, costs = {}, {}
    for case in test_cases(names, strict=True):
        name, module = case.id(), type(case).__module__
        group = name if name in WINDOWS_LONG_CASES and not shared_setup(case) else module
        groups.setdefault(group, []).append(name)
        costs[group] = costs.get(group, 0) + WINDOWS_LONG_CASES.get(name, WINDOWS_CASE_COST.get(module, 3))
    shards = [{}, {}]
    loads = [0] * (2 * workers)
    for group in sorted(groups, key=lambda name: (-costs[name], name)):
        lane = min(range(len(loads)), key=loads.__getitem__)
        shards[lane % len(shards)][group] = groups[group]
        loads[lane] += costs[group]
    return shards


def select(base=None, *, explain=False):
    new = {path.stem: path.read_text(encoding='utf-8') for path in sorted(TESTS.glob('test_*.py'))}
    old = before(base) if base else new
    changed = edited(old, new)
    whole = (CORE | changed) & new.keys()
    sys.path.insert(0, str(ROOT / 'runtime'))
    chosen = [f'oh.{m}' for m in sorted(whole) if not m.startswith(FIXTURE_PREFIX)]
    if explain:
        for name in chosen:
            module=name.split('.')[-1]
            reason=('platform module' if module in CORE else 'edited module'
                    if code(old.get(module,''))!=code(new[module]) else 'imports edited test code')
            print(f'{name}: {reason}',file=sys.stderr)
    for case in cases(unittest.defaultTestLoader.discover(str(TESTS), 'test_*.py', str(ROOT / 'runtime'))):
        if isinstance(case, unittest.loader._FailedTest):  # a module that fails to import runs, so its error shows
            chosen.append(case._testMethodName);continue
        package, _, module = type(case).__module__.rpartition('.')
        if package != 'oh' or module in whole:continue
        try:source = inspect.getsource(getattr(type(case), case._testMethodName))
        except (OSError, TypeError):continue
        if match:=PLATFORM.search(source):
            chosen.append(case.id())
            if explain:print(f'{case.id()}: platform marker {match[0]!r}',file=sys.stderr)
    return chosen


# Each changed path's needs, first match wins: runtime modules (their importing tests run) or test modules.
OWNERS = [
    ('docs/*', ()), ('README.md', ()), ('CONTRIBUTING.md', ()), ('SECURITY.md', ()), ('LICENSE', ()), ('AGENTS.md', ()),
    ('CLAUDE.md', ()), ('.github/*', ()), ('.gitignore', ()), ('.claude/*', ()), ('.codex/*', ()), ('config/invariants.json', ()),
    ('.gitattributes', ('test_windows',)),
    ('integrations/select_tests.py', ('test_select_tests',)), ('integrations/test.sh', ('test_select_tests',)),
    ('integrations/full_tests.py', ('test_select_tests',)),
    ('integrations/oh_dev.py', ('test_installation',)),
    ('integrations/e2e_fixture.py', ('test_e2e_fixture',)),
    ('integrations/windows-*.ps1', ('test_windows',)), ('integrations/*', ()),  # the rest run only in CI
    ('prompts/*', ('native',)), ('workflows/*', ('native', 'installation', 'mcp_server')), ('config/*', ('config',)),
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
        return sorted(m for m in sources if m.startswith('test_') and not m.startswith(FIXTURE_PREFIX))
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
    return sorted(m for m in tests if not m.startswith(FIXTURE_PREFIX))


def pr_selection(paths, sources):
    # Known runner changes exercise their own selection/sharding tests plus core.
    # An unknown path still needs conservative coverage until it has an owner.
    broad = any(needs(path) is None for path in paths)
    modules = (sorted(m for m in sources if m.startswith('test_') and not m.startswith(FIXTURE_PREFIX))
               if broad else affected(paths, sources))
    names = ['oh.' + module for module in modules]
    # A module subsumes its individual smoke cases; execute each test only once.
    return names + [name for name in SANITY if '.'.join(name.split('.')[:2]) not in names]


def run(names, workers=2, report=False, shard=None):
    """Run the exact selected names, grouped by module, in separate processes; True when every group passed."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import os
    from time import monotonic
    if shard is None:
        groups = {}
        for name in names:groups.setdefault('.'.join(name.split('.')[:2]), []).append(name)
    else:
        partitions = windows_shards(names, workers)
        shard_names = [[name for members in partition.values() for name in members] for partition in partitions]
        groups, names = partitions[shard], shard_names[shard]
        full_ids = [name for partition in shard_names for name in partition]
        assignments = [f'{index}:{name}' for index, partition in enumerate(shard_names) for name in partition]
        print(f'Windows shard {shard+1}/2: {len(names)} of {len(full_ids)} tests', flush=True)
        print(f'Windows full test ID digest {id_digest(full_ids)}', flush=True)
        print(f'Windows selection digest {id_digest(assignments)}', flush=True)
    if not groups:raise ValueError('No selected tests')
    started=monotonic()
    def one(module, names):
        command = [sys.executable, '-m', 'unittest', '--durations', '15', *names]
        if report:print(f"start  {module}  +{monotonic()-started:.1f}s", flush=True)
        try:
            return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                  env=os.environ | {'PYTHONPATH': str(ROOT / 'runtime'), 'PYTHONUTF8': '1'})
        except OSError as exc:
            return subprocess.CompletedProcess(command, 1, '', str(exc))
    if report:
        ids=test_ids(names) if shard is None else names
        fingerprint=id_digest(ids)
        print(f'Running {len(ids)} tests in {len(groups)} groups with {workers} workers '
              f'(test ID digest {fingerprint})',flush=True)
    passed = True
    with ThreadPoolExecutor(workers) as pool:
        order = sorted(groups, key=lambda module: -WINDOWS_PRIORITY.get(module, 0)) if report and shard is None else groups
        pending = {pool.submit(one, module, groups[module]): module for module in order}
        for future in as_completed(pending):
            module, result = pending[future], future.result()
            print(f"{'ok' if not result.returncode else 'FAILED'}  {module}", flush=True)
            if result.returncode:passed = False
            if report or result.returncode:print(result.stdout + result.stderr, flush=True)
    if report:print(f'Selected tests completed in {monotonic() - started:.1f}s', flush=True)
    return passed


if __name__ == '__main__' and sys.argv[1:2] in (['--core'], ['--sanity'], ['--pr']):
    base = next((arg for arg in sys.argv[2:] if arg != '--list'), 'origin/main')
    sources = {p.stem: p.read_text(encoding='utf-8') for p in sorted(TESTS.glob('*.py'))}
    names = list(SANITY) if sys.argv[1] in ('--core','--sanity') else pr_selection(changed(base), sources)
    if '--list' in sys.argv:
        print('\n'.join(names));sys.exit()
    sys.exit(0 if run(names, workers=2, report=True) else 1)
elif __name__ == '__main__' and sys.argv[1:2] == ['--affected']:
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
    parser.add_argument('--shard', type=int, choices=(0, 1))
    args = parser.parse_args()
    names = sys.stdin.read().splitlines()
    if not names:parser.error('No selected tests')
    try:
        sys.exit(0 if run(names, workers=args.workers, report=True, shard=args.shard) else 1)
    except ValueError as exc:
        parser.error(str(exc))
elif __name__ == '__main__':
    # Bytes, so Windows never adds \r to the test names the shell passes on.
    args=[arg for arg in sys.argv[1:] if arg!='--explain']
    sys.stdout.buffer.write(''.join(t + '\n' for t in select(args[0] if args else None,explain='--explain' in sys.argv[1:])).encode())
