# Real CLI acceptance

Run native subscription sessions against a frozen candidate in disposable consumers.
The developer or authorized operator sends actual host choices. Verify files, saved
decisions, checks, reviewed commits and PRs. Fixture setup or an agent's final message
alone cannot establish a pass. Typed CLI choices prove the CLI path.

## Sign in once on each Mac

Run `python3 integrations/e2e_fixture.py login-codex` and complete the native ChatGPT
sign-in. The launcher always uses `~/.local/share/oh-dev/acceptance/codex-home` for new
trials. Codex manages that profile's subscription login. Repeat only if it expires or
you sign out. Finish one candidate's sessions before setting up another on this profile.

## Prepare once for a candidate

Choose model names available to the subscriptions. Both the coordinator and fixture OH
roles use the specified model; the catalog uses medium effort and sanity uses low effort. Both allow two consumer review rounds.
The two-round limit belongs to the consumer workflow being tested. It is separate from
the one independent review of OH's implementation. Never renew the fixture limit automatically.

```sh
python3 integrations/e2e_fixture.py prepare --codex-model MODEL --claude-model MODEL
```

The default suite is sanity. This prints a fresh temporary directory and frozen snapshot. It creates separate delivery, planning and choice repositories per host (plus a Design
repository for sanity), separate OH data, private planning space, and an
isolated candidate configuration. It launches nothing and never activates normal oh-dev.
`trial.json` identifies the exact candidate, fixture root and build. Keep that root until
the trial finishes. A source change requires a new candidate; do not relabel an old pass.

Open the installed native CLI in the corresponding fixture repository, using the candidate
plugin and fixture data. Verify the available controls with the actual installed CLI's help.
For Codex, run `python3 integrations/e2e_fixture.py setup-codex TRIAL` once per
candidate. It checks the dedicated login, applies the fixture configuration, installs
the local plugin and verifies its version and source. Launch checks the selected plugin
again, including on resume. Review changed hook definitions in the native `/hooks`
screen for this profile. Do not copy authentication or synthesize hook trust.
For Claude, load `<build>/claude/plugins/o-harness` with `--plugin-dir`, use the supplied
`claude-settings.json` and `--setting-sources project,local`, and use normal subscription authentication.
Excluding project sources also excludes `CLAUDE.md`; confirm the fixture memory appears
in native `/context` before testing project-specific instructions. User settings remain excluded.
Both hosts need `OH_DATA_HOME` and `OH_DEV_NORMAL_DATA_HOME` set to `<trial>/data`.
Clear inherited conversation/worker identifiers so a trial cannot impersonate its parent.
Use normal native permissions; no bypass flags or API credentials. Keep owned sessions
available across turns; do not impose a short timeout that discards a valid decision.
If the interactive test terminal cannot deliver a reply, preserve the CLI-origin session
and use supported `codex exec resume SESSION_ID 'actual answer'` after closing that owned
terminal. The fixture instructions require the plain-chat fallback in noninteractive turns,
where there is no operator async-card surface. Record this limit; it proves native typed
decisions, not clickable cards. Never run two coordinators for the same conversation.

The helper can execute those native commands with the isolated environment. It has no
agent loop and supplies no answers automatically:

```sh
python3 integrations/e2e_fixture.py launch TRIAL --host codex --scenario delivery --prompt '$oh-deliver 0001'
python3 integrations/e2e_fixture.py launch TRIAL --host claude --scenario delivery --prompt '/o-harness:oh-deliver 0001'
```

For a saved native conversation, pass `--resume SESSION_ID --prompt 'actual answer'`.
Only do so after its prior native process has exited. Native approval review remains
enabled; the launcher does not bypass permissions or hook trust.

## Live sanity

Use the `sanity` fixture for the pre-PR run. Run the following slices in both installed
Mac CLIs. Independent projects and hosts may run concurrently. During development
choose the affected slices; add a focused real CLI regression for a change these do
not exercise. After the single implementation review run every slice on the final candidate.

| Slice | Action in the real host | Check the effect |
| --- | --- | --- |
| Propose | In `planning`, propose the small greeting initiative described in P and accept its native preview. | The prospective row validates before the first approval; one approval records the same semantic addition in M1, which validates and passes review. Syntax-only repair does not ask again; application files stay at baseline. |
| Design | In the independent private `design` fixture, invoke Design for the pre-existing greeting initiative. Accept the actual reviewed design. | The design and roadmap validate and Deliver selects the approved task. Application files stay at baseline. |
| Delivery | Give the delivery fixture a private test remote and a passing hosted check before entry. Invoke Deliver 0001, choose Core, then send Stop at the selection boundary before workers, with no prepared Stop question. Exit, resume in a fresh conversation, then deliver task 1, review it and select publication. | Stop preserved the grant with zero attempts; one real Continue in a fresh session enters the authorized phase in the same turn without an operator nudge or allowance renewal. Report any extra nudge as an assisted recovery, not an autonomous pass. The first assessment reaches supported native permission directly when private state is outside writable roots, without a throwaway worker; a later helper uses the same supported access. Only the selected task edits `answer.txt`, the actual check and fresh review precede completion. The menu itself names the completed work and offers the next runnable Core task, the PR destination and Stop. Select publication once. A second question for the same effect fails this slice even if a later retry publishes. Exactly one PR links the reviewed HEAD and passes CI; the next Core task and excluded track remain untouched. |
| Quick fix | In the choice project request a one-file quick fix, inspect the actual bounded scope, and decline it in the prepared scope menu. | One actual Stop binds a scope decline. Verify its receipt, no new run, no implementation, approval, edits or publication. |

The independent Design fixture contains a normal roadmap initiative only. The host still drafts, checks, reviews and accepts its design. Nightly P also exercises the direct handoff from the newly created proposal.

For outside-state helper acceptance, leave the first assessment's native permission
request pending across a coordinator wait before approving it. Verify the same child
and admission continue, with no timeout-driven interruption or replacement. Exercise
a later helper and a fresh session too. This extends the existing delivery slice:
time spent awaiting a real permission answer must not consume a throwaway worker.
In a separate delivery variant, explicitly refuse native helper permission and verify
the terminal attempt is retained without another child retrying the refused operation.
This refusal variant belongs in the nightly catalog; exercise it during permission
repairs and report its cost separately. Preserve real Stop and revoked-attempt coverage.

Use a unique base branch in a dedicated private fixture repository, set its name as
the fixture project's configured base, and push only this trial's starting tree to it.
Use `python3 check.py` for hosted sanity. For scenario C also require release readiness.
After the run close the fixture PR unmerged and delete only its trial branches.
In sanity, Core has a second runnable task so all three checkpoint actions are available. The second track exists only to test selection; it
is outside the chosen scope. Fault injection, additional batches and failed hosted CI
belong to the longer catalog. Measure preparation, each slice, slowest host and overall
wall time. Report sanity separately from additional targeted/nightly variants, per host,
and retain overall wall time. State whether each duration includes setup, human approvals,
hosted CI and recovery. Use existing scenario boundaries and timestamps; never repeat an
otherwise valid scenario just for a nicer timing number. Preserve failed first answers
after recovery and link unrelated known failures, explaining their effect on scoped readiness.
Timings guide optimization; an overrun never converts a pass into a failure.
For a new E2E case document whether it protects an essential ordinary workflow (sanity
and nightly) or adds a variant or fault (nightly). Prefer extending an existing path.

## External merge re-entry

The `merged` fixture on each host exercises this additional sanity and nightly path.
Use a unique base in a dedicated private test repository. Deliver Core task 1 and
choose Stop at its completed checkpoint. The operator opens and merges a fixture PR
through native Git/GitHub, leaving OH's run unpublished. In a fresh CLI invoke Deliver
for the same design. It must fetch the base, identify the merged batch and select task 2
without a Resume/discard question for task 1. Send the first actual Stop without a prepared question before task 2 workers and inspect
that its grant is exactly task 2, product files still reflect task 1 only, and the old
journal keeps its original allowances/results/publication state. No record is fabricated
to make OH look like it published. The fixture-only merge is part of this test.

This extends sanity because returning after a human merge is a fundamental delivery
entry. It adds one tiny implementation/review and an external hosted merge per host.
Additional dirty/unmerged variants have focused deterministic coverage.

## Nightly live regression

Prepare with `--suite catalog`. Run P/D/Q/C below on both Mac CLIs using fresh consumers.
D and C share a real PR. The broader D includes the same delivery fundamentals with an
interruption and an extra task batch; Q covers selection, Stop and quick-fix refusal.
The catalog also covers changes graduated from incident regressions. Record gaps and
extend this catalog when adding a distinct workflow option.

A local Codex project automation schedules the live catalog at 03:00 America/Sao_Paulo.
It needs an awake authenticated Mac, both installed subscription CLIs, GitHub access
to the dedicated private fixtures, and native hook review when definitions change.
The separate GitHub Actions schedule covers deterministic Linux/Windows regression.
Live runs test a clean isolated checkout of fetched main. Leave normal oh-dev and
developer checkouts alone. If another trial owns the acceptance profile, report the
nightly as deferred; never displace that trial or report skipped work as passed.
Record each attempted outcome with a sanitized report, triage failures against the
tested revision, and clean owned resources. No live nightly status is a PR or release
dependency. A confirmed relevant defect still requires a release decision.

## P — Propose and Design

Use `<host>-planning`, which has a private roadmap with one milestone and no initiative.
Ask the installed Propose skill to add an initiative named `greeting` to change
`answer.txt` from `before` to `after`, preserving the other files. Approve the actual
additions through the native question, then invoke Design for `greeting` and accept
the actual reviewed private plan. A missing product decision must remain a real question.

Check: proposal preview precedes writes; actual acceptance binds; the roadmap and approved
design exist in the fixture's private plans; tasks/checks describe the tiny requested
outcome; native analysis and independent review completed; application files and Git HEAD
remain unchanged; no PR or extra completion approval is invented. Run the packaged
`plans check` and retain the actual paths and verdicts in the result report.
Use `inspect --scenario planning` to confirm the completed design is actually approved
and selectable by Deliver. A completed run with an undeliverable draft fails this scenario.

## D — Deliver, recovery and batches

Use `<host>-delivery`. Invoke the installed Deliver skill for `0001`. Task 1 changes
`answer.txt`; task 2 changes `marker.txt`; the task allowance is one at a time.
The delivery fixture instructions ask the FIRST implementation child to attempt one
missing-file read and return unfinished without edits; subsequent authors work normally.
This is a deliberate unfinished-author test, not a claimed live service outage.
Invoke Deliver with only its supported design/track arguments; do not append a second
paragraph of test directions to a slash-command argument. The fixture owns those directions.

Check: the first unfinished attempt and failed read remain visible; a fresh author finishes
task 1 without a new scope/allowance grant; checks and a fresh consumer review precede its
commit. The checkpoint offers next batch, publication and takeover. Stop there, record the
committed HEAD and remaining allowance, then resume in a fresh native session. Continue the
next batch through its actual decision. Exactly tasks 1 and 2 finish; original evidence,
commit and spent allowances survive. No third task or unrelated file change is allowed.

For catalog delivery, configure a dedicated private GitHub fixture repository before
starting D: push only this fixture's initial main, set origin, then let normal publication
create its one PR after the actual checkpoint choice. Never use a real product repository.
Check the clickable link, saved URL and actual remote HEAD. Do not merge the test PR.

## Q — Selection and refusal

Use `<host>-choice`. Invoke Deliver `0001`, select Core through the actual track question,
and confirm only task 1 is selected. Stop before implementation using the native Stop
decision. Inspect that application files and grants were not expanded. Then request a tiny
new quick fix and choose Stop and take over once. Check the decline receipt, the previous
stopped journal and unchanged files. For recovery, inspect the path list through its inspection
link, then choose Continue once. Check the same grant is retained. At a checkpoint
with only Stop, require a single direct chat answer. Resume a pending question only through supported
host controls. Missing clickable cards may use OH's documented direct-reply fallback;
record which surface was actually exercised.

## C — Published CI failure and repair

Before D, add a minimal GitHub Actions workflow to its fixture: run `python3 check.py`,
then require `release.txt` to equal `ready\n`. Initial `pending\n` deliberately fails only
the hosted readiness check. D's tasks exclude that file. This must be a real hosted failure.

After publication, choose Investigate CI failures. Confirm logs were inspected and the
cause, proposed change and verification are understandable. `release.txt` must still be
pending until the separate actual repair approval. Approve changing only that file to
`ready\n`, then observe implementation, checks, consumer review and update of the SAME PR.
Follow actual GitHub checks to green on the updated head. No weakening the check, additional
approval to prepare the proposal, duplicate PR or fabricated successful CI observation.

On Claude, exercise the repair approval through the native plan viewer with normal auto
permissions. Inspect the separate actual acceptance and the subsequent scope-approval
call. A generic menu approval does not establish this path. If the host denies the call,
retain the denial and distinguish host permission classification from OH rejecting the
native evidence; do not bypass it or add blanket permissions. This fault variant remains
in the nightly catalog and runs during development of approval repairs.

For commit/PR presentation changes, run D/C in a project whose instructions require
Conventional Commit subjects and a PR template with named sections. Add a commit hook
that checks the convention and rewrites the subject while preserving evidence trailers.
Verify both the task and repair commit's actual subject, reviewed tree, parent and
trailers. Inspect the submitted GitHub title/body for the instructed format, verified
facts and unchanged publication identity. Recover an interrupted completion/publication
against that same PR. Also run ordinary D with OH defaults. These additional presentation
variants belong in the nightly catalog; they extend D/C without adding another sanity
journey. Record their measured cost separately.

## Menu coverage in the live catalog

Use the real question on each host, with a readable introduction and action descriptions.
The question must make sense without an internal reference. Vary the title and the order
of options between hosts. Inspect the native call, the first actual answer and its effect.
Record a repeated question, rejected valid answer or extra grant as a failed path even if a
later attempt succeeds. Run the affected variants during development; keep the extended
paths below in the nightly catalog.

| Exercise in a disposable consumer and useful context | Outcome to inspect | Golden-reference comparison |
| --- | --- | --- |
| P: refine or cancel a proposed roadmap addition before accepting the revised preview; discuss a Design choice before approving private Design | Discussion and cancellation grant nothing. Only the accepted additions and reviewed design become usable. | Propose step 3 separates Approve, Refine and Reconsider; only the accepted preview is written. Design leaves consequential choices to the person. OH private approval binds reviewed artifacts rather than a merge. |
| D: select a named design/track; at the first completed task choose the next batch, then publish the completed work | Only the selected track and displayed task window run. One publication answer opens one PR at the reviewed commit and destination. | Deliver task checkpoints bind the exact next window or publication. OH Stop preserves work locally without pushing; the reference’s Stop-without-PR push is not OH policy. |
| D recovery: leave a harmless uncommitted fixture file, stop, resume, and select the explicit discard action (including a readable Start fresh label) after inspecting the branch, restart base and affected file list | Continue preserves existing edits; on a separate disposable run an actual restart discards only the disclosed contents. Changing those contents before acting invalidates restart. | The shared recovery contract repairs operations within existing authority. A new choice never replenishes a task or review window; destructive cleanup still needs its disclosed effect. |
| Q: decline a new fix with an earlier run stopped; accept a distinct one-file fix through the normal plan or menu in a fresh fixture | Decline never approves anything, starts a worker or modifies the earlier journal. Approval executes only the actual scope. A dismissed question remains pending. In the Claude plan viewer decline using feedback and verify that the scope stays unapproved and no worker runs. The host records a rejected plan separately from a menu Stop. For a technical approval retry, use the same actual native answer without a copied decision ID; verify the same run, unchanged journal/grants and no duplicate attempts. Do not ask again. | Human-only grants and non-granting cancellation are retained. OH also supports bounded quick fixes and native plan acceptance; it does not require the reference’s exact bare-command presentation. |
| Review: use a tiny manual change with a real optional concern. Request review, choose Fix concerns, and on a separate concern choose acceptance. If a repair would exceed the task or review allowance, decline it, then exercise an explicit bounded grant in a separate trial | Acceptance records the reviewed subject. Fix concerns repairs within the grant. A supporting repair or additional round requires its own actual choice; observe the exact changed scope or count. | Deliver’s concern matrix separates fixes from exact-tree acceptance and explicit review-window grants. OH standalone feedback itself grants no repair or completion authority. |
| C: select investigation of a failed fixture check, inspect the actual cause, then decline or approve the proposed correction. When a failed hosted check is safe to rerun unchanged, select rerun in a separate trial | Investigation grants diagnosis; only the repair approval can change the PR. Rerun repeats the intended check at its existing head. | Finish-with-PR follows actual current-head checks and preserves the task boundary during repairs. OH explicitly separates investigation, repair approval and unchanged-head rerun. |
| Other routing and configuration choices: for a touched skill, exercise its normal entry with multiple eligible options; choose an option, discuss, or dismiss on the native surface | Verify the resulting selected work or setting. Discussion and dismissal leave it unchanged. | Consequential product choices stay with the person. Selection identifies work; discussion, dismissal and configuration prose never create a task or publication grant. |

Compare against `my-geoffrey` at `b508bdc`: its Propose, Design and Deliver skills,
`codex-gate.sh`, and `round-ledger.sh`. Retain native provenance, finite windows and
non-granting alternatives; its product policies and exact-command menus are not OH requirements.

For each row, record the actual host/version and candidate, trigger, readable subject,
first answer, observed effect and any remaining host limit in the result report.
Record a variant as unexercised if its prerequisite never occurred. The ordinary
Propose, Design, three-way Delivery checkpoint, recovery and quick-fix refusal remain
in pre-PR sanity. Extended variants reuse those fixtures and may run independently.

## Evidence and finish

Use the read-only fixture observation command at checkpoints:

```sh
python3 integrations/e2e_fixture.py inspect TRIAL --host codex --scenario delivery
```

For a published sanity delivery it also requires a three-way checkpoint and exactly one recorded publication answer. Inspect the native presentation for clarity.
It checks retained report hashes and prints files, actual task IDs, attempts, status and
publication evidence. It is not a pass oracle. The operator also inspects native questions,
the original delivery run when C creates a correction run, and actual GitHub check results.
Record host/CLI versions, source/snapshot, model, scenario, outcomes, duration and observed
usage (unknown when unavailable), including first failures and diagnostic reruns. Keep raw
transcripts and state private and outside Git. A passing exit code or an agent's final prose
alone cannot establish acceptance. Sanity is a subset, never a claim that the full catalog ran.

After acceptance: exit each CLI and verify its owned workers/processes ended; close the
fixture PRs without merging and remove task-owned remote branches; remove the fixture root
and its exact inactive snapshot. Use Codex's native `delete SESSION_ID` in the
dedicated acceptance home for this trial's saved conversations, including child sessions.
Retain the acceptance profile and its subscription login for the next trial. Remove only this trial's
host project history if it was stored outside the isolated root, using native controls.
Keep a concise sanitized result report outside the temporary root before deleting it.
No wildcard cleanup of other OH projects, normal settings, drafts or active snapshots.
