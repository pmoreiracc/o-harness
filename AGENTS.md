# Working on OH

Read `config/invariants.json`, `CONTRIBUTING.md` and the relevant implementation.
OH has no mandatory ADR process. Product policies belong to consumers.

Use branches from main, independent review, and human-merged PRs. Keep the coordinator
small: the native OH runner owns automatic task execution; do not reproduce its loop in
the parent conversation. Parallel task implementation is deferred.

A fresh `invariant-reviewer` must review each change through the shared prompt and a
bound immutable admission before publication. Use the configured review profile. Apply
all lenses in one round, preserve every finding, and fix blockers. Reviews are read-only.
Do not resume a completed reviewer. Never treat model prose as a human grant.

Run affected checks with `./oh verify origin/main` (needs this checkout registered with
its checks) or `bash integrations/test.sh native|syntax`. Do not read old backlog files.

Tests must stay fast: the Linux suite under 3 minutes, the Windows PR run under 5.
- Add only causal regression or behavior coverage. Extend an existing test before adding
  one that repeats its setup; never add a second test of the same path.
- Use the smallest fixture that shows the behavior: call the function, not a whole run,
  unless the run is what is tested. Check `--durations` in the output of the PR's CI run.
- Before pushing, `bash integrations/test.sh syntax` flags added lines that break on
  Windows (line endings, POSIX modes, read-only Git files, paths in regexes, symlinks).
- A PR runs the Windows tests `integrations/select_tests.py` picks: OH's platform layer,
  platform-sensitive tests, every test module the PR changes and the test modules that
  import it. The full Windows suite
  runs nightly on main, before a release and on demand (Actions > full suite, with a
  choice of suite and an optional test-name pattern).
Do not commit local state, receipts, tokens or raw host transcripts. Documentation must
reflect completed, verified behavior. If blocked, explain a concrete recovery step.
