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

Use branches from main, independent review, and human-merged PRs. OH skills coordinate
fresh native host agents; focused helpers validate scope, evidence and completion.
Do not introduce a second agent runner, permission broker or custom menu engine.
Consumer task implementation remains sequential.

Handle routine recoverable failures automatically within the existing authorization:
preserve valid commands and choices, repair what OH owns, and retry with a short bounded
wait when host evidence is still being saved. Recovery never invents approval, broadens
scope or renews allowances. An unavoidable blocker must explain what happened and provide
a concrete supported next step; an internal stop/restart requirement is not a complete solution.

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
  runs nightly on main, before a release and on demand (Actions > full suite, with a
  choice of suite and an optional test-name pattern).
Do not commit local state, receipts, tokens or raw host transcripts. Documentation must
reflect completed, verified behavior. If blocked, explain a concrete recovery step.
