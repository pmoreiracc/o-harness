# Real CLI acceptance catalog

These are explicitly launched subscription tests, never scheduled AI jobs. The operator
may be the developer or their authorized development agent using native CLI tools. Choices
must travel through the actual host; never write synthetic approvals or successful reports
into OH state. An automated test choice is not evidence of a physical human click.

## Prepare once for a candidate

Choose model names available to the subscriptions. Both the coordinator and fixture OH
roles use the specified model; all fixture roles use medium effort and two review rounds.
The two-round limit belongs to the consumer workflow being tested. It is separate from
the one independent review of OH's implementation. Never renew the fixture limit automatically.

```sh
python3 integrations/e2e_fixture.py prepare --codex-model MODEL --claude-model MODEL
```

This prints a fresh temporary directory and frozen snapshot. It creates three repositories
per host (delivery, planning, choice), separate OH data, private planning space, and an
empty Codex authentication profile. It launches nothing and never activates normal oh-dev.
`trial.json` identifies the exact candidate, fixture root and build. Keep that root until
the trial finishes. A source change requires a new candidate; do not relabel an old pass.

Open the installed native CLI in the corresponding fixture repository, using the candidate
plugin and fixture data. Verify the available controls with the actual installed CLI's help.
For Codex, use the fixture's `codex-home` as `CODEX_HOME`, run
`codex plugin add o-harness@oh-dev` in that environment, and start a fresh CLI session.
Declaring the marketplace and enablement alone does not install its plugin. Sign in through the native login
(or use an explicitly authorized temporary copy of existing subscription authentication),
and review the candidate hooks in `/hooks`. Do not copy or synthesize hook trust.
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

## Sanity and focused development

Live sanity is scenario D through its first completed-task checkpoint, followed by Stop.
For shared execution changes, resume it and complete the second task too. Scenario Q is a
cheap addition for menu/entry changes. Run only the scenario relevant to a focused edit;
the full catalog is P, D, Q and C on both Mac CLIs at final acceptance. Reuse D's published
branch for C rather than delivering another project. Test tasks remain sequential.

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

For final catalog acceptance, configure a dedicated private GitHub fixture repository before
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
(including copied authentication) and its exact inactive snapshot. Remove only this trial's
host project history if it was stored outside the isolated root, using native controls.
Keep a concise sanitized result report outside the temporary root before deleting it.
No wildcard cleanup of other OH projects, normal settings, drafts or active snapshots.
