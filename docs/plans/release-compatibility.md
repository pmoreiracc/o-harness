# Release compatibility and native acceptance audit

Status: checkpoint prepared for final validation and fresh independent review. This
document preserves the audit history; older status entries describe the candidate at
that time and do not override the current summary below. It is not a release-readiness
claim. The developer requested automated acceptance; fixture results remain distinct
from native-host acceptance.

## Checkpoint status 2026-10-26

- Commit `16174e8` preserves the working Windows delivery/recovery and hook fixes.
  Subsequent Git blob batching removes one Git launch per file from candidate validation
  and standalone review export without caching approvals or weakening byte checks.
  The same 505-file disposable candidate took 43.140 seconds before and 1.260 seconds
  after, producing the identical Git tree. This measures candidate validation, not
  total delivery time.
- The latest observed real Windows Codex continuation completed the approved task,
  retained a clean independent review, committed the reviewed candidate and opened
  the requested PR; its three reported CI checks passed. Resume, additional review
  allowance and publication decisions were answered through native gates. This was
  a continuation from Claude, not a fresh full delivery on one final frozen build.
- The performance patch passed eight focused Windows tests, seven focused Linux tests
  under WSL, syntax/portability checks and a 505-file helper workflow through assessment,
  implementation, checks, review, commit and the final decision request. That helper
  workflow used real Git/OH operations and synthetic native-agent records; it was not
  a live-host end-to-end run.
- The broad affected run completed 25 modules. Twenty-three passed directly, including
  all 25 workflow tests and all ten recovery tests. Four test cases across cancellation
  and Windows execution failed in the parallel run; every failed case passed focused
  reruns without changed deadlines. The check-start deadline also failed on the unchanged
  checkpoint. The initial broad run is not reported as a clean pass, and the intermittent
  file-descriptor failure's cause remains unproved.
- Control-hook limits are 10 seconds for the affected Claude control events and 5 seconds
  for Interrupt. Concurrent packaged-hook measurements established that the former
  three-second limit could cancel successful work. Latest real Codex continuation records
  showed no hook timeout; this does not prove all historical intermittent host timeouts
  are eliminated. Full native Claude validation of the final timeout change remains open.
- Windows long-path handling, state-directory inheritance and narrow legacy ACL repair
  have regression coverage. Existing custom permissions are intentionally preserved;
  sandbox access retries in the real continuation are not claimed universally fixed.
- Remaining before publication: activate and exercise the final combined snapshot,
  obtain fresh invariant review of that exact subject, repair any blocking findings,
  and obtain PR CI results. Final-build native Claude, macOS and Linux delivery coverage
  is not established. Earlier subscription/access limitations are historical observations,
  not a claim about their current availability.

## Historical audit record

All following progress entries refer to their then-current source and host state.

## Baseline and scope

The baseline is published release **0.8.0**, Git commit
`eeceb6f695aa63e604bd00737c5eace5848196bb`. Both the GitHub release tag and the
installed release pointer resolve to this commit. The existing uncommitted patch is
preserved separately before further changes. The active development installation is
not the baseline. Consumer repositories and their saved decisions are not test fixtures.

The audit covers every production module and entry surface below. Inventory coverage
is distinct from code review, executed tests, and native-host acceptance. An unchecked
boundary remains unchecked even if all neighboring tests pass.

## Architecture boundary inventory

| Boundary | Implementation and consumers | Required evidence |
| --- | --- | --- |
| Plugin discovery and packaging | `installation`, `integrations/package.sh`, both plugin manifests, marketplace catalogs, skill wrappers and icons | Both hosts load the built package; installed commands use that exact core |
| Development selection and updates | `integrations/oh_dev.py`, `updater`, production/dev launchers | On/off/status, frozen versus live, shared versus isolated data, interrupted switching and existing-run compatibility |
| Python and shell bootstrap | `python.sh`, `python.cmd`, `get-python.ps1`, `oh`, `oh.cmd`, MCP launchers, hook launchers | Actual selected shell, paths with spaces/Unicode, stdin, exit codes, timeout and missing-prerequisite behavior |
| OS and storage | `system`, `storage`, `private_storage`, `backup` | Windows/POSIX paths, locks, atomic writes, immutable evidence, process identity, backup/restore and cleanup |
| Project identity and configuration | `registry`, `profiles`, `config`, `entry` | Stable checkout identity, linked worktrees, project-owned checks, external settings and no consumer markers |
| User and agent provenance | `authority`, `native_events`, native transcript formats | Actual human choices, child identity/profile, delayed records, terminal versus intermediate outcomes and interruption |
| Human decisions | `decisions`, `native._presented`, shared decision/recovery instructions | Same answer survives recoverable failures; stale/changed/negative answers never grant work |
| CLI and MCP transport | `cli`, `mcp_server`, `worker_checks` | Same operation semantics, current conversation/root, bounded failure, no inherited protocol stdin or alternate permission channel |
| Admission and workflow state | `native`, `workflow`, `prepared`, `controls` | Scope fixed; one active task; exact model/context; retained attempts; consistent continuation and admission |
| Cancellation and ownership | `cancellation`, `processes`, lifecycle hooks | Stop during launch/tool/check, callback loss, late results, descendant cleanup, no overlapping old/new writers |
| Worker packets and result views | `handoff`, `receipts`, `gates`, role prompts | Historical failure distinguished from current evidence; bounded context; complete findings; report prose never proves readiness |
| Git and task selection | `branches`, `delivery`, `design_adapter`, `design_parse`, `delivery_verify` | Merged/unmerged/no-op branch transitions, dirty work, WIP commits, approved task structure and cumulative branch review |
| Planning and artifacts | `plans`, proposal/design workflows and prompts | Repository/private planning, approval, ownership, transactional edits, refinement and resume |
| Checks and reviewed completion | `checks`, `verification`, `review`, `review_report`, `native.complete` | Candidate/check/review agree; changed subject invalidates evidence; failed/cancelled checks cannot pass |
| Findings and publication | `scope`, `issues`, `publication`, publication workflow | Scoped repair, remaining allowance, follow-ups, explicit publication authority, idempotent PR recovery and exact-head CI |
| Dashboard and observations | `telemetry`, `transcripts`, `observability`, `server`, `service`, dashboard assets | Read-only views, no grants from telemetry, unavailable data stays unknown, collector errors do not corrupt workflow |
| Compatibility aliases | `actions`, `runner`, `design_runner`, package `__init__` | Imports remain compatible; no second execution loop |
| Verification infrastructure | Test modules, `select_tests.py`, `full_tests.py`, `windows_risk.py`, `install-check.py`, GitHub workflows | Platform selection, real package execution, failure attribution, useful timings and no secret/transcript publication |

## Established failure chain

1. The older Windows package launched a quoted `.cmd` path as if the host always
   selected `cmd.exe`. The observed Codex session selected PowerShell. The command
   failed before OH's native-control callback ran. Explicit-interpreter packaging
   addresses that reproduced bootstrap failure; successful discovery/trust alone
   does not establish callback execution.
2. The subsequent session accepted Continue but launched no new worker. Its final
   claim that the current hook failed was based on a previous attempt's report.
3. Recovery emitted `delivery.recovered` even when branch and HEAD stayed identical.
   The reducer superseded prior attempts but retained the assessment. Continuation
   then suggested assessment while admission refused reassessment. Status omitted
   the superseded flag, and packet construction also selected historical authors.
4. A completed native child with a plain-text blocked report was stored as
   `implemented`. Missing structured status defaulted to success even though the
   report said no source inspection, candidate or checks occurred. Original prose
   must remain usable; adding a mandatory prose schema is not the remedy.
5. A decision locator containing a turn but no transcript path skipped prepared
   question discovery. The same real answer was located when that turn field was
   removed. The failure was deterministic, not evidence-save latency.
6. PowerShell 5's native argument binder stripped JSON quotes from the suggested
   worker command. Earlier tests decoded that command and called Python directly,
   bypassing the failing shell boundary. Literal `Start-Process` with one correctly
   quoted argument string preserves argv and exit status on PowerShell 5 and 7.
7. The Windows Interrupt hook intermittently exceeded its three-second host limit
   under concurrent test load. Its runtime work measured 0.312 seconds in a fixture;
   the launcher also chained multiple shells and Python processes. The native-control
   route now reuses its isolated UTF-8 interpreter. Direct non-UTF-8 invocations retain
   an explicit relaunch and forward the already-read input; POSIX dispatch is unchanged.

Items 3–5 are in shared code. They must be compared with the release and tested on
both hosts; their discovery on Windows does not make them Windows-only defects.

## Design decisions to verify before implementation

- Keep native host agents, tools and permission decisions. Keep immutable scope,
  finite allowances, fresh independent review and exact-candidate completion.
- Keep Windows compatibility within bootstrap/platform boundaries where possible.
  Do not change POSIX shell execution merely to accommodate Windows fixtures.
- Make continuation a consistent projection of existing evidence, not another
  workflow engine. Its suggested action must be admissible under the same facts.
- Preserve old reports as history. Determine readiness from existing candidate,
  verification and review records; do not parse arbitrary prose into success or
  treat a historical failure as a freshly observed environmental condition.
- Avoid no-op branch resets and evidence invalidation. When the subject really
  changes, invalidate only evidence that depends on that subject; retain grants,
  useful work and review usage.
- Resolve prepared questions from native records consistently for supported locator
  shapes, preserving the existing answer, context, freshness and subject checks.
- Audit each existing patch group separately: filesystem compatibility, Git stdin,
  development storage defaults, hook bootstrap, recovery/decisions, publication,
  assessment/result handling, tests and documentation. A Windows failure is not
  permission to rewrite unrelated shared behavior.

## Automated acceptance strategy

### Core and fault injection

Run the release and candidate in disposable Git checkouts. Extend existing causal
tests rather than duplicating setup. Cover every invariant and transition, including
the observed failure sequence. Inject delayed/partial records, failed launches,
missing callbacks, crashed checks, stale answers, changed candidates and interrupted
recovery. Assert both the intended continuation and refusal of unauthorized work.

### Packaged host contract

Use real installed Codex/Claude binaries and generated plugin commands. Verify
discovery, trust, selected shell, callback payloads, reservation, wrapper execution,
completion and cancellation. A manually supplied callback payload is contract-test
evidence only; it is not proof that the host emitted that payload.

### Native execution

Automate a disposable consumer through the hosts' supported interfaces, using existing
subscription authentication. The driver may supply predetermined test-user inputs
only to its own test sessions and stores. It must not forge approval records, bypass
hook trust, replace native agents, or mutate real consumer history.

Required scenarios: ordinary quick fix; approved-design delivery; blocked worker and
retry; snapshot update and Continue; same/new-session continuation; Stop during an
owned command and configured check; review blocker and repair; allowance exhaustion;
changed candidate; completed batch and publication boundary; proposal/design/review
entry and recovery; release/dev switching and settings/dashboard access.

Use Windows PowerShell and Git Bash as applicable, macOS and Linux. Record host
versions, source hash, scenario, actual events, assertions and result. Separate CLI
acceptance from desktop-specific behavior. A synthetic host transcript, mocked model
response, installation pass or unit-suite pass does not satisfy native acceptance.

### Execution order and acceptance accounting

Finish the coherent fix batch before running its focused regression tests. Repair
any failures in that affected set. Run broader regression checks when the batch is
stable, not after each edit. Native end-to-end acceptance runs last, after all fixes
and their focused checks pass. Re-run a broader suite only for a new change or
unresolved risk that warrants it. The developer explicitly requested this order.

Every required scenario has one of: not run, running, passed, failed, unavailable.
Skipped or unavailable cells are never counted as passed. Completion requires all
required cells to pass and fresh independent review of the resulting change.
The developer is not asked to run the scenarios.

## Current evidence and gaps

- Release identity verified against published tag and installed pointer.
- Production module/interface/import inventory completed; full boundary audit is
  ongoing. This is not yet an exhaustive code-review claim.
- Existing ordinary install-check covers all three OSes but does not execute a native
  delivery worker. Existing workflow tests simulate native-agent evidence.
- An on-demand macOS behavior job is added to the existing full-suite workflow.
  It has not run; the existing macOS install check is not equivalent evidence.
- Windows native CLIs and Ubuntu 24.04 under WSL are available locally.
- The Mac is online through the existing network; its SSH endpoint refuses access.
  Automated macOS execution remains to be arranged and is not marked verified.
- First Linux baseline invocation was invalid because the Windows test driver changed
  shell-input line endings. It is excluded from product results. The corrected run
  completed: 282 tests, 303.197 seconds, no failures, 12 platform skips.
- Windows causal regressions for plain reports/no-op Continue and native decision
  locators failed before the corrections and passed afterward (2 tests, 170.855 seconds).
- Linux candidate: 287 tests, 387.179 seconds, no failures, 14 platform skips. Later
  shell and path changes passed three focused Linux checks (1.704 seconds).
- Windows child-session path detection and long-path settings migration passed two
  causal checks (1.860 seconds). Both extend existing coverage.
- The exact shell/packaged-hook tests exposed and then verified corrections for
  argument corruption and hook startup (2 tests, 99.560 seconds). Interrupt uses
  the unchanged three-second deadline through PowerShell 5, PowerShell 7 and cmd.
  These are real shell executions with fixture provenance, not live-agent acceptance.
- The frozen-development-package entry test passed after the stdin/UTF-8 correction
  (1 test, 30.426 seconds). Syntax and diff-whitespace checks also passed.
- The broader Windows affected run uses a frozen tracked-source copy, excluding an
  unrelated private untracked note. Later hook/launcher deltas are verified separately;
  its result must not be described as a single run of the final source hash.
  All 25 selected modules passed (exit 0).
- A premature Claude native test stopped at provenance binding; no review worker
  executed. A Codex capability-root probe exposed skills but no OH MCP tools. Neither
  is acceptance evidence. Further native execution is deferred until the fix batch
  and focused checks pass. Do not weaken provenance rules for a test driver.
- No acceptance claim or development-installation refresh is justified yet.

### Native acceptance setup findings

The final candidate used for the current tiny calculator fixtures is
`eeceb6f695aa63e604bd00737c5eace5848196bb+worktree.a0fab255962b6e75`.
Both projects are disposable local Git repositories with separate OH stores; no
GitHub repository was created. Existing user installation and consumer work are unchanged.

- Claude's interactive CLI presents genuine native plan approval. Its first launch
  inherited the controlling Codex conversation environment, invalidating that test's
  conversation binding. The corrected launcher clears those variables. The subsequent
  attempt to reuse the old acceptance after another input was rejected; the native
  agent then attempted to relabel its locator, which auto mode correctly denied.
  A fresh plan acceptance was presented, but auto mode still denied scope binding.
  This is recorded as blocked, not a successful delivery or evidence of a core fix.
- Codex selected capability roots loaded candidate MCP tools after explicit plugin
  mention, but command hooks still came from the installed development snapshot.
  Process-only plugin enablement overrides did not change `hooks/list` results.
  A native-installed `o-harness@oh-acceptance` plugin, disabled for normal sessions
  and enabled only in the disposable project's native configuration, correctly
  exposes all six candidate hooks. With explicit permission, all six were trusted
  through Codex's native configuration writer and the candidate hooks executed.
- Codex's native config writer refused project-local hook trust writes. Automatic
  approval review then rejected user-level hook trust without explicit permission.
  Explicit permission was subsequently received and the scoped trust applied. Remove the temporary
  plugin and marketplace after acceptance and preserve only sanitized evidence.
- Claude standalone review completed through the real interactive CLI: a fresh
  configured Opus/high child was admitted, native lifecycle evidence bound its
  identity, its tool guard was observed, and its blocking arithmetic finding was
  retained with the run completed. The consumer remained clean and unchanged.
  This validates the standalone feedback workflow, not delivery or repair. The
  parent reported an auto-mode denial of manual binding; lifecycle binding supplied
  the actual evidence. Ordinary scoped permission prompts were subsequently approved.
- The next Codex delivery exposed a scope preparation defect: supplying an initiating
  human locator omitted the prepared approval question. The resulting paraphrased
  question failed binding, and the native agent substituted a direct edit without
  OH review. This is a failed acceptance run, even though its arithmetic test passed.
  Preparation now returns its approval question for this path as well; the existing
  immutable-scope regression was extended and passed (1 test, 25.892 seconds).
  Workflow guidance explicitly preserves that question and prohibits substituting
  parent-authored delivery after a binding failure. Syntax checks passed.
- That live Codex run also recorded two post-tool hooks timing out at ten seconds.
  Three direct executions of the same packaged hook took 1.266, 1.531 and 1.375 seconds.
  The intermittent native-host timeout remains unresolved; no deadline was increased.
- Claude's next interactive delivery rewrote the prepared preview, causing exact-plan
  binding to refuse it. Guidance now says to copy the preview unchanged. The native
  agent corrected the display, obtained acceptance and bound the scope, then launched
  its assessment agent. Claude returned a subscription weekly-limit HTTP 429 before
  assessment completed. Delivery remains unverified; the CLI was stopped and its
  evidence retained. No API fallback or subscription purchase was attempted.
- The subsequent Codex run displayed the exact scope question through its native
  asynchronous question tool. A plain chat answer was rejected because the reader
  only considered ordinary assistant messages, while this host saves that display
  as `event_msg/item_completed/AgentMessage`. The reader now accepts completed displays
  from the same conversation before the human answer. Two Windows provenance checks
  passed (0.590 seconds), as did the same Linux checks (0.093 seconds), including
  rejection of foreign, incomplete, late and nonhuman records. Read-only replay of
  the actual failed conversation now finds the correct original question and answer.
  The prior scope-return regression also passed on Linux (1.847 seconds).
  These are parser/unit results; the refreshed live delivery is still in progress.
- With the disposable runtime refreshed, native Codex scope binding succeeded.
  Two assessment attempts stopped on incorrect shell invocation forms; both were
  retained as blocked and the coordinator retried within the existing grant. The
  third used the literal PowerShell form and completed source inspection. Guidance
  now carries shell instructions into the bootstrap prompt and distinguishes a
  recoverable format correction from Stop or denied permission. Implementation then
  changed only `calculator.py`; its actual configured unittest receipt passed with
  return code 0 (890 ms). Native Stop interrupted the parent at the review boundary.
  Resume and independent review are still being exercised; no completion is claimed.
- That run subsequently resumed with the same Continue answer after one bounded
  evidence-delay retry. It preserved the candidate, verification and review allowance;
  the unlaunched reviewer remained cancelled. A fresh independent reviewer returned
  clean, and OH committed the exact reviewed tree locally as `61ea085`. No publication
  occurred. The coordinator omitted the final handoff until prompted, then paraphrased
  its plain-chat question. That handoff failed binding and is not an autonomous pass.
- The corrected handoff exposed a separate provenance defect: Codex stored two identical
  human answers with distinct UserMessage IDs in one turn. OH grouped by turn/text and
  used the earlier timestamp, attaching the newer answer to the old question. Input
  parsing, decision identity and cancellation ownership now preserve the native message
  ID. Existing consumed receipts remain replayable without minting new grants. Native
  question-tool replies retain their existing identity. Guidance distinguishes exact
  plain-chat questions from the native menu's permitted shortened introduction.
  Eight Windows provenance tests passed (8.276 seconds); ten focused Linux provenance,
  checkpoint and cancellation tests passed (54.765 seconds). Read-only replay of the
  actual failing answer now selects the correct question. Syntax checks passed.
  Native verification of this final delta is pending; the next frozen candidate is
  `eeceb6f695aa63e604bd00737c5eace5848196bb+worktree.91d78335a937da9e`.

### Subsequent native evidence and repairs

- The original saved Codex Stop answer was accepted through the actual CLI after
  the message-identity repair. The run is stopped with its reviewed local commit
  retained and no publication. This was a replay of genuine saved evidence, not
  a complete new native delivery pass on one frozen build.
- Frozen candidate `91d78335a937da9e` accepted its initial scope and completed its
  assessment on the first attempt. Its implementation worker failed while manually
  rebuilding PowerShell argument quoting. Cancelled parallel read-only resource
  requests lost their native completion callbacks and then blocked retention. The
  parent subsequently made an unreviewed direct edit; this run failed acceptance.
- Admission now returns the already-bound task context after verifying its hash.
  A formatting-only helper returns the existing literal Bash/PowerShell rendering
  from a structured argument array; native tools still approve and execute commands.
  Missing callbacks for the two narrowly identified read-only helpers cannot block
  retention; unfinished edits, checks and owned processes still do. Five focused
  regressions passed on Windows and Linux (Linux: 9.650 seconds). No live delivery
  pass is claimed for this repair yet.
- A fresh configured native invariant review of the preceding frozen patch retained
  one blocking finding: unqualified `oh-dev exec` could select the wrong data store
  when both hosts used the same live source with different storage. Selection now
  compares effective data destinations as well as source/build, preserving legacy
  isolated-store defaults. The extended regression passed on Linux in 7.636 seconds
  and Windows in 27.594 seconds. A fresh review of the repaired batch is pending.
- Claude delivery remains blocked by its observed subscription weekly limit. Native
  macOS execution remains unavailable (SSH refused and no remote project exposed).
  Neither platform has a complete delivery acceptance result for this candidate.

### Latest verification limits

- Frozen candidate `e480c912a4e85e9b` completed native Codex scope approval,
  assessment, implementation and its configured calculator check (781 ms).
  Native Stop interrupted the coordinator, and a fresh conversation found the saved
  work. Its original Continue was incorrectly rejected: the authority reader kept
  only the compact menu, discarding the complete question displayed immediately before it.
- The reader now considers the assistant displays preceding that human reply.
  Scope, artifact and decision checks retain the actual full display's timestamp
  and saved subject. Intervening human input clears that context. Eleven authority
  and gate tests passed on Windows (16.275 seconds) and Linux (1.526 seconds).
  Syntax checks passed. No additional decision or approval step was added.
- Frozen candidate `e19be433ac29c9da` accepted the original native Continue through
  the CLI and then through the resumed native Codex session. The CLI recovery
  preserved the candidate and review allowance. Codex first supplied its new retry
  message instead of the original answer, corrected that locator itself, and
  continued without asking again. The resumed implementation made no edits and
  reran the configured check successfully (750 ms). Fresh independent delivery
  review returned clean and was retained; OH committed the reviewed candidate as
  `11ad7e5f830e7dba054c5b4481444577be9ec874`. Its final native Stop and take over
  answer was accepted. Durable state confirms stopped, task done, clean checkout
  and no publication. All 101 hooks in this continuation completed (maximum 9520 ms).
  This is mixed-version recovery evidence, not a complete new delivery pass on
  one frozen candidate. The source delta still needs fresh review.
- A fresh configured native invariant review of `e480c912a4e85e9b` was retained clean,
  including closure of the mixed-store selection finding. It predates the display
  context repair and is not a review of that delta.
- The native Stop/recovery evidence includes two files with Windows paths longer
  than 260 characters (maximum 287), successfully written and read by OH's path layer.
  This is real filesystem evidence, not a complete delivery acceptance pass.
- Native hook timeouts remain unresolved: one Interrupt exceeded three seconds and
  one review post-tool hook exceeded ten seconds. Controlled packaged-hook probes
  took 1.322–1.348 seconds; in-process profiles took 0.512–0.739 seconds. These
  measurements do not establish the native timeout's root cause. No further deadline
  increase was made in response to these timeouts.
- No single frozen candidate has yet passed the complete acceptance scenario.
  Claude quota and unavailable macOS execution remain external validation limits.
- The temporary acceptance plugin was uninstalled after this test. Its marketplace,
  six hook trust records and seven temporary project trust entries were removed;
  parsed configuration comparison verified unrelated settings were preserved.
  Test artifacts and native evidence remain local. Normal development activation
  was not refreshed and no OH source changes were committed or published.

## Primary host contracts

- [Codex plugin packaging and trust](https://developers.openai.com/plugins/build/plugins)
- [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- [Codex app-server](https://learn.chatgpt.com/docs/app-server)
- [Claude hooks](https://code.claude.com/docs/en/hooks)
- [Claude programmatic execution](https://code.claude.com/docs/en/headless)

Current documentation is checked against the installed binary/schema where versions
differ. Documentation describes a contract; observed native execution proves that the
installed host and package satisfy it.
