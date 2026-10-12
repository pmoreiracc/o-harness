# Working on OH

These instructions guide development of OH itself. Use the product goals below to
evaluate every proposed fix or improvement to OH.

Read `config/invariants.json`, `CONTRIBUTING.md` and the relevant implementation.
OH has no mandatory ADR process. Product policies belong to consumers.

For workflow changes, use the golden reference in `my-geoffrey` at tag
`harness-before-separation` (`b508bdc`) as a strong reference point. Consult the relevant
skill and supporting scripts before redesigning a working flow. Prefer its proven approach
when it fits OH's goals; explain a concrete reason when departing from it. Its implementation
and Geoffrey-specific policies are not requirements for OH.

## Product goals and experience

OH helps independent developers turn an idea into code they can confidently ship,
with less supervision than prompting an agent directly. Approved work should be
easier to complete with OH than with a simple skill.

- **Clear work:** Propose shapes the idea; Design defines scope, ordered tasks and
  acceptance checks; Deliver builds approved designs or bounded quick fixes.
- **Autonomous delivery:** Approved work progresses automatically within its scope.
  Project checks and a fresh independent reviewer establish whether it is ready;
  blocking findings are repaired before reviewed work is committed.
- **Minimal interruption:** Routine failures are repaired within existing authority.
  The developer should not need to repeat valid commands, manage agents or debug OH.
  Questions belong to real decisions, missing authority or unavoidable external actions.
- **Useful visibility:** Show meaningful transitions and short results: what changed,
  what was checked, what review found and what remains unresolved. Repeating unchanged
  status does not improve confidence.
- **Human control:** Scope stays fixed. The developer controls further allowances and
  publication, and decides what ships. Agent claims never substitute for human approval.
- **Natural fit:** Support Claude and Codex through existing subscriptions across
  macOS, Linux and Windows. Respect each project's standards and keep OH configuration
  outside consumer repositories.

Judge changes by the complete developer workflow, not by what makes an isolated test pass.
Do not weaken useful production behavior just to accommodate a local test setup.
Explain changes through what the developer will see or do, with a brief before/after example
when useful; internal mechanism names alone do not explain the behavior.

## Development workflow

Use branches from main, independent review, and human-merged PRs. Keep the coordinator
small: the native OH runner owns automatic task execution; do not reproduce its loop in
the parent conversation. Parallel task implementation is deferred.

Reliable execution with minimal interruption is a development requirement on both Claude
and Codex, across macOS, Linux and Windows. Reuse the working host entry paths and shared
runner; prefer the smallest complete fix over new machinery, abstractions or approval gates.

Handle routine recoverable failures automatically within the existing authorization:
preserve valid commands and choices, repair what OH owns, and retry with a short bounded
wait when host evidence is still being saved. Do not make the person retype a valid command,
restart a session or debug OH's internals when OH can recover itself. Ask only for a real
decision, missing authority or an external action OH cannot perform. Keep existing authority
and review guarantees; recovery never invents approval, broadens scope or renews allowances.
An unavoidable blocker must explain what happened and give a concrete next step.

For OH host-interaction fixes, implement and verify locally, then let the developer rebuild
with `oh-dev on` and test the snapshot before independent review or publication. Use short,
concrete host scenarios and fix the observed behavior before requesting review. This ordering
is for developing OH, not an extra gate in a consumer's delivery workflow.

A fresh `invariant-reviewer` must review each change through the shared prompt and a
bound immutable admission before publication. Use the configured review profile. Apply
all lenses together in each review round, preserve every finding, and fix blockers.
Reviews are read-only.
Do not resume a completed reviewer. Never treat model prose as a human grant.

Run affected checks and syntax with `./oh verify origin/main` (needs this checkout
registered with its checks), or run `bash integrations/test.sh affected origin/main`
and `bash integrations/test.sh syntax`. Use `bash integrations/test.sh native` when
the full behavioral suite is needed. Do not read old backlog files.

Keep tests as fast as practical while preserving required behavioral coverage. Avoid runtime
regressions and use measured durations to find unnecessary work; there is no fixed time limit.
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
