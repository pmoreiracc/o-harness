# Working on OH

Read `config/invariants.json`, `CONTRIBUTING.md` and the relevant implementation.
OH has no mandatory ADR process. Product policies belong to consumers.

Use branches from main, independent review, and human-merged PRs. Keep the coordinator
small: the native OH runner owns automatic task execution; do not reproduce its loop in
the parent conversation. Parallel task implementation is deferred.

The standard is whether OH helps a developer complete the work with quality.
OH must make approved work easier than prompting an AI directly or using a simple skill.
Reliable execution with minimal interruption is a development requirement on both Claude
and Codex, across macOS, Linux and Windows. Reuse the working host entry paths and shared
runner; prefer the smallest complete fix over new machinery, abstractions or approval gates.
Judge changes by the complete developer workflow, not by what makes an isolated test pass.
Do not weaken useful production behavior just to accommodate a local test setup.
Explain changes through what the developer will see or do, with a brief before/after example
when useful; internal mechanism names alone do not explain the behavior.

Handle routine recoverable failures automatically within the existing authorization:
preserve valid commands and choices, repair what OH owns, and retry with a short bounded
wait when host evidence is still being saved. Do not make the person retype a valid command,
restart a session or debug OH's internals when OH can recover itself. Ask only for a real
decision, missing authority or an external action OH cannot perform. Keep existing authority
and review guarantees; recovery never invents approval, broadens scope or renews allowances.
An unavoidable blocker must explain what happened and give a concrete next step.

A fresh `invariant-reviewer` must review each change through the shared prompt and a
bound immutable admission before publication. Use the configured review profile. Apply
all lenses in one round, preserve every finding, and fix blockers. Reviews are read-only.
Do not resume a completed reviewer. Never treat model prose as a human grant.

Run affected checks with `./oh verify origin/main` (needs this checkout registered with
its checks) or `bash integrations/test.sh native|syntax`. Do not read old backlog files.

Tests must stay fast: the Linux suite under 3 minutes, the Windows PR run under 5.
- Add tests only for a concrete behavior or failure risk; do not test implementation details
  or add speculative coverage. Check affected behavior on both hosts without duplicating suites.
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
