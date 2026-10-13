# Shared OH execution protocol

Load this once for the active workflow. The runtime owns execution and decisions; the coordinator
handles the conversation, the returned questions and authorized publication.

## Host entry

In Codex, use the o-harness tools with the checkout's absolute `root`. Do not invoke OH through
Codex's shell: that shell cannot write OH's state. In Claude, use the absolute plugin entry
`<plugin>/scripts/oh --root <checkout> <command>` (`scripts/oh.cmd` on native Windows).
Read shared resources through the same `resource` entry. `config set` and `config unset` use the
plugin command on either host; preserve the person's selected settings.

The explicit invocation registers the checkout. If its name is ambiguous, obtain the intended
name and use `init --name`. For Deliver without configured checks, use the project's existing
instructions and CI to register affected checks; preserve existing checks. Planning validates
its documents without running product tests. Keep OH files and settings outside the consumer.

Deliver and Resume can continue saved work in a fresh session on either host, using the same
checkout and OH data. Let the runtime transfer ownership; never restart the task or grant new
allowances to switch hosts. It waits briefly for already-requested Stop/Pause cleanup. If that
cleanup remains pending, retry the valid command after a short wait without asking for approval.
A still-active run must first be stopped or paused; do not take it over while workers run.

A valid command remains pending through routine internal repair. Follow OH's concrete remedy
and continue it within existing authority. For the person's uncommitted changes, conflicts,
missing authority or an external action, explain the actual issue and use the returned choices.
Never discard, commit or stash their edits by assumption. OH owns checkout/branch transitions.
A persistent obstacle must name the next action; it does not create a recovery approval.

## Execution and visibility

Before selection, say you are checking the requested work and saved delivery state. Once the
runtime selects work, introduce its process once; a saved final decision needs no new worker.
Use “implementation agent”, “planning agent”
or “proposal agent”, and “independent reviewer agent”. Independent review challenges correctness,
requirements, failure paths and test claims. Explain that the work may take several minutes.

Keep one execution call in flight. Use yielding/background execution so the conversation stays
responsive: in Codex, a functions.exec wrapper can use `// @exec: {"yield_time_ms": 1000}` and
wait for the same cell in intervals of at most 60 seconds; in Claude, use Bash background execution
and wait for that same command. These waits observe work and never launch another run.

About every 210 seconds, read `status` once and relay a new concrete `progress.focus.message` in
one sentence. Deduplicate by attempt and focus id, including native progress already reported.
Do not invent progress or reread raw transcripts. Report actual transitions/failures when observed:
say which agent finished which work and which agent is starting next. During review, challenge
is in progress, not approval. A spent review allowance means the reviewer has not started.
Use the original execution result when it finishes; inspect status immediately if interrupted or
asked. Show each new model compatibility notice once without a new approval.

`next_action` describes the runtime's next step. If `next_action.resume` is true, call `run` to finish the
already-authorized work. Never reproduce the worker/check/review loop in conversation. The
implementer runs checks and repairs failures; the runtime validates evidence and owns review and
completion. A review allowance is requested only when the next review is ready. Stop cancels
owned work and retains edits; Pause lets the current step finish before waiting.

## Decisions

Follow `gate.how` and its exact question/choices. Explain `gate.summary` briefly. For review
findings, explain each current finding and the effect of the offered choices; read the linked
report for details when needed. For an allowance, state reviews used, remaining work and the
additional allowance. Prior receipts are history, not new results or new authority.

When `gate.preview` exists, link the complete review copy beside the question. In Codex use
`open_in_codex` for that file when available. In Claude, use `mcp__ccd_view__show_pane` if available
with a scratchpad copy, keeping the original path visible; the copy never goes back to OH.
If no panel is available, show the link. Other routine decisions need no side panel.

For ordinary Codex menus, call `choose` directly and await its answer without polling. For
publication, `gate.how` or `choose` returns a native question: use `request_user_input_async`
with exactly `native_ask`, after reporting the result and gate summary. Keep the turn open
until the person answers, using `clock.sleep` in intervals of at most 60 seconds; new input
interrupts the wait. Do not send a final answer after opening the question: ending the turn
can dismiss the unanswered menu. Do not poll OH status or repeat progress while waiting.
After the actual human reply, call `run`; OH verifies it. If the native question or interruptible
wait tool is unavailable, or the person reports a disappearing menu, show the complete question
and typed choices once and wait for a direct human reply instead of reopening that failing menu.
Bare choices are case-insensitive; preserve the original human message as evidence. Do not
replace publication permission with an MCP confirmation. In Claude, use exactly `gate.ask`
with AskUserQuestion, without an `answers` field. A cancelled question or silence grants nothing.

After Refine, ask `waiting.ask` in ordinary conversation and end the turn. The next message
supplies the refinement; call `run` to retain it. If OH returns `prepare`, revise only the
unapproved task list and call `prepare` again. The resulting preview receives its own approval.
Do not make the person repeat their answer. If an ordinary menu is missing, refresh status and
reopen its current question; preserve the existing work and choice. For a disappearing publication
question, use the direct typed fallback above instead of repeating the failed interaction.

## Results and publication

Report the recorded review outcome and round count once; say “no findings” only for a clean
receipt with none. Give a short whole-change summary, the actual verification and any unresolved
limitations. Link `report` for readable receipts. Author claims never mean completion; only
native completion updates task marks. Never implement findings outside the approved scope.

When `gate` is absent and `next_action.kind` is `publish`, publication is already authorized.
Use `pr_summary` (Claude: `pr-summary`), preserving its entire body and hidden review metadata in
an external temporary file. It revalidates the reviewed commits and destination. Push only
`publication.head` to `refs/heads/<publication.branch>` on `publication.remote`, using quoted
arguments. Check for an existing PR, then create or reuse one against `publication.base_branch`;
use `gh pr create --body-file` for the saved body. In Codex attach its URL with `attach_artifact`.
Report the PR link, then observe its checks with `gh pr view --json headRefOid,statusCheckRollup,url`.
Keep each observation compact: current head, check names and states; read job logs only to
diagnose a failure. Do not accumulate complete check responses in the conversation.
Bind observations to that head: if it changes, discard the previous head's readiness result and
inspect the new head's checks. The saved OH review still covers only its recorded commit;
do not describe a different head as independently reviewed. Wait responsively in intervals of at most 60 seconds while checks
are queued or running; report meaningful changes, not every poll. Do not use fail-fast watching
that hides remaining check results. Local checks or a successful push do not establish CI success.
If no checks appear, allow one short wait for registration, then report that CI was not observed;
never call an empty check list a pass. Report cancelled, failed, skipped or action-required checks
honestly; do not call the PR ready when verification failed or is still unresolved.

For failures, read the relevant job log and explain the cause and smallest concrete correction.
Do not rerun unchanged failures or edit code as part of this publication step. A correction must
go through implementation, verification and independent review under appropriate task authority;
publication permission alone does not authorize edits. If an external action or unavailable CI
prevents completion, name the check and next step. When interrupted, reuse the PR and inspect its
current head rather than republishing. End with the PR link, delivered work and actual CI result.
Human merging remains separate. Never rerun implementation or reviews to recover publication.

For `next_action.kind: observe_publication`, the branch contains later commits beyond OH's
publication grant. Find the existing PR for the recorded branch/destination and observe its
current head and CI as above. Do not push, create a PR, call pr_summary or claim those later
commits are reviewed. If no matching PR exists, preserve the branch and explain that the later
work needs an authorized review/publication path; this resume grants no new work or publication.

If the host rejects publication, retain the work and grant, explain its actual reason and obtain
only the specific missing native authorization. Never bypass a rejection through another tool.
A returned `handoff` is unresolved work for human triage, not completion or publication authority.
For `blocked`, explain the actual obstacle and concrete action needed, then continue within the
same authority after it is resolved. No routine Retry question is offered.
