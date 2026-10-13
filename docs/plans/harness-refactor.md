# OH harness refactor

Status: handoff correction and local host acceptance passed; awaiting the developer's new Desktop trial.
Branch: `codex/harness-refactor`. Independent review and publication remain pending.

## Objective and fixed decisions

Deliver one coherent improvement to quality, continuity and user experience while retaining
fresh agents, model selection, subscription access and the existing safety foundations.
The golden reference is `my-geoffrey` at `harness-before-separation` (`b508bdc`): its skills,
readiness contract, completion controls, readable receipts and review history are the reference.
Keep OH's native shared runner and external storage instead of copying Geoffrey's product policy.

Difficulty assessment belongs entirely to OH's runtime and external records. Consumer designs
contain project requirements, tasks and acceptance checks, with no model or effort recommendations.
A fresh read-only assessment on the configured standard profile precedes each new Deliver task.
The assessment is reused for the task's repairs and resumes. Only the same blocking family in two
independent review receipts escalates implementation. Failed checks never escalate or create a gate.

Implementation follows the ordered tasks below. Check a task off only after its completion
condition and affected checks pass. Record evidence and deviations here. Do not commit raw
transcripts, receipts, tokens or local run state.

## Ordered tasks

### Desktop-trial correction — ordered implementation and acceptance

The 0005 trial proved Stop (about 1.1 seconds) and retained-work continuation, but exposed
two finding identifiers presented as `id`. Thirteen completed author reports used the case
hash while validation expected the receipt reference. OH classified rejected handoffs as
unfinished code, producing repeated implementation and checks. Real-host acceptance had
never exercised repair after a blocking review; mock reports used the validator's own helper.
Tasks 3, 5, 6 and 7 below are reopened for these affected conditions. Task 8 remains pending.

The golden reference's current semantic review reader preserves recognizable findings despite
presentation anomalies; its strict receipt parser is historical compatibility code. Retain
OH's substantive evidence requirements and structured tools, not that historical parser.
There is no report-correction agent, new consumer gate, configuration or service.

- [x] **C1. Canonical finding references.** Version 3 packets use receipt references as the only
  finding IDs; grouping hashes become `case_key`. Return exact validation errors. Keep v2 readers.
- [x] **C2. Native report submission.** Both active agents submit through the existing worker
  connection. Validate role, subject, evidence and report; retain submissions externally and
  revalidate the latest submission on exit. Final prose is not another authoritative report.
- [x] **C3. Conservative review interpretation.** Preserve recognizable findings and uncertain
  fragments independently of metadata validity. Never infer clean, family identity or approval.
- [x] **C4. Accurate execution and visibility.** Invalid author reports cannot restart implementation.
  Incomplete reviews retain findings and use existing fresh-review authority. Report failures
  immediately; retain factual periodic progress, scope decisions, Stop and review allowances.
- [x] **C5. Compatibility and paused continuation.** Convert only unambiguous v2 case IDs, preserving
  original reports; reuse only exact verified work. Explicit Deliver may adopt a settled paused
  run in the selected runtime without changing its grants. Keep actual 0005 paused and untouched.
- [ ] **C6. Regression and host acceptance.** Extend current fixtures across both roles, invalid
  submissions, repeat findings, stale evidence, Stop and upgrades. Derive fixture IDs independently.
  Run affected checks/syntax with durations. Exercise seeded blocking review → real repair → fresh
  review twice per host; record time, observed tokens, calls, checks and interruptions. A first-round
  clean result does not satisfy the repair trial. Build a candidate for the developer's Desktop
  trial before independent OH review and human-merged publication.

Each item is checked only after its affected checks pass; evidence is recorded here. Immutable
consumer evidence stays external. No consumer code or requirements are changed by this correction.

### Original refactor tasks

- [x] **1. Preserve and organize today's work.** No dependencies.
  Create the requested branch from the current checkout and preserve the existing patch and
  untracked worker-checks module. Classify every existing change as retain, integrate or supersede.
  Retain implementer-owned checks, protected plans, reviewed completion, Stop/resume, scope
  protection and the escalation rule. Commit logical verified changes with the refactor.
  **Done when:** every starting change has an explicit disposition and a recoverable starting point.
  **Evidence:** base `fc78ae06f85bd794c3cc073c8ba3c3907d0a5458` equals local main and origin/main;
  branch created without discarding edits. Recovery copy is outside the checkout at
  `/private/tmp/oh-harness-refactor-20261012T160539Z` (binary patch, worker module and hashed manifest).

- [x] **2. Audit tests before expanding coverage.** Depends on 1.
  Inventory modules by behavior, shared fixtures and execution cost. Map tests to retain, improve,
  consolidate or delete and explain the protection remaining. Replace tests for growing report
  bundles and design-authored difficulty. Remove obsolete behavior and incidental assertions when
  no distinct protection is lost. Extend existing fixtures first; add only concrete uncovered cases.
  Run affected checks and inspect durations; avoid repeated full-suite runs.
  **Done when:** the coverage/disposition map and baseline affected-check results are recorded.

- [x] **3. Replace accumulating history with a current task packet.** Depends on 2.
  Introduce a versioned internal packet for approved scope/references, current and remaining work,
  verification references and all finding dispositions. Readiness explicitly covers requirements,
  rules, affected surfaces, proof, self-review, family closure, prior findings, verification and limits.
  Reviewers consume the latest readiness and a compact complete finding index. Retain earlier
  reports by reference without mandatory rereading. Bind packets to task/repository state; preserve
  original evidence. Missing readiness returns to the implementer within existing authority.
  Native verification and independent review remain required; author claims grant nothing.
  **Done when:** more attempts do not grow the mandatory report bundle and every finding is traceable.

- [x] **4. Add fresh runtime difficulty assessment.** Depends on 3.
  Before each new Deliver task, use the configured standard profile for one read-only assessment
  of approved scope, relevant code and referenced contracts. Return difficulty, rationale, examined
  references and uncertainty. Local bounded edits are simple; ordinary contained changes standard;
  cross-cutting changes, consequential boundaries and substantial uncertainty complex.
  Use an explicit assessment role, retain its evidence externally and count its time/tokens in task
  totals. Reuse its initial selection for repairs/resume. Remove difficulty from design generation
  and ignore old document annotations for new work without editing approved documents.
  Already-started tasks retain their recorded selection and all review allowances.
  **Done when:** new runtime selection needs no consumer metadata or repeated assessment calls.

- [x] **5. Consolidate workflow decisions.** Depends on 4.
  Derive execution, status, menus and resume from one next-action function over recorded state and
  validated evidence. Preserve Propose/Design approvals and concern/scope decisions. In Deliver,
  repair implementation/check failures before asking for allowance when the next review is ready.
  No routine Retry/recovery approval. Real external obstacles name their cause and next action.
  Stop cancels owned work and fences subsequent checks/reviews/commits. Resume preserves useful
  implementation, findings and consumed allowances; scope never expands silently.
  **Done when:** execution and displayed next action agree in normal, interrupted and resumed runs.

- [x] **6. Restore readable receipts and organized PR descriptions.** Depends on 5.
  Add deterministic Markdown requests/receipts and a run index organized by task and review round,
  alongside the authoritative structured evidence in OH's external storage. Include task, branch,
  reviewed state, reviewer, elapsed time, outcome, findings and evidence. Findings name the
  rule/reference, location, concrete failure and proposed correction. Original receipts are immutable;
  current dispositions link back to their evidence. No extra summarizing model call.
  PRs have a short whole-change summary, completed tasks, verification, review outcome, stop reason
  and expandable complete review history. Preserve findings and human decisions, mark unavailable
  historical fields honestly, and keep raw transcripts and private local paths out of publication.
  **Done when:** receipts/PRs are readable, complete and traceable.

- [ ] **7. Unify the visible host experience.** Depends on 6.
  Shorten shared workflow instructions around runtime decisions. Report actual transitions and
  factual progress about every three to four minutes during long phases. Separate historical
  failures from current unresolved problems. Use one trusted native publication question naming
  branch, destination and PR target; retain it across recovery. Reuse existing PRs and completed
  work. Preserve host-required permissions; suppression of host-imposed citations is not promised.
  **Done when:** the known publication path needs no redundant OH decision and current status is accurate.
  **Evidence:** native publication-question/destination tests, current-failure projection, repeated
  public-focus timing, immutable recovery and both-host live Deliver trials passed. Actual Desktop
  permission handling and Stop remain part of the developer's integrated trial in task 8.

- [ ] **8. Validate, consolidate and prepare publication.** Depends on 7.
  Complete the test audit, remove superseded paths/tests, and document only verified behavior.
  Read older receipts and stopped runs without rewriting approval or resetting allowances.
  Build one integrated development candidate, then the developer tests the snapshot, a fresh
  independent reviewer reviews the final change, and a PR is prepared for human merge.
  **Done when:** automated checks, live-host acceptance, developer trial and independent review pass.

## Acceptance checks and measurements

Use small synthetic consumer repositories, extending existing fixtures. Exercise:

1. Propose → refine → Design → Deliver without harness difficulty in generated designs.
2. Multiple consecutive tasks with bounded coordinator context.
3. Failed checks, defective tests, repeated families and newly exposed defects.
4. Missing/stale verification, edited approved plans and premature task completion.
5. Stop during implementation/review, fresh-session resume, interrupted completion/publication.
6. Historical receipts and stopped runs retaining evidence and authority.
7. Readable receipts/PRs retaining findings, decisions and whole-change summaries.

Run targeted automated checks on supported platforms. Exercise real Claude and Codex agents on
clean and defective fixtures twice per host; test Desktop Stop and publication through actual
host paths. Record tokens per completed task (including assessment/repairs), elapsed time, review
rounds, missed defects and unnecessary interruptions. Unknown observations stay unknown.
Quality and authority checks must pass; savings must be measured, not assumed.

The developer's integrated host trial precedes independent review/publication, as AGENTS.md
requires. New consumer gates, configuration files and production services are out of scope.

## Starting-change dispositions

The table below covers the carried patch and new file. Retain means preserve its behavior;
integrate means preserve its intent through the redesigned contract; supersede means replace
the implementation, keeping any distinct behavioral protection.

| Starting path | Disposition |
|---|---|
| `AGENTS.md` | Retain |
| `CLAUDE.md` | Retain |
| `config/defaults.json` | Retain |
| `docs/architecture.md` | Integrate |
| `docs/configuration.md` | Integrate |
| `docs/installation.md` | Integrate |
| `docs/usage.md` | Integrate |
| `plugins/o-harness/scripts/oh` | Retain |
| `plugins/o-harness/skills/oh-deliver/SKILL.md` | Integrate |
| `plugins/o-harness/skills/oh-design/SKILL.md` | Integrate |
| `plugins/o-harness/skills/oh-propose/SKILL.md` | Integrate |
| `plugins/o-harness/skills/oh-start/SKILL.md` | Integrate |
| `prompts/invariant-reviewer.md` | Integrate |
| `runtime/oh/authority.py` | Retain |
| `runtime/oh/checks.py` | Retain |
| `runtime/oh/cli.py` | Integrate |
| `runtime/oh/config.py` | Integrate |
| `runtime/oh/controls.py` | Retain |
| `runtime/oh/delivery.py` | Integrate |
| `runtime/oh/delivery_verify.py` | Retain |
| `runtime/oh/design_adapter.py` | Retain |
| `runtime/oh/gates.py` | Integrate |
| `runtime/oh/hosts.py` | Integrate |
| `runtime/oh/mcp_server.py` | Integrate |
| `runtime/oh/processes.py` | Retain |
| `runtime/oh/publication.py` | Supersede summary assembly; retain publication evidence |
| `runtime/oh/runner.py` | Integrate |
| `runtime/oh/suggestions.py` | Integrate |
| `runtime/oh/test_analytics.py` | Integrate |
| `runtime/oh/test_config.py` | Integrate |
| `runtime/oh/test_controls.py` | Integrate |
| `runtime/oh/test_delivery.py` | Integrate |
| `runtime/oh/test_design_adapter.py` | Integrate |
| `runtime/oh/test_gates.py` | Integrate |
| `runtime/oh/test_integration.py` | Integrate |
| `runtime/oh/test_mcp_server.py` | Integrate |
| `runtime/oh/test_plugin_transitions.py` | Integrate |
| `runtime/oh/test_system.py` | Integrate |
| `runtime/oh/test_windows.py` | Integrate |
| `runtime/oh/test_workflow.py` | Integrate |
| `runtime/oh/verification.py` | Retain |
| `runtime/oh/workflow.py` | Integrate |
| `workflows/deliver/SKILL.md` | Integrate |
| `workflows/design/SKILL.md` | Integrate |
| `workflows/oh/SKILL.md` | Integrate |
| `workflows/propose/SKILL.md` | Integrate |
| `runtime/oh/worker_checks.py` | Retain |

## Test audit

Initial inventory: 23 test modules, 410 declared test methods. This is an inventory, not a quota.
Tests use shared temporary-repository fixtures and fake model results; live-host acceptance is
separate. No existing test count or incidental wording is a success criterion.

| Test modules | Action | Distinct protection / change |
|---|---|---|
| test_authority, test_registry, test_branches | Retain | Native human provenance, checkout/branch identity; extend current publication-proof cases. |
| test_controls, test_system | Retain and extend | Cancellation/process containment, progress and state locks; add assessment to existing host/phase matrices. |
| test_config, test_installation, test_service | Retain | External settings, subscription host restrictions, packaging and recoverable installation; no new settings. |
| test_workflow | Improve existing scenarios | Current packet, assessment reuse, verification-before-review, repair before allowance, immutable receipts and publication. Remove obsolete call-order assumptions. |
| test_plugin_transitions | Improve | Replace full-history expectations with complete indexed findings and bounded current handoff; retain upgrade/entry guarantees. |
| test_delivery, test_design_adapter | Improve | Replace design-owned difficulty assertions with runtime selection; preserve document bytes, completion, private paths and resume authority. |
| test_design, test_propose, test_planning, test_plans, test_private | Improve relevant existing cases; retain domain protections | Drop mandatory growing report counts and incidental prompt fragments. Preserve approval, routing, refinement and rendering behavior. |
| test_gates, test_mcp_server | Improve existing host cases | One native publication decision, current failure reporting and consistent actions; retain stale/tampered-choice rejection. |
| test_analytics | Extend existing usage accounting | Assessment usage belongs to task totals without counting as author/reviewer or manufacturing missing observations. |
| test_integration, test_windows | Extend existing host matrices | Assessment read-only permissions, legacy evidence and platform behavior; avoid separate duplicated suites. |
| test_select_tests | Retain | Affected-selection dependency and ownership rules. Add explanatory plan path ownership only if needed. |

Concrete obsolete assertions identified: `test_design.test_a_repair_rewrites_the_same_doc_from_the_reviewed_parent` requires growing `implementer_reports` counts and incidental prompt phrases; `test_delivery.test_ready_selection_skips_blocked_tasks_and_orders_dependencies` contains design-owned difficulty assertions. Replace these expectations in place, retaining their lifecycle/resume cases. Test deletion is based on lost purpose or proven duplicate protection, not duration alone.

## Validation and decisions

- 2026-10-12: user approved the complete plan and selected fresh runtime assessment over
  coordinator assessment. Use the existing standard profile; no new model configuration required.
- 2026-10-12: no product files or run evidence in my-geoffrey will be changed by this refactor.
- Baseline: all 22 affected modules passed (405 tests), 392.71 seconds with two processes. Slowest modules: delivery 240.85s, propose 111.44s, workflow 79.44s, design 73.24s. Per-test durations retained in the external baseline log. The initial sandbox run was discarded because process inspection was denied; no production behavior was weakened to satisfy that environment.
- Integrated candidate, live trials, independent review and publication: pending.

- Task 3: targeted multi-task handoff, final-check evidence, repair/family context, repo/private scope preservation, planning repair and private human-refinement scenarios passed. The old required historical report bundle was removed; older original records remain untouched. Also replaced Geoffrey-specific mandatory doc/test cross-link prose with the consumer's documentation conventions.

- Task 4: runtime assessment, multi-task reuse, both-host repeated-family escalation, legacy design annotation independence, stopped-task continuation and read-only host permissions passed targeted checks. Assessment cost is retained as a separate role and included in task totals; no new model setting was introduced.

- Task 5 validation so far: shared-policy review allowance, planning repair, private approvals and pause-after-review passed. The allowance scenario now also asserts that the last repair and its verification precede the renewal question. Legacy waiting runs use the same policy to complete already-authorized repairs without renewing reviews.

- Task 5: allowance timing, stopped-version continuation, Stop after a worker, current-failure reporting and automatic same-authority continuation passed. Updated the two obsolete expectations (repair was previously withheld at a spent window; historical failure was previously displayed during its replacement). No new test method was needed.

- Task 6: immutable readable receipts, complete indexed family history, current whole-change PR summaries, portable evidence validation/tamper rejection and native publication destination binding passed targeted checks. Removed obsolete repair-paragraph concatenation and a byte cap on the full PR audit section.
- Test audit improvement: shared workflow fixtures capture the unchanged source runtime version once; consumer Git-tree checks and explicit upgrade overrides remain active. This avoids repeatedly hashing the OH source during a single synthetic run. Validate the measured effect with final affected-check durations.

- Workflow skill validation: all four shortened workflows passed the skill-creator validator. PyYAML was installed only in a temporary validation environment because neither local Python runtime supplied it; project dependencies were unchanged. Shared host protocol now lives in `workflows/runtime.md`.

- Broader affected run: 405 tests in 419.45s (baseline 392.71s). The new assessment adds native
  lifecycle work; no speedup is claimed. Failures exposed obsolete direct-prompt, attempt-order and
  Retry-menu assertions. They now check actual packets and authority instead. Follow-up modules
  also exposed the PR base label using a Git remote ref and an older receipt missing an attempt ID;
  presentation now uses the approved PR target and tolerates unavailable historical fields.
- The reviewer prompt contained contradictory historical-report instructions; consolidated them
  around the current packet. Distinct failures in one family are retained, author repair claims are
  labelled, and later clean reviews are linked without editing earlier receipts. Terminated attempts
  without a final report remain resumable. Large planning views are referenced, and private diffs
  are no longer duplicated into coordinator status beside the complete approval preview.
- First live trials: Claude clean and defective-test fixtures passed in 116.29s and 120.93s;
  Codex clean passed in 261.01s. Each used one review and passed the separate contract oracle.
  Codex spent much of review rediscovering OH's hash/config logic and inspected an older installed
  runtime. The golden reference's `review-admission-check.sh` handles this natively. OH now reuses
  its existing worker connection for a read-only `admission` operation bound to the current review;
  it cannot run checks, change scope or grant completion. No additional service or model role.
- Live Claude initialization also exposed unrelated connector tools and 40 inherited skills.
  Child invocations now use its documented strict MCP/disabled-skill switches; Codex child apps
  are disabled through an invocation override. User configuration remains untouched. Codex settings
  were checked against the [official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).
  Repeat the final live matrix after these evidence-driven corrections; early trial results are
  exploratory measurements, not final-candidate acceptance.
- All 405 affected tests were exercised; failures were corrected and their modules/scenarios
  rerun. The final native-admission/host checks passed after supplying the lifecycle fixture's
  explicit role. Extended the existing worker-tool test with admission tamper, stale-tree,
  finished-attempt and role-isolation checks. No additional test method or module was introduced.
- Syntax and diff checks passed. macOS native host checks passed; native Windows-only cases
  remain for Windows CI, with platform-neutral command/permission assertions checked locally.

## Integrated candidate and final acceptance

Tested build: `0.6.0-SNAPSHOT.1791828678964737000`. Both hosts were packaged together.
The current production runtime, prompts, workflows and configuration match the tested package
byte for byte (54 files compared). Test-only and documentation updates after packaging do not
change the candidate's runtime. The installed development plugin has not been switched.

Activate this exact candidate for the agreed Desktop trial:

```sh
oh-dev on --build "/Users/pedromoreira/.local/share/oh-dev/builds/0.6.0-SNAPSHOT.1791828678964737000"
```

Final live trials used actual subscription-authenticated CLI workers and reviewers, isolated
synthetic consumer repositories and external OH records. The input command grants were fixture
records for these explicitly authorized tests; they do not prove Desktop human-message provenance.
Every trial used one assessment, one implementer and one independent review. Every review was
clean; no review renewal, scope question or repair interruption occurred. No trial published code.

| Host | Fixture | Repeat | Elapsed seconds | Input tokens | Output tokens | Cached input subset |
|---|---|---:|---:|---:|---:|---:|
| Claude | Clean implementation | 1 | 82.13 | 301,237 | 8,637 | 239,697 |
| Claude | Clean implementation | 2 | 72.77 | 308,651 | 7,581 | 258,652 |
| Claude | Defective assertion | 1 | 73.40 | 302,304 | 7,276 | 251,418 |
| Claude | Defective assertion | 2 | 89.64 | 304,215 | 10,533 | 252,099 |
| Codex | Clean implementation | 1 | 160.92 | 494,540 | 5,153 | 380,672 |
| Codex | Clean implementation | 2 | 194.01 | 494,623 | 6,350 | 412,928 |
| Codex | Defective assertion | 1 | 191.38 | 463,666 | 6,178 | 384,640 |
| Codex | Defective assertion | 2 | 181.17 | 442,350 | 5,769 | 341,376 |

These are observed totals across all calls, including assessment; cached input is already part
of input and is not added again. They are workload observations, not API bills. No token saving
against the golden reference is claimed. Median elapsed time was 77.77s on Claude and 186.28s
on Codex. Assessment took 11–14s and 27–31s respectively, which is visible overhead on tiny tasks.
These fixtures establish correctness and interruption behavior, not large-project performance.

The defective fixture began with correct code and an assertion contradicting its approved
contract. All four runs corrected the assertion and retained the correct behavior. A separate
oracle checked required behavior and unchanged requirements. The retained tests also caught
all five isolated seeded defects in every trial: lower/upper escapes, exclusion of the upper
boundary, wrong equal-bound behavior and acceptance of reversed bounds. Missed seeded defects:
0 of 40. No model or native completion claim substituted for these checks.

Final regression work reused the existing fixtures. All 405 affected tests were exercised;
obsolete assertions were corrected and their affected cases/modules rerun. Then 204 workflow
scenarios exercised native admission validation across repository/private plans, Propose/Design,
delivery, interrupted work and human dispositions. The one remaining old PR-target expectation
was corrected and its full delivery scenario passed. The inventory remains 410 test methods;
none was added to meet a count, and no whole scenario was deleted because each protects a
distinct supported boundary. Superseded report-bundle, prompt-wording and Retry expectations
were removed instead. External logs include duration reports and original failures.

### Remaining acceptance, in order

1. Developer trial in fresh Desktop sessions: meaningful progress, Stop during implementation
   or review, fresh-session resume, and one native publication question with reuse of existing
   completed work/PRs. Host-imposed permissions and citations remain host behavior.
2. Fix any observed integration defect; preserve useful work, evidence and existing authority.
3. Fresh independent invariant review of the final OH change, using the configured review
   profile and immutable admission. Repair blocking findings before publication.
4. PR for human merge, with affected Linux/Windows CI and measured durations. Local command
   and permission tests cover platform-sensitive paths; native CI on those systems is pending.

The initial recovery copy and all live test evidence remain outside Git. The final metrics and
negative-oracle results are under `/private/tmp/oh-refactor-final-metrics.json` and
`/private/tmp/oh-final-*/`; complete native receipts are linked from each fixture's `result.json`.


### Desktop-trial correction evidence

- Canonical IDs, incorrect-ID correction in the same author call, ambiguous legacy mapping,
  immutable v2 recovery and exact subject/verification reuse pass targeted fixtures. The v2
  recovery fixture is the one added test: no previous fixture imported this failed handoff.
- The native worker-tool fixture exercises invalid → valid → duplicate submissions, rejection
  of a later invalid reviewer submission, role isolation and zero reviewer check execution.
- Stop/pause and worker-completion fixtures pass. Legacy optional finding fields are retained
  without inventing empty metadata. All 22 affected test modules passed; follow-up host/platform
  checks passed (52 cases, 12 native-Windows-only skips), as did the final return-boundary and
  legacy-recovery fixtures. Syntax and Windows-risk checks passed. Native Linux/Windows CI remains
  required before publication; macOS simulation is not a claim of native platform execution.
- Read-only inspection of actual 0005: paused, unambiguous v2 mapping, request hash matches,
  no verification errors, one of three review rounds consumed. No consumer mutation or resume.
- The first live candidate exposed Claude plan mode rejecting the explicitly allowed native
  report write. Its native assessment/review evidence is retained externally. Those trials do
  not count as successful acceptance. The corrected reviewer uses default permission handling
  with exact native-tool allows; its existing filesystem sandbox and write-deny rules remain.
  The native Windows permission fixture verifies these restrictions. Codex also inherited
  unrelated interactive MCP processes and stayed open after completing a report. Invocation-only
  tool/plugin overrides now match Claude's native-tool isolation. Actual Codex config parsing and
  complete live runs verify that boundary; installed settings remain unchanged. Independent OH
  review/publication still follows the developer trial.


### Corrected live acceptance

All four trials completed blocking review → one real repair → clean fresh review, with zero
missed seeded defects and zero human interruptions. Each preserved SPEC.md and passed the
independent behavior oracle. The initial defective, test-passing author handoff was synthetic;
assessment, repair and both reviews used real subscription agents. These fixtures measure the
handoff boundary, not the expected time or cost of consumer task 0005.

| Host trial | Seconds | Observed input | Output | Cached input subset | Reviews | Check calls | Rejected submissions |
|---|---:|---:|---:|---:|---:|---:|---:|
| Claude 1 | 159.99 | 682,665 | 18,585 | 576,194 | 2 | 2 | 2 |
| Claude 2 | 175.86 | 784,172 | 24,067 | 677,582 | 2 | 3 | 3 |
| Codex 1 | 262.44 | 806,308 | 13,317 | 710,144 | 2 | 2 | 3 |
| Codex 2 | 366.02 | 799,009 | 13,296 | 711,680 | 2 | 2 | 3 |

Cached input is already included in observed input; it is not added again. No savings claim is
made. The extra Claude check followed another code/test edit, with a different tree; report
correction did not rerun unchanged checks. The first Claude trial exercised reviewer rejection;
the other three also injected an author-report rejection through the actual native connection.
All corrections completed inside the original agent attempt and consumed no extra review round.
Original failed exploratory trials are retained externally and excluded from these pass counts.

C6 remains open only for the developer's Desktop resume/publication trial, fresh independent OH
review and PR/CI. The paused consumer remains untouched: one of three review rounds was used,
and its latest retained report and verification passed the read-only compatibility check.

### Publication question correction — Desktop trial, 2026-10-13

Task 9 reached a clean sixth review and native completion commit `892a49c` in the consumer.
No publication choice was applied. The native question was accepted, followed seconds later by
a final answer/turn completion; the developer observed the menu appear and immediately close
again when reopened. No context-compaction event occurred. Separately, the human typed `Pr`:
the case-sensitive command parser ignored that valid choice, leaving `pr_summary` unauthorized.
The accepted question-tool result did not establish that the question remained visible.

- [x] D1: Normalize bare command choices without rewriting native human evidence or accepting
  arbitrary prose. Extend existing choice/publication fixtures for `Pr` and uppercase choices.
- [x] D2: Show results before the native question and keep its turn waiting for the human reply
  with the existing interruptible host wait. Preserve the exact question/destination binding,
  no authority from silence, and the typed fallback when native display is unavailable or fails.
  Validate the actual Desktop question lifetime before claiming this host correction works.
- [x] D3: Run affected gate/authority/MCP checks and syntax, then prepare a development candidate
  for the developer's host trial before independent review/publication. Do not modify the
  completed consumer run or publish from this monitoring/development conversation.

Golden reference: `harness-before-separation` Deliver task checkpoint and `codex-gate.sh` wait
for an explicit human command; they do not require a transient native popup. OH retains its
native publication question to share the user's exact destination approval with Codex, and
uses the proven direct-human-command path as its fallback. Capitalization has no bearing on
the approved scope. Existing transcript, current-menu, destination and one-use checks remain.
Internal workflow citations are deferred at the developer's request.

D1 validation: the existing native gate fixture now consumes a direct `Pr` reply, retains `Pr`
in the immutable human source and binds publication to the same reviewed HEAD. Existing native
question stale-answer and changed-destination cases pass in that fixture. The existing choice
dispatch fixture checks lowercase, capitalized and uppercase bare choices without rewriting the
source. Both affected cases passed; no additional test method was introduced. The initial sandbox
attempt could not inspect fixture processes (`/bin/ps`); the unchanged fixtures passed with that
local permission. No native receipt, choice or consumer work was modified here.

Desktop question lifetime trial: the developer confirmed that the same native async question
stayed visible for at least 20 seconds while this turn remained open, and its native answer
arrived successfully. This validates the wait mechanism; publication through the updated
Deliver coordinator still requires the development snapshot trial.

The affected run exposed a superseded assertion in the gate suite: it expected the old dotted
plugin override and unrelated plugins to remain enabled in a child. The prior isolation change
intentionally disables inherited interactive tools using parsed TOML tables. Removed that
duplicated command-shape block; the existing integration fixture already proves tool isolation,
project/user configuration coverage and unchanged user settings. Kept the worker/menu and
wrong-runtime authority checks in the gate test. Production isolation was not weakened.

Validation finished: all 22 affected modules were exercised. Twenty-one passed initially;
the gate module passed after the obsolete block was removed (38 cases including the existing
isolation fixture, 77.7s). The focused choice/publication cases passed, as did syntax and
Windows-risk checks. Logs: `/tmp/oh-publication-affected.log`,
`/tmp/oh-publication-gates-final.log` and `/tmp/oh-publication-syntax.log` (external, not committed).
D3's candidate was subsequently activated with E3 below; the actual publication trial remains
in C6. Existing consumer sessions retain their loaded snapshot until the developer opens a fresh
session. Neither the ignored capitalized message nor the display-test answer here was turned
into consumer publication authority.

### Gate coverage and fresh-session final checkpoint — 2026-10-13

The developer requested the monitoring heartbeat be stopped, every equivalent menu path be
audited, and the corrected snapshot be enabled before resuming 0005 in a fresh session.
The heartbeat is paused. Consumer code/evidence stays untouched during development.

- [x] E1: Audit shared and host-specific gate entry points. Ensure native async publication
  questions retain the corrected wait at partial-task, completed-run and changed-destination
  gates; ordinary blocking menus and prose-only clarification keep their appropriate handling.
- [x] E2: Resume a settled completed-task decision under the new runtime and owning session,
  preserving completed commits, original receipts, settings, task/review allowances and any
  recorded publication grant. Validate the saved branch/HEAD/tree and plan evidence before
  adoption; reject live execution or changed work. Reuse existing continuation fixtures on
  both hosts and the completed-delivery fixture rather than adding a parallel suite.
- [x] E3: Run affected checks and syntax, commit the coherent correction, rebuild and activate
  the fixed snapshot for both hosts. Verify the installed revision. The developer then invokes
  Deliver 0005 in a fresh session; it must return directly to the saved final decision without
  starting another task or rerunning checks/reviews.

Reference: golden Deliver step 2 and `next.sh` distinguish a task checkpoint, completed branch
and recorded PR choice before selecting runnable work. OH keeps that distinction while using
its existing journal and subscription runtime. The current gap is runtime adoption at those
settled boundaries, not missing user scope or a reason to grant another task.

E1 audit: `gates.how` is shared by partial batch, completed run and changed-destination
publication questions across Deliver, Propose and Design. All use the corrected native wait.
Other Codex approvals/review/scope/pause menus use blocking `choose`; configuration uses
blocking `confirm`. Claude uses its blocking native question and the existing human-answer
hook. Missing idea/initiative/track and Refine replies use plain conversation, so ending
those turns does not dismiss a pending native menu. No second async gate implementation was
found. The existing publication fixture also verifies that a changed destination produces
its own current question without replacing the saved old grant.

E2 validation: extended the existing Stop/resume fixture through the final decision and a
recorded PR grant on Codex/repository and Claude/private plans. The same run, completed HEAD,
receipts, task/review allowances and settings survived both session and runtime changes;
no worker or check was rerun. Live-run and dirty-checkout adoption is refused. The existing
finished-design fixture covers a new runtime after Stop and rejects an amended HEAD.
Both scenarios passed (30.1s total). Read-only inspection of real 0005 confirms its clean
completed commit and plan evidence match, with task 9 done and no further granted task.
The fixture initially lacked a publication remote and reused an old human turn ID; corrected
those inputs, preserving production publication and stale-command checks.

Final E2 checks also interrupt the finished-run handoff before updating the active pointer.
Runtime adoption and reopening a stopped completed run are one journal transition, so replaying
the same human command still reaches the final gate. Both continuation scenarios passed again
(33.5s), and all 22 affected test modules passed. Syntax/Windows-risk checks passed. Logs remain
external in `/tmp/oh-gate-resume-affected.log`, `/tmp/oh-final-gate-atomic.log` and
`/tmp/oh-gate-resume-syntax.log`. No test method or suite was added for this correction.
E3 activation succeeded: source commit `a20e02bd430bac4c6fc0981ed2e5d21260d5999b` is enabled
for both Codex and Claude as `0.6.0-SNAPSHOT.1791855995703845000`. `oh-dev status` confirmed
both hosts on that exact snapshot and source revision. The consumer run was not resumed or
published by this development session. The developer's fresh-session publication trial and
independent OH review remain in C6.

### Quality and delivery visibility — follow-up

The developer confirmed the fresh-session final gate worked. The new session resumed task 9
without implementation/review and opened consumer PR #144 with one publication answer.
Its coordinator ended while CI was pending; a failed test timeout was discovered by the developer.
The earlier six review receipts contain 13 families: five original, seven first-round escapes
and one test-proof regression. This is evidence of late discovery, not repeated ignored repairs.

This follow-up preserves execution decisions, authority, models, schemas, allowances and
Stop/resume. No additional agent, service, consumer file or approval is introduced. Automatic
post-publication repair and internal skill citations remain deferred.

- [x] F1: Save baseline instructions and reuse live-agent trial tooling with small synthetic
  clean/defective fixtures for public contracts, time boundaries, siblings and weakened race
  proof. Compare baseline and candidate twice per host using unchanged configured profiles;
  record detection, false findings, rounds, observed tokens and elapsed time.
- [x] F2 (F1): Replace overlapping implementation/review instructions with ordered coverage
  derived from approved requirements and actual operations, then challenge author claims.
  Preserve full-task review and family closure. Keep only changes supported by trial evidence.
- [x] F3: Remove check logs from review remaining-work; label running/incomplete reviews and
  claimed/confirmed repairs accurately, retaining original evidence and human dispositions.
- [x] F4: Clarify existing agent phase messages at actual handoffs, distinguishing a waiting
  review allowance from a started review. Reuse existing progress delivery/deduplication.
- [x] F5: Extend shared publication instructions to observe CI for the current PR head,
  diagnose failure, and report missing/external checks honestly; do not implement CI repair.
- [x] F6: Create the deferred project-local learning GitHub issue with bounded, evidence-linked
  lessons, relevance and staleness handling; no lesson creates authority or escalation.
- [x] F7 (F1–F6): Extend existing behavioral fixtures, run affected/syntax checks and comparative
  trials, commit focused changes and activate a candidate on both hosts for the developer's
  host trial. Independent review and publication follow that trial, as required by AGENTS.md.

Golden reference: Deliver's inspectable readiness, whole-family repair and complete coverage
lenses are retained. Its reviewer calibration method is useful without its promotion machinery;
its publication path explicitly waits for current-head CI. OH uses the existing coordinator for
that observation rather than introducing a CI repair loop. No trial can prove exhaustive review
quality; report measured misses and false findings instead of assuming improved savings.

Coverage map: extend `test_plugin_transitions`' existing repair/receipt scenario for bounded
handoffs, active/missing artifacts and claim labels; extend existing workflow progress/allowance
scenarios for real transition ordering. Shared workflow prose gets scenario validation rather
than assertions matching its wording. All historical receipt readers and authority checks remain.

F3/F4 evidence: the existing repair/receipt fixture passes with running and missing-result cases,
bounded check summaries and claimed/confirmed labels. Existing progress and allowance fixtures
pass; phase messages follow immutable admission, and a spent allowance launches no reviewer.
No test method was added. F5's seven fixed coordinator scenarios passed on actual Codex and
Claude standard-profile calls: pending CI, changed head, failed check, absent CI, interrupted PR,
spent review allowance and successful checks. Both preserved review/publication authority and
proposed no edits. This validates instruction interpretation, not actual GitHub/Desktop behavior;
the developer snapshot trial still verifies that path. Scenario results are external under
`/tmp/oh-quality-coordinator-v2-{codex,claude}/result.json`.

F6: created [issue #80](https://github.com/pmoreiracc/o-harness/issues/80),
“Project-local learning from escaped and recurring defects”. Its design and implementation
remain deferred. Handoff messaging is included in F4 rather than tracked as another feature.

F7 automated evidence: all 22 affected test modules passed, as did syntax/Windows-risk checks.
The final allowance-message extension also passed separately (11.2s); progress ordering passed
in 3.6s. Logs are external at `/tmp/oh-quality-{affected,syntax,focused,progress,allowance}.log`.
The Deliver skill validator passed using the existing temporary validator dependencies.
Code and behavioral fixture changes are committed as `8e2f601`.

F1/F2 comparison finished using the existing native trial pattern, adapted in the external
`/tmp/oh-quality-trial.py`. Baseline was enabled snapshot `1791855995703845000`; the candidate
was frozen as `1791858045278984000` before testing. Each host ran each variant twice, with a
retained defective draft followed by a real independent review, real implementer repair and
fresh review of the clean result. Initial draft/readiness were synthetic; assessment, repair
and reviews were real. These are comparative trial costs, not complete new-task implementation
costs. The configured profiles were unchanged: Codex assessed with sol/medium, selected
astra/high for repairs and reviewed with sol/high; Claude used sonnet/medium and opus/high.

| Trial | Seconds | Input tokens | Output tokens | Cached input subset | Reviews |
|---|---:|---:|---:|---:|---:|
| Baseline Claude 1 | 184.79 | 663186 | 17738 | 542931 | 2 |
| Baseline Claude 2 | 207.18 | 686695 | 21257 | 578650 | 2 |
| Baseline Codex 1 | 642.05 | 850356 | 19476 | 748288 | 2 |
| Baseline Codex 2 | 754.05 | 970679 | 22067 | 860544 | 2 |
| Candidate Claude 1 | 194.91 | 670652 | 18557 | 566743 | 2 |
| Candidate Claude 2 | 195.01 | 606017 | 18970 | 500940 | 2 |
| Candidate Codex 1 | 650.85 | 815338 | 18506 | 701824 | 2 |
| Candidate Codex 2 | 727.72 | 987693 | 19894 | 839936 | 2 |

Every first review detected all four seeded families: missing initialization state, refund
output compatibility, saved-timezone boundaries across callers and a noncausal concurrency
test. Every repaired control passed the external behavior oracle and an independent in-memory
mutation that removes the race guard. All final reviews were clean: zero missed seeded families,
zero findings on clean controls, zero report rejections, one repair and two reviews per run,
and no intervening allowance/recovery decision. There were 21 verification calls in total.
Cached input is a subset of input, not an additional token total.

Limits and decision: both variants already detected every seeded family, so this small trial
does not establish improved detection or lower review counts on larger tasks. Claude sometimes
added overlapping readiness/coverage findings on the seeded incomplete draft in both variants;
the candidate does not eliminate that noise. Keep the ordered guidance as a clarification using
existing report fields, not a claimed quality guarantee. Time/token differences are descriptive,
not demonstrated savings; host trials ran concurrently. One candidate Claude assessment logged
a macOS process-cleanup warning but completed without a repeated attempt; the original log is
retained. No lifecycle code was changed to hide it. Native logs, requests and results stay outside
Git under `/tmp/oh-quality-*`; aggregate measurements are `/tmp/oh-quality-metrics.json`.

Publication/CI instructions and documentation are committed separately as `cf8aca5`.
The final package was built from that commit; developer host testing and independent OH review
remain required before publication. No production services, report fields or consumer gates were added.

Activation verified: both Codex and Claude are on `0.6.0-SNAPSHOT.1791858920237433000`,
source `cf8aca5fcaa53b36e6c384f04c2ec2675a9de42f`. Activation refreshed the existing development
dashboard; fresh sessions use this snapshot. This final measurement/activation entry is a
documentation-only follow-up to the packaged commit. Next developer scenario: a new bounded
Deliver should report actual implementer/reviewer transitions, retain a visible final menu, and
follow the chosen PR's current-head CI through its result. C6's independent review/publication
remain pending that host trial; no consumer code or OH delivery evidence was edited here.

### Session and host continuation

Approved follow-up: one safe resume path covers a new session in the same host and both
Codex/Claude directions in the same checkout and shared OH store. Active execution has one
owner; completed evidence has provenance, not permanent host ownership. No new approval,
service, configuration or execution state is introduced.

- [x] G1: Consolidate Deliver/Resume continuation under runner-then-control locks. Wait briefly
  only for already-requested Stop/Pause cleanup; refuse a still-active runner without transfer.
  Validate retained work/branch and preserve idempotent command replay across crashes.
- [x] G2 (G1): Transfer host/session together; keep original configuration, difficulty, scope,
  findings and consumed allowances. New calls use the destination's saved profiles. Preserve
  per-attempt origin in old and new evidence; reject stale menus and cancellation events.
- [x] G3 (G1): Resume pending review/semantic/completion gates directly. Reuse valid reports
  and checks; preserve interrupted review accounting. Already-authorized publication retains
  its grant; later descendant commits permit PR observation only, never unreviewed publication.
- [x] G4 (G1–G3): Extend existing resume/control/receipt fixtures across all four session/host
  directions and interruption boundaries. Run affected checks and syntax, commit and activate
  both hosts for developer Desktop Stop → Claude and same-host fresh-session trials.

Golden reference: Deliver and `next.sh` derive continuation from saved work and human task
choices; host-specific gate adapters do not define which product task exists. Retain OH's
fresh agents and native session ownership to isolate Stop/menu events, using existing journal
transitions to move that ownership instead of a second handoff system. Independent review
and publication follow the developer host trial (AGENTS.md).

G1–G3 implemented through the existing `delivery.continued` transition. The shared ownership
routine validates the saved branch and work while holding runner/control locks in execution
order. Already-requested cleanup gets up to ten seconds per call, with a valid Deliver/Resume
command retained for another automatic attempt if needed. A still-active run is refused.
Same-host and cross-host moves use this same routine. Explicit Resume always retains the run;
ordinary later Deliver admission in its existing session keeps its established new-batch and
branch-refresh semantics, including conflict/human-handoff paths. Those paths were preserved
after regression checks exposed an overly broad early classification.

Historical attempts derive their original host from the journal at admission; new attempts
also store it explicitly. Receipts and PR history show that origin without rewriting evidence.
Typed choices now reject a stale owner before any transition, and cancellation compares host
as well as session. Stale native menu replies remain bound to the old journal/menu. A recorded
PR grant with later descendant commits returns the derived `observe_publication` action and
`publication.observe_only`; native evidence export still refuses the later unreviewed head.
No execution state, configuration or consumer approval was added.

Validation: all 22 affected modules were exercised. The changed delivery/gate/launcher modules
were rerun together (88 cases, 393.3s); their final remaining conflict case passed after restoring
unstarted-work admission (7.8s). The final four-direction matrix passed again (37.8s), including
unreviewed-publication refusal. Native Resume/menu and completed-recovery cases passed (22.6s);
interrupted review and updated command dispatch passed (4.9s). Existing fixtures were extended;
no test method was added. Syntax and Windows-risk checks pass. Logs are external under
`/tmp/oh-transfer-*.log`. The Resume skill validates after removing its unchanged Claude-specific
frontmatter key from a temporary validation copy; the source keeps that supported host setting.

A read-only validation against real 0005 accepted host transfer and selected PR observation for
its later commits. The probe collected the proposed transition in memory; it wrote no consumer
journal, approval, branch or file. Developer Desktop testing remains necessary before independent
OH review and publication. The next snapshot must be tested with a fresh session on each host.

G4 activation: commit `33e85c71e9b920f564108a88f98327420728447a` was rebuilt and enabled as
`0.6.0-SNAPSHOT.1791887114519730000` on both Codex and Claude; `oh-dev status` confirmed both
hosts on that exact source. The remaining manual trial is Desktop Stop during work, followed by
Deliver/Resume in a fresh session in either host; 0005 currently resumes its existing PR observation.
This activation record is a documentation-only follow-up. Independent review remains after the
developer host trial, and no OH PR has been opened or merged by this change.

### Publication completion and finished delivery cycles

Approved follow-up: a new session alone does nothing. Resume continues unfinished work or
interrupted publication; a published run reports its PR without reopening delivery. A new
Deliver request follows normal task admission and branch safeguards. PR creation ends the
implementation cycle, while current-head CI reporting remains separate from review approval.

- [x] H1: Add a verified, immutable publication receipt separate from the human publication
  grant. One shared CLI/MCP command discovers or verifies the PR using its approved destination,
  branch/base and commit evidence; interrupted calls are idempotent.
- [x] H2 (H1): Recognize publication before transferring ownership. Update shared next-action,
  Resume, Deliver and publication recovery; replace the changed-HEAD observation shortcut.
  Preserve older runs, original approvals, consumed allowances and current-head CI reporting.
- [x] H3 (H1–H2): Extend existing publication, host-transfer and admission fixtures for interrupted
  publication, later commits, closed/merged PRs, branch reuse and GitHub failures. Run affected
  checks and syntax with duration evidence. No additional orchestration or test framework.
- [x] H4 (H3): Update verified documentation, commit the candidate and prepare the development
  snapshot. Remaining developer trials under C6: Resume 0005 on either host reports its PR; a genuinely stopped
  run resumes work; a new Deliver after merge selects the next approved batch. Independent
  review and publication follow that host trial, as required by AGENTS.md.

Reference: golden Deliver's Finish with PR opens one PR and follows current-head checks;
next.sh treats the PR choice as terminal for task admission. OH adds a durable verified
publication result because fresh host sessions cannot depend on the publishing chat's memory.
Existing status `pr` remains compatible as publication approval; the additive receipt supplies
completion evidence. No consumer gate, configuration or background service is introduced.

Test disposition: retain the existing review-evidence tamper test; add one integrated publication
recovery case using the existing workflow fixture, because this external completion boundary had
no coverage. Replace the host-transfer fixture's changed-HEAD inference with verified PR
completion. Extend existing delivery admission and CLI/MCP command fixtures rather than
duplicating model-run setup. GitHub failures must preserve saved evidence and never authorize
a duplicate PR; later commits must never inherit the saved review.

H1–H3 implemented with one additive `publication.completed` journal event and one CLI/MCP
`publication` command. It reads the approved GitHub destination using the existing gh login,
matches branch/base and the approved commit in the PR, and pins the verified PR identity.
Reads paginate; a truncated commit list cannot establish absence. Repeated calls preserve the
original receipt and return current observations separately; an outage retains a clearly labelled
last verified result. No remote writes occur in this command. The readable run index links the PR.

Resume checks publication before transferring ownership or applying checkout-tree restrictions.
The existing execution entrypoints return a verified finished result without running workers,
while still rejecting a result belonging to another active run. New Deliver uses normal branch
admission after publication: it cannot append tasks to an unmerged published branch, and after
merge selects the next task. The previous changed-HEAD shortcut is removed. CI follow-through
remains separate, and the immutable reviewed commit never expands to cover later changes.

Validation: all 16 modules selected by `affected HEAD` were exercised. Fifteen passed directly;
the delivery module's two affected cases needed fixture corrections (a local Git remote could
not stand in for GitHub publication, and the old scope test started another batch immediately
after PR approval). The final delivery cases plus publication regression passed together:
3 tests, 42.57s. All other delivery cases passed, including the four-direction Stop/Pause →
resume → publication → next-batch matrix (45.84s in the module run). The shared workflow module
also passed, including the final command-result binding. Syntax and Windows-risk checks pass.
No full suite or real consumer checks were run. These are macOS runs of both host fixtures and
platform checks, not claims of native Windows/Linux or Desktop trial completion.

A read-only probe of the real 0005 journal and GitHub recognized PR #144 as merged, including
its later head, while confirming the original journal was unchanged. No consumer checkout,
approval, ownership or receipt was modified by the probe. External logs are
`/tmp/oh-publication-{focus2,affected,regressions,syntax}.log`. The candidate still needs the
developer's fresh-session host trial and the subsequent independent review under C6.

H4 activation: source `497aca900bb7e5c2cf705a373a757d7fd78f9216` is enabled on both Codex
and Claude as `0.6.0-SNAPSHOT.1791889457000178000`; `oh-dev status` verified both hosts,
the source revision and snapshot mode. Existing sessions retain their loaded plugin, so the
developer trial uses fresh sessions. Start with Resume in my-geoffrey: it should report merged
PR #144 without transferring the finished run or reopening a gate. Test genuine mid-task
continuation separately. This activation note is documentation-only; no OH PR was published.

### Renew execution per phase and strengthen core review

Approved scope: address only the observed Claude SDK background interruption, missing public
progress/result summary, and a reviewer dismissing an explicit requirement. Consumer task 10
and its receipts stay untouched. No new approval gate, publication redesign or review stage.

- [x] I1: Add safe one-agent-phase execution to the shared runner and use it in native host
  entrypoints. Save reports, validate evidence and finish deterministic transitions before
  yielding. Return explicit automatic continuation, retaining the same run and authority.
  Each call gets a fresh two-hour budget with one minute reserved for cleanup; there is no
  workflow-wide deadline. Interrupted attempts retain the existing allowance rules.
- [x] I2 (I1): Update the host protocol to continue the next native phase automatically,
  observe public progress using supported host tools, and present a short change/check/review
  summary before the existing decision. Observer expiry cannot cancel execution. Keep output
  bounded and avoid raw transcripts, truncated JSON, new services and consumer configuration.
- [x] I3: Integrate required observable behavior, failure paths and proof into the core review
  procedure. Author disclosures and prior implementation patterns cannot waive requirements.
  Retain existing lenses and receipt fields; no blanket test requirement or final checklist.
- [ ] I4 (I1–I3): Extend existing workflow, control, progress and host fixtures with simulated
  long phases and observer expiry. Exercise real Claude/Codex reviewers on a disclosed defect
  and a compliant control. Run affected checks and syntax, record durations and limitations,
  then build the development candidate for the developer's host trial before C6 review.

Reference: the golden Deliver implements in the parent agent and starts fresh reviewers with
bound readiness. OH retains its fresh implementers but must end transport calls at durable
agent boundaries. The native runner still owns next-action selection, checks validation,
review admission and completion; the coordinator only continues returned execution.

Coverage disposition: extend the existing batch/idempotence fixture for per-phase continuation
and the existing Stop/Pause fixtures for handoff cancellation. Reuse progress/host fixtures for
observation and result ordering. One focused observer test is justified if no existing fixture
can cover its expiry without launching another execution; do not duplicate whole-run setup.
Reviewer calibration uses isolated temporary repositories and existing native admissions.

I1–I3 implementation: the shared runner supports one-phase calls; the CLI entrypoints used by
both hosts enable that mode. An invocation launches at most one assessment/implementation/review,
then retains its result, validates evidence and finishes allowed deterministic transitions.
`continue_execution` explicitly returns automatic continuation under existing authority. No
new workflow state, grant or review receipt is created just for a handoff. Each invocation starts
a fresh 7,140-second native budget inside the 7,200-second host call limit. Normal handoffs do
not interrupt attempts; actual timeouts keep the existing failed-attempt accounting. Automatic
responses carry a short current phase result rather than repeated completed-task history.

Claude now uses the explicit per-phase background limit, Monitor observation and a bounded
fallback when Monitor is unavailable. The small read-only `observe` command binds to a run,
returns bounded public focus, throttles streamed detail to 210 seconds and exits at a returned
execution or observer deadline. Its expiry cannot launch/cancel workers or write evidence.
Gate summaries now contain the delivered work and review outcome/count, including interrupted
attempts, before the existing menu. Resume loads this shared protocol before its first call.
The reviewer maps actual requirements to observable behavior and proof throughout its existing
review procedure; disclosed gaps and older patterns cannot supply an exemption.

Validation: all 16 modules selected by `affected HEAD` passed. The focused phase/control/observer
checks passed in 37.32s. After compacting automatic handoff output, the affected phase/control
cases passed again in 33.77s. A simulated approved batch took over two hours in aggregate while
each agent received its own fresh budget; no handoff was recorded as interrupted. Existing
fixtures cover both host directions and repository/private designs, Stop/Pause between calls,
no repeated workers/reviews, observer expiry and unchanged journal evidence. No new unit-test
method or full-suite run was added. Syntax and Windows-risk checks passed. The Resume skill
passed the skill validator using a temporary copy excluding its unchanged Claude-specific
frontmatter key; production retains that supported host field.

Real reviewers used the saved configured profiles and native immutable admissions on two
isolated fixtures each: a disclosed violation of an explicit transient-error contract, and a
compliant control whose small failure branch can be established by inspection. Both hosts
reported the violation as blocking and accepted the control, with zero report-format issues.
Assessment/implementation were synthetic fixture setup, so these are reviewer calibration
costs including native overhead, not completed product-task metrics or claimed savings:

| Host / case | Seconds | Input | Output | Cached input subset |
| --- | ---: | ---: | ---: | ---: |
| Claude / disclosed violation | 47.59 | 170198 | 4092 | 141154 |
| Claude / compliant control | 49.99 | 171955 | 4086 | 144064 |
| Codex / disclosed violation | 219.33 | 277696 | 6035 | 233216 |
| Codex / compliant control | 145.92 | 266590 | 4239 | 242688 |

Read-only instruction forward tests with the configured standard profiles (Claude 15.68s,
Codex 31.74s) selected automatic next-phase execution, observation-only renewal, summary before
the menu and no restart after Stop. They also offered redundant renewal commentary; the final
protocol explicitly makes observer renewal silent and removes an unnecessary approval aside.
These tests are not actual Desktop/SDK UI trials, native Windows/Linux execution or a guarantee
against semantic reviewer mistakes. Developer host trials and independent OH review remain C6.
No task-10 consumer files or receipts were changed. Evidence stays outside Git under
`/tmp/oh-phase-*`, including affected/focused test logs, native calibration receipts and usage.

Final budget binding starts at CLI entry, so admission/setup inside the command consumes the
same phase budget rather than reducing cleanup headroom outside it. The phase, cancellation
and four-direction cross-host continuation fixtures passed again after that change: 3 tests,
81.90s (47.05s cross-host matrix, 27.03s multi-phase batch, 7.83s pause/stop). Syntax and
Windows-risk checks passed on the final candidate. No failed checks remain.
