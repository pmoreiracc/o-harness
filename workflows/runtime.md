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

A valid command remains pending through routine internal repair. Follow OH's concrete remedy
and continue it within existing authority. For the person's uncommitted changes, conflicts,
missing authority or an external action, explain the actual issue and use the returned choices.
Never discard, commit or stash their edits by assumption. OH owns checkout/branch transitions.
A persistent obstacle must name the next action; it does not create a recovery approval.

## Execution and visibility

Introduce the selected work and its process once. Use “implementation agent”, “planning agent”
or “proposal agent”, and “independent reviewer agent”. Independent review challenges correctness,
requirements, failure paths and test claims. Explain that the work may take several minutes.

Keep one execution call in flight. Use yielding/background execution so the conversation stays
responsive: in Codex, a functions.exec wrapper can use `// @exec: {"yield_time_ms": 1000}` and
wait for the same cell in intervals of at most 60 seconds; in Claude, use Bash background execution
and wait for that same command. These waits observe work and never launch another run.

About every 210 seconds, read `status` once and relay a new concrete `progress.focus.message` in
one sentence. Deduplicate by attempt and focus id, including native progress already reported.
Do not invent progress or reread raw transcripts. Report actual transitions/failures when observed.
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
with exactly `native_ask`, then end the turn while waiting. After the actual human reply, call
`run`; OH verifies it. If the native question tool is unavailable, show the complete question
and typed choices once and wait for a direct human reply. Do not replace publication permission
with an MCP confirmation. In Claude, use exactly `gate.ask` with AskUserQuestion, without an
`answers` field. A cancelled question or silence grants nothing.

After Refine, ask `waiting.ask` in ordinary conversation and end the turn. The next message
supplies the refinement; call `run` to retain it. If OH returns `prepare`, revise only the
unapproved task list and call `prepare` again. The resulting preview receives its own approval.
Do not make the person repeat their answer. If a menu is missing, refresh status and reopen
its current question; preserve the existing work and choice.

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
Report the PR link and brief result; distinguish local verification from any observed remote CI.
Human merging remains separate. Never rerun implementation or reviews to recover publication.

If the host rejects publication, retain the work and grant, explain its actual reason and obtain
only the specific missing native authorization. Never bypass a rejection through another tool.
A returned `handoff` is unresolved work for human triage, not completion or publication authority.
For `blocked`, explain the actual obstacle and concrete action needed, then continue within the
same authority after it is resolved. No routine Retry question is offered.
