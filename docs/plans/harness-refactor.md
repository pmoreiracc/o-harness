# OH harness refactor

Status: implementation in progress. Branch: `codex/harness-refactor`.

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

- [ ] **3. Replace accumulating history with a current task packet.** Depends on 2.
  Introduce a versioned internal packet for approved scope/references, current and remaining work,
  verification references and all finding dispositions. Readiness explicitly covers requirements,
  rules, affected surfaces, proof, self-review, family closure, prior findings, verification and limits.
  Reviewers consume the latest readiness and a compact complete finding index. Retain earlier
  reports by reference without mandatory rereading. Bind packets to task/repository state; preserve
  original evidence. Missing readiness returns to the implementer within existing authority.
  Native verification and independent review remain required; author claims grant nothing.
  **Done when:** more attempts do not grow the mandatory report bundle and every finding is traceable.

- [ ] **4. Add fresh runtime difficulty assessment.** Depends on 3.
  Before each new Deliver task, use the configured standard profile for one read-only assessment
  of approved scope, relevant code and referenced contracts. Return difficulty, rationale, examined
  references and uncertainty. Local bounded edits are simple; ordinary contained changes standard;
  cross-cutting changes, consequential boundaries and substantial uncertainty complex.
  Use an explicit assessment role, retain its evidence externally and count its time/tokens in task
  totals. Reuse its initial selection for repairs/resume. Remove difficulty from design generation
  and ignore old document annotations for new work without editing approved documents.
  Already-started tasks retain their recorded selection and all review allowances.
  **Done when:** new runtime selection needs no consumer metadata or repeated assessment calls.

- [ ] **5. Consolidate workflow decisions.** Depends on 4.
  Derive execution, status, menus and resume from one next-action function over recorded state and
  validated evidence. Preserve Propose/Design approvals and concern/scope decisions. In Deliver,
  repair implementation/check failures before asking for allowance when the next review is ready.
  No routine Retry/recovery approval. Real external obstacles name their cause and next action.
  Stop cancels owned work and fences subsequent checks/reviews/commits. Resume preserves useful
  implementation, findings and consumed allowances; scope never expands silently.
  **Done when:** execution and displayed next action agree in normal, interrupted and resumed runs.

- [ ] **6. Restore readable receipts and organized PR descriptions.** Depends on 5.
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
