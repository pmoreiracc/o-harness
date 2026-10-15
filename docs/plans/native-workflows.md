# OH native workflows

Status: local implementation and affected checks are complete. On 2026-10-15 the
maintainer explicitly accepted native Stop as a known, non-blocking limitation and
requested [issue #81](https://github.com/pmoreiracc/o-harness/issues/81). It no longer blocks development
activation or release. The maintainer subsequently chose to test the official release
instead of a development snapshot and authorized preparing the PR. Independent
review and required checks remain required; merge and release stay human-controlled.
Earlier Stop-blocking decisions in the execution history below are superseded by
this decision, not erased from the record.

## Objective and decisions

Make OH primarily skills and focused validation helpers. Claude and Codex launch
fresh agents, run tools and enforce their native permissions. OH preserves approved
scope, task/review allowances, independent review, evidence and human publication.
The golden reference is `my-geoffrey@harness-before-separation` (`b508bdc`): use its
skill-led workflow and result validation, not its product policies or exact-command
transcript machinery.

- Fresh implementation and review agents; sequential consumer task execution.
- Configured model and effort passed explicitly; difficulty remains outside designs.
- Implementers use host permissions. No OH permission broker, unrestricted command
  proxy, replacement process supervisor or headless fallback runner.
- Native reviewers are instructed not to edit. Changed subjects invalidate receipts.
  This is not OS-enforced isolation and cannot detect an edit subsequently reverted.
- Retain independent final-candidate review and family repairs. Only a repeated
  blocking family in two reviewer receipts triggers implementation escalation.
- Distinguish parent interruption from cancellation of owned native work. Do not start
  conflicting checks, reviews or completion while an owned child remains active.
  Track the observed cancellation limitation in issue #81 without blocking release
  or adding workaround machinery.
- Configuration, evidence and receipts stay outside consumer repositories.

## Native questions, not an OH menu engine

Skills directly use Claude `AskUserQuestion` or Codex's available native question
tool for real decisions. Claude quick-fix scope approval uses the native plan viewer's
single Accept action, without a second question. Preserve the actual accepted scope.
Keep a direct typed-reply fallback when the native question surface is unavailable.

Remove generated question payloads, `choose`, exact option-wording comparison,
menu polling, visible OH gate identifiers and runtime-directed conversation/display
protocols. Keep only the native human decision provenance, the scope/attempt/head
it concerns, its effect and consumption identity for consequential approvals.
Routine clarification needs no durable gate. Silence and model claims grant nothing.

## Ordered work and completion conditions

- [x] 1. Preserve the starting checkout and classify existing changes.
  Starting branch: `codex/harness-refactor`; base: `b8c633c`.
  A binary tracked patch and recovery manifest were saved externally before edits.
  No untracked files existed. See the execution record below.
- [ ] 2. Track native delegation and Stop validation (non-blocking issue #81).
  Use disposable fixtures: fresh context, actual model/effort, native permissions,
  attributed results, Stop during delegated work and checks. Prove parent Stop
  cancels children; joining a child is not proof. Test supported Codex Desktop/CLI
  and Claude terminal/Remote Control paths. Record each tested surface honestly.
  Remaining Stop validation is follow-up work and does not block activation/release.
- [x] 3. Settle focused helper contracts and adapt the shared test fixture.
  Reuse existing journal/storage, scope, admission, verification, completion and
  publication primitives. Helpers return facts/refusals, not `next_action` agent
  dispatch, prompts, conversational menus or observer loops.
- [x] 4. Implement native skills and helpers with GPT-6.1 Sol/high workers.
  Set disjoint ownership before parallel edits. Workers are not alone and must
  preserve other changes. The supervisor challenges each phase against this plan.
- [x] 5. Integrate, migrate historical readers and delete obsolete machinery.
  No parallel legacy execution engine. Preserve original evidence and allowances.
- [ ] 6. Validate the integrated PR candidate and document measured results.
  Run affected/syntax checks and obtain fresh independent review before the PR.
  Platform CI remains required. Per the latest maintainer decision, the workflow
  trial will use the official release rather than a development snapshot.

Dependencies: 3 settles contracts before parallel work in 4; 5 follows integration
in 4. Stop follow-up in 2 is non-blocking. Do not check an item complete
on an agent's claim alone.

## Target responsibilities

Skills own selection, sequential native delegation, recoverable repair and native
questions. Use Codex agents with `fork_turns: none` and explicit model/effort, avoiding
additional installed user roles. Claude uses packaged named non-fork agents with
explicit model/effort. Send a bounded current packet, not conversation history.

Helpers own scope/task admission, review-window accounting, native child/result
attribution, verification records, immutable reports, reviewed completion and
publication reconciliation. Admit a review before spawn; bind its child ID after
spawn returns. Retain and charge failed/uncertain launches exactly once. Never reuse
a completed reviewer or overlap implementation and review in the same checkout.

Keep approved scope as an external immutable snapshot, rather than locking every
planning file. Permit required living-document changes. Check structural task and
completion history mechanically; independent review assesses semantic scope drift
against the original. Prepare provisional task marks/lifecycle changes before final
checks and review. They are candidate content, not completion authority. Commit the
exact reviewed candidate; select subsequent tasks from external completion records.
The last task's review covers the accumulated branch and task interactions without
adding an obligatory extra final-review stage.

Keep complete original reports and the minimum identity, candidate, findings and
outcome metadata. Do not demand repeated regeneration into rigid prose schemas.
Preserve every finding and distinguish author repair claims from reviewer closure.
Supplementary measurements are ordinary hashed evidence references in both packets;
attachment is neither approval nor automatic proof. Standalone review requires no
exact-command authority matching and grants no repair/completion authority. Repairs
use the existing bounded quick-fix approval, including original unreviewed changes.

Publication permission binds reviewed head and destination. Reuse existing PRs;
failed discovery never grants permission to create another. Preserve ordinary scope,
concern and allowance decisions without reconstructing custom menus around them.

## Existing work disposition

| Existing changes | Disposition |
| --- | --- |
| Native Claude plan viewer and one accepted scope | Retain behavior; integrate native acceptance, supersede duplicated display/menu protocol |
| Fresh request replaces unused preparation | Retain behavior and causal coverage; integrate simpler entry path |
| `authority.py`, `gates.py`, `cli.py`, `workflow.py` plumbing | Integrate consequential decision/evidence checks; supersede runner/menu/exact-command plumbing |
| `prepared.py`, launcher version/activation safeguards | Integrate supported historical adoption and interrupted activation protection |
| `test_authority.py`, `test_gates.py`, `test_plugin_transitions.py` changes | Retain behavior coverage; adapt/remove assertions about superseded mechanisms |
| Delivery/shared skill instructions | Supersede execution/menu protocol; retain scope, one approval and native display behavior |
| Usage documentation and prior correction plan | Retain historical validation; update current behavior only after verification |

Extract and retain useful code from runner/hosts/design-runner before deleting custom
agent launching, stream handling, worker check proxying and phase scheduling. Keep
process utilities only for checks/services that still need them. Reuse packaging and
external settings. Telemetry remains passive: correlate available native child usage,
avoid inclusive-parent double counting and label missing data unknown. Add no pricing
or observation infrastructure merely to fill gaps.

## Test audit and acceptance

Adapt the shared workflow fixture to fake native delegation with real helper
admission/results. Extend existing tests first. Delete tests exclusively enforcing
removed subprocess flags, worker stream protocols, menu strings and scheduler internals.
Retain causal scope, authority, evidence, completion and platform checks. No target
test count, duplicated host suites or repeated full-suite runs after small edits.

Required scenarios:

- Propose → Design → Deliver; bounded quick fix; multiple tasks with bounded context.
- Docker/network checks and additional experiments through native permissions.
- Required roadmap prose updates without changing approved scope.
- Standalone review after stopped delivery, natural language and slash invocation.
- Check failures, imperfect reports, family repairs and spent review windows.
- Reviewer mutation, stale verification/review and unauthorized scope changes.
- Parent Stop during implementation/check/review; no surviving owned work or later
  completion; fresh-session and cross-host resume preserve grants and findings.
- Interrupted completion/publication; existing PR reconciliation.
- Native plan approval and other native questions with no duplicate scope gate.
- Native usage deduplication and honest unknown counters.

Measure elapsed time, observed tokens, review rounds, missed defects and unnecessary
interruptions. Neither fewer findings nor fewer lines of code alone proves quality.

## Compatibility and rollout

Adopt unfinished legacy work only at quiescent boundaries, preserving original scope,
completed commits, evidence and consumed allowances. Reuse matching verification and
review when possible. Do not migrate beneath a live legacy worker. Retain historical
readers, not a second executor. Published cycles remain terminal. Work completed
outside OH (including the recent task-12 delivery) must not be reopened or relabelled
OH-reviewed. Validate snapshot adoption explicitly; refreshing dev alone is insufficient.

Before publication: integrated affected checks and fresh independent review of the
actual OH change. The maintainer chose an official-release workflow trial instead
of the earlier development-snapshot prerequisite. Fix blockers and obtain fresh
review after changes. The observed Stop limitation is accepted as non-blocking;
other unverified capabilities must still be reported honestly. Monitoring of consumer
sessions remains paused.

## Execution record

- 2026-10-15: recovery copy saved at `/private/tmp/oh-native-workflows-start-20261015T094717Z`.
  Patch SHA-256: `d8d99f5ad1d5f1f461a3d1aa8f0bcb184f2cd6a3b66ac185e29eacebd2e0ac20`.
  This path identifies a local recovery artifact, not a deliverable or consumer file.
- 2026-10-15: Codex CLI 0.161.0, interactive terminal, GPT-6.1 Sol/high parent and
  fresh native child: **FAIL**. The child started a bounded 45-second Python command
  at 09:50:52.684 UTC. Parent Ctrl-C produced native `turn_aborted: interrupted` at
  09:51:24.607 UTC. The child nevertheless wrote its completion marker at
  09:51:37.690 UTC, about 13 seconds after the recorded interruption, and finished
  normally. The fixture process exited and the idle parent terminal was closed.
  Sanitized evidence: `/private/tmp/oh-native-stop-codex-20261015/observation.json`.
- 2026-10-15: Claude Code 2.1.296 terminal Ctrl-C, named fresh native Haiku child:
  **PASS for the bounded scenario**. A 20-second delayed Bash write was cancelled
  before its marker; native cancellation, process exit and marker absence beyond
  the deadline were observed. Sanitized evidence and limitations:
  `/private/tmp/oh-native-stop-claude-20261015T095012Z/evidence.json`.
- Neither result establishes Desktop Stop-button or Claude Remote Control behavior,
  nor cleanup of detached/Docker workloads. The Codex terminal failure is sufficient
  to leave prerequisite 2 incomplete. Do not introduce a cancellation supervisor.
  Next step for rollout: confirm a supported native cancellation behavior/fix, then
  rerun this same probe before activation or publication.
- 2026-10-15: user answered "Yes" to implementing now while retaining the native
  Stop block on development activation and publication. This authorizes migration
  work, not a Stop workaround or a weaker published Stop guarantee.

### Integration progress (not yet validated as complete)

Native skills and four packaged Claude roles are implemented; Codex uses native default
agents. The MCP bridge exposes focused scope, attempt, evidence and completion helpers.
The old question endpoints, active prompt hook, menu hook and legacy executor routing
have been removed. Historical journals remain inputs to the current reader.

Packaging checks passed for both hosts; the shared-core packaging case took 1.020s.
The independent integration/configuration/selector group passed 36 checks in 6.883s
(one skip). These results do not establish end-to-end readiness. Integrated native
fixtures are still being repaired and expanded to preserve the previous protections.
The first syntax pass identified Windows newline/path fixture issues, being corrected.

Supervisor review found and assigned corrections for exact question/child attribution,
cancelled results being mistaken for completion, duplicate private proposal approval,
provisional future-task completion, request idempotence and oversized task packets.
None of these is accepted as an activation exception.

### Coverage map being validated

| Protection | Existing test module adapted | Status |
| --- | --- | --- |
| Exact native scope approval and immutable accepted plan | test_workflow, test_gates | Passed local affected/targeted checks |
| Task/review windows, repeated blocking families, interrupted commit | test_workflow | Passed local affected/targeted checks |
| Missing/stale checks and reviewer mutation | test_workflow | Passed local affected/targeted checks |
| Fresh native child, actual profile, cancellation and question attribution | test_authority | Passed local affected/targeted checks |
| Living roadmap prose, preserved task structure, provisional final candidate | test_design_adapter | Passed local affected/targeted checks |
| Proposal acceptance, private design acceptance, private lineage | test_planning, test_delivery, test_private | Passed local affected/targeted checks |
| Legacy adoption, terminal publication, scope/concern decisions | test_workflow | Passed local affected/targeted checks |
| MCP mapping, packaging, platform safety | test_mcp_server, test_installation, test_windows | Passed locally; 12 platform skips |

Tests solely specifying the removed scheduler, generated menus, custom subprocess flags
and streaming protocol are superseded. Substantive authority and evidence protections
are obligations until replacement cases pass; deleting their former fixture does not
satisfy this plan.

- Integrated native group: 42 checks in 61.336s; 35 passed, 3 errors and 4 failures.
  The failures exposed missing milestone/private-lineage protection as well as fixture
  and interface mismatches. Restore protections and rerun the failing cases; this is
  not a passing acceptance result.
- Focused MCP group: 7 passed in 2.176s. Existing subprocess timeout/cleanup group:
  5 passed in 1.697s, outside the sandbox for inspection of its disposable processes.
- Auxiliary affected group: 65 checks in 8.484s, 11 Windows-specific skips; it exposed
  a leftover development builder reference to the removed gate hook. That reference
  and the obsolete installation tool-name expectation were corrected; packaging
  confirmation remains pending.
- Dashboard AI analysis depended on the removed headless executor. This candidate
  explicitly disables that action instead of retaining a second executor. Historical
  analytics and saved suggestions remain readable. Isolated desktop/narrow preview
  showed the disabled action and saved data, with no model request or page errors.
- Approval audit added causal coverage for negative replies, one combined
  concern/scope decision, ordinary Stop/Pause without internal file-path wording,
  and child terminal-event ordering. These are unresolved until the integrated
  checks confirm the corrections. No live consumer or dev activation was performed.


## Local implementation result

Steps 3–5 are complete locally. Step 2 and the host-trial/release portion of step 6
remain open. No development snapshot was enabled, no consumer files changed, and
nothing was pushed or published. The existing snapshot remains selected.

The frozen affected selection exercised 23 modules / 238 cases on macOS, with 12
Windows-only skips. The first integrated selection took 83.92s. Its failures were
corrected and verified through focused reruns (22 cases / 9.249s; 3 cases / 8.979s;
controls / 1.859s). Linked Codex skill controls then passed the existing extended
case in 2.603s. Syntax and whitespace checks passed. These are combined affected
and causal-rerun results, not a claim that the initial full run was clean.

Preserved protections include scope/approval identity, task and review windows,
private plan lineage, milestone dependencies, family escalation, stale checks,
reviewer mutation, provisional completion, concern/scope decisions, existing PR
reconciliation, interrupted result/commit recovery, quiescent legacy adoption and
native child provenance. Only removed executor/menu/proxy mechanics lost their
behavioral tests. Full original receipts and findings remain retained.

Both host packages built in isolated tests. The disabled dashboard analysis action
was checked at desktop and narrow widths with fake saved data. Real saved Claude
successful native-child metadata confirmed the supported synchronous result shape;
this was read-only evidence inspection, not a new end-to-end host trial. Native
usage that is unavailable stays unknown; no token-saving claim is made.

Remaining release work: obtain a fresh independent review and complete required PR
checks. The maintainer chose the official release for their workflow trial instead
of a development snapshot. Native Stop follow-up remains non-blocking in issue #81.
Do not introduce a replacement cancellation supervisor.

Final reference correction: the two existing standalone/legacy scenarios passed in
5.340s. Standalone review carries no scope-approval claim; adopted legacy work links
its unchanged original `000001.json` provenance instead of a nonexistent new approval
file. Final syntax and whitespace checks passed after this correction. All workers
are finished; no known local-check failure remains. Host trials and independent
release review are still pending as stated above.

### Actual Desktop Stop probe — 2026-10-15

The developer clicked Stop in disposable Desktop parent task
`01a13f38-392f-7e81-95e4-dbe772ea73b1`. Its native turn was interrupted at
11:00:36 UTC. Native child `01a13f38-57d3-7440-bc0b-09a521f9b4cf` continued
running the foreground timestamp probe, reached its natural deadline at
11:03:24.732 UTC (168.7 seconds after parent Stop), and completed with exit code 0.
This is an observed Desktop cancellation-propagation failure, not an inference from
CLI Ctrl-C or a short cancellation delay. The probe is finished; no consumer
repository or dev activation changed.

Computer Use could not operate Codex, so the developer performed the actual click.
A later explicit cleanup message was rejected by automatic approval review; no
workaround was attempted and the bounded command finished naturally. Sanitized
evidence: `/private/tmp/oh-desktop-stop-20261015T1059/observation.json`. Native Stop
remains a rollout blocker. Next step: report/verify the native parent-to-child
cancellation behavior and retest a supported fix; do not add an OH supervisor.

### Maintainer decision — native Stop is non-blocking

After the Desktop result, the maintainer requested recording it as a GitHub issue
and explicitly said Stop must not block release. Created [issue #81](https://github.com/pmoreiracc/o-harness/issues/81)
with sanitized reproduction, observations and follow-up criteria. No raw transcripts
or local private paths were published. Updated active usage, architecture, installation
and plan guidance accordingly. No runtime safeguards were weakened, no cancellation
workaround was added, and no dev activation or publication was performed by this change.

### Maintainer decision — official-release trial and PR

The maintainer requested publication through a PR and chose to test the official
release instead of the development snapshot. This supersedes the developer snapshot
trial prerequisite for this change, without claiming that trial occurred. Prepare the
PR with fresh independent review and required checks. Preserve human merge/release
control and disclose the known Stop limitation and disabled dashboard AI analysis.

### Independent PR review — round 1

A fresh configured GPT-6.1 Sol/high invariant reviewer validated a bound immutable
admission for the complete main-to-candidate range ending at `7853dd6`. The exact
committed candidate passed all 23 affected modules and syntax checks before review.
The review nevertheless found seven concrete blockers and one documentation concern:

1. Native question/plan answers could remain usable after superseding cancellation.
2. Failed packet construction could strand an unfinished, never-launched admission.
3. Completed standalone feedback hid the original delivery from Resume.
4. Mixed blocking/scope findings could leave scope unresolved through completion.
5. Issue references differed between native decisions and the PR renderer.
6. Earlier-task corrections confused the original corrected commit with current parent.
7. Existing-PR corrections omitted review coverage for original manual commits.
8. Two current documentation passages still described Stop as blocking release.

The original receipt is preserved externally. Repairs extend existing causal scenarios
through the failed downstream transitions, without weakening publication/authority
checks or introducing gates. Actual receipt ingestion additionally exposed inline
Family/Relation metadata being conflated; fix that parsing family while preserving
the original report. A fresh review of the repaired candidate is required before PR.

Round-1 repairs: newer human input now invalidates unconsumed native answers while
already-consumed replay remains read-only; admission artifacts are built before the
atomic admission transition; completed feedback yields to the original delivery on
Resume. Scope portions can be disposed independently of blockers, and all retained
scope occurrences require disposition before completion. Publication accepts current
and historical issue references and historical design dismissals. Corrections bind
both the original corrected task and current reviewed parent; existing-PR intake binds
original manual commits into approved scope, review packets and completion evidence.
Readable inline Family/Relation metadata is normalized without rewriting originals.
Current Stop documentation now consistently reflects the non-blocking decision.

Validation after repairs: all 23 affected modules / 238 selected cases passed in
96.88s on macOS, with 12 platform-specific skips. The historical-design-dismissal
extension passed its existing scenario in 3.850s. Syntax and whitespace checks passed.
No new test cases or suites were added; existing scenarios now reach the previously
failing downstream transitions. These repairs still require fresh independent review.
