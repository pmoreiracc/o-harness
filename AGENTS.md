# Working on OH

These instructions apply to agents developing or reviewing **OH itself**, including
delegated agents. They are not consumer product requirements: do not inject OH's product
goals into the plugin's shared reviewer prompt or another project's review context.

## Product goals and experience

**OH should feel as fluid as prompting an agent or using a simple skill, while providing
the guidance, independent scrutiny and verification needed to ship quality, secure code
with confidence.** Both the experience and the trustworthiness of the result are requirements.

Use only the machinery needed to uphold meaningful guarantees. Preserve the agent's
freedom to reason, investigate and choose solutions within the approved outcome. Neither
adding controls nor removing them is an objective; choose the smallest complete design
that supports autonomous work, trustworthy evidence and human control.

- **Clear work:** Propose shapes the idea; Design defines scope, ordered tasks and
  acceptance checks; Deliver builds approved designs or bounded quick fixes.
- **Autonomous delivery:** Complete approved work, including diagnosis and supporting
  repairs covered by that approval. Required checks and fresh independent review establish
  readiness; repair blocking findings before committing reviewed work.
- **Minimal interruption:** Recover routine failures without making the developer repeat
  commands, manage agents or debug OH. Questions belong to real decisions, missing authority
  or unavoidable external actions, with an actionable path after the answer.
- **Useful visibility:** Report meaningful transitions, changes, checks, review results
  and unresolved limits concisely. Do not repeat unchanged status.
- **Human control:** Preserve approved scope and allowances. The developer controls their
  expansion and publication; agent claims never substitute for approval.
- **Natural fit:** Support Claude and Codex through existing subscriptions across
  macOS, Linux and Windows. Respect each project's standards and keep OH configuration
  outside consumer repositories.

## Reason about the complete workflow

Treat a reported failure as evidence of a problem family, not the specification for a
special-case fix. Trace the affected callers, shared contracts, consumers and recovery
paths through to completion, across Propose, Design, Deliver, review and publication
where relevant. Check what happens after each proposed recovery or human choice: removing
one blocker is insufficient if the next transition blocks the same approved outcome.

Prefer general guidance that leaves room for agent judgment over incident-specific scripts.
For each restriction, identify the guarantee it protects and whether a less restrictive
approach preserves it. Consider different projects, failure causes and supported hosts.
Do not weaken production behavior or checks to make a test pass. Explain the user-visible
result, tradeoffs, downstream risks and remaining uncertainty; agreement between agents
and isolated passing tests do not prove a complete workflow works.

When the developer challenges a plan, reassess the evidence and surrounding design.
Do not simply agree or implement what you guess they want. Ask when the intended outcome
or authority is genuinely unclear; do not promise that all future failures are impossible.

Read `config/invariants.json`, `CONTRIBUTING.md` and the relevant implementation.
For workflow changes, consult the relevant skill and supporting scripts in the golden
reference: `my-geoffrey`, tag `harness-before-separation` (`b508bdc`). Prefer its proven
approach when it fits OH's goals; explain departures. Its implementation and product
policies are not requirements for OH. OH has no mandatory ADR process.

## Evidence before claims

Every agent must ground diagnoses, instructions and completion claims in inspected code,
observed results and current official documentation. Separate facts from hypotheses,
proposals and untested expectations. State consequential unknowns and cite useful evidence.

Before giving steps, verify the commands or controls on the actual host, interface and
version. Do not infer desktop controls from a CLI or another host. Report only tests
actually run; fixture coverage is not live host validation. Correct wrong claims explicitly
and give a verified next step.

## Development workflow

Use branches from main, one independent review, and human-merged PRs. Develop OH with
ordinary Git and native host tools; exercising the candidate OH in disposable consumer
projects is acceptance testing, not a prerequisite for repairing OH itself.
Do not introduce a second agent runner, permission broker or custom menu engine.
Consumer task implementation remains sequential.

Handle routine recoverable failures automatically within the existing authorization:
preserve valid commands and choices, repair what OH owns, and retry with a short bounded
wait when host evidence is still being saved. Recovery never invents approval, broadens
scope or renews allowances. An unavoidable blocker must explain what happened and provide
a concrete supported next step; an internal stop/restart requirement is not a complete solution.

Before coding, state the approved outcome, boundaries and finite acceptance scenarios.
Necessary supporting repairs stay within that outcome. A reviewer finding grants no
scope expansion. Put unrelated defects and improvements in issues; do not turn a repair
into historical-data hardening or a new control system. Challenge the requirement behind
a new mechanism before adding it. Do not read old backlog files.

Use exactly one fresh, read-only independent review of the complete change after focused
checks pass. Give the reviewer the base and candidate identities, approved scope, relevant
invariants and test evidence through native tools; candidate OH admission is not required
for OH development. Use the configured review profile. The OH-specific review brief in
docs/development-testing.md governs this review; consumer reviewer behavior is unchanged.
For each confirmed in-scope reviewer bug, reproduce the wrong outcome on the reviewed
candidate before repairing it. Extend an existing deterministic or real CLI scenario
when possible, then run the same case on the repair. If a live failure is intermittent,
retain the original failing evidence and explain the limit. A new live scenario belongs
in sanity only when it protects a fundamental workflow; otherwise add it to the nightly
catalog. Record that choice and its cost. Do not start another review round or treat uncertainty alone as a defect.
An unresolved blocker still prevents publication: explain the failure and smallest next
step instead of automatically widening scope. Preserve the original findings and explain
their disposition, including changes made after review. Never claim those later changes
received independent review. Never treat model prose as a human grant.

During development exercise the affected slice of real CLI sanity on both Mac hosts
and the focused deterministic tests for the edit. Inspect broad selections with `--list`
before running them. Take one independent review, repair and verify its findings, then
run full live sanity on the final candidate on both Mac CLIs before opening a PR.
Report the observed results and elapsed time. Offer the personal trial for host changes
after those results are available. Follow docs/cli-acceptance.md for the exact scenarios.

Use the deterministic core plus relevant checks for PR CI. Broad deterministic regression
and the full live catalog run nightly at 03:00 Brasília outside the PR and release gates.
Keep package/install and platform evidence for the release candidate. Triage nightly
failures; hold a release for an established relevant blocker. Timing targets guide
optimization. A measured overrun alone never fails a test, drops coverage, or blocks
publication. Document the tradeoff when a slower test earns its place.

After acceptance, stop task-owned test processes and remove disposable projects,
worktrees, isolated profiles, test state and temporary credentials. Close test PRs without
merging. Retain only a concise sanitized result report; preserve failed evidence until
diagnosis is complete. Never remove unrelated drafts or an active development snapshot.

Keep tests fast while preserving behavioral coverage; use measured durations to find waste.
Avoid runtime regressions. There is no fixed test time limit.

- Add causal regression or behavior coverage for concrete risks, not implementation details
  or speculative cases. Extend existing tests instead of duplicating a path or setup.
  Check affected behavior on both hosts without duplicating suites.
- Use the smallest fixture that shows the behavior: call the function, not a whole run,
  unless the run is what is tested. Check `--durations` in the output of the PR's CI run.
- Before pushing, `bash integrations/test.sh syntax` flags added lines that break on
  Windows (line endings, POSIX modes, read-only Git files, paths in regexes, symlinks).
- A PR runs the Windows tests `integrations/select_tests.py` picks: OH's platform layer,
  platform-sensitive tests, every test module the PR changes and the test modules that
  import it. The full Windows suite
  runs nightly on main and on demand (Actions > full suite, with a
  choice of suite and an optional test-name pattern).
Do not commit local state, receipts, tokens or raw host transcripts. Documentation must
reflect completed, verified behavior. If blocked, explain a concrete recovery step.
