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
python3 integrations/e2e_fixture.py prepare --suite sanity --codex-model MODEL --claude-model MODEL
```

This prints a fresh temporary directory and frozen snapshot. It creates three repositories
per host (delivery, planning, choice), separate OH data, private planning space, and an
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
not exercise. After the single implementation review run all three on the final candidate.

| Slice | Action in the real host | Check the effect |
| --- | --- | --- |
| Planning | Follow P below in the private planning project. Approve the tiny greeting proposal and reviewed design. | Private documents validate; design is accepted and selectable for Deliver; application files remain at baseline. |
| Delivery | Give the delivery fixture a private test remote and a passing hosted check before entry. Invoke Deliver 0001, choose Core, then Stop at the selection boundary before workers. Exit, resume in a fresh conversation, then deliver task 1, review it and select publication. | Stop preserved the grant with zero attempts; resume preserves it, only the selected task edits `answer.txt`, the actual check and fresh review precede completion. The checkpoint identifies excluded other-track work. One PR links the reviewed HEAD and passes CI. |
| Quick fix | In the choice project request a one-file quick fix, inspect the actual bounded scope, decline it. | No implementation, approval, edits or publication. |

Use a unique base branch in a dedicated private fixture repository, set its name as
the fixture project's configured base, and push only this trial's starting tree to it.
Use `python3 check.py` for hosted sanity. For scenario C also require release readiness.
After the run close the fixture PR unmerged and delete only its trial branches.
In the sanity delivery project the second track exists only to test selection; it
is outside the chosen scope. Fault injection, additional batches and failed hosted CI
belong to the longer catalog. Measure preparation, each slice, slowest host and overall
wall time. Timings guide optimization; an overrun never converts a pass into a failure.
For a new E2E case document whether it protects an essential ordinary workflow (sanity
and nightly) or adds a variant or fault (nightly). Prefer extending an existing path.

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
new quick fix; dismiss or decline its proposed scope, and confirm it makes no changes and
does not treat dismissal as acceptance. Resume a pending question only through supported
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

## Evidence and finish

Use the read-only fixture observation command at checkpoints:

```sh
python3 integrations/e2e_fixture.py inspect TRIAL --host codex --scenario delivery
```

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
