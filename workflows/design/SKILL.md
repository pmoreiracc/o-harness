---
name: design
description: Write the design doc for one roadmap initiative through the shared runner.
---
When OH returns `model_notices`, show each new notice once in chat and continue automatically.
Do not ask for fallback approval or repeat the notice at every status poll.

How to run OH commands, such as `config`, `init`, `deliver` or `run`: in Codex, call the o-harness tool of
that name (use `prepare_design` and `pr_summary` for the hyphenated ones) with the checkout's absolute path as
`root`; never run OH from Codex's shell, which cannot write OH's state. In Claude, run the absolute
`<plugin>/scripts/oh` entry supplied by the invoking skill as `<plugin>/scripts/oh --root <checkout> <command>`.
Changing settings (`config set`, `config unset`) is never a tool: run it with `<plugin>/scripts/oh` on either
host, so the person approves it. Stopping a long Codex tool call does not stop OH: call `status` to follow it and
`stop` to end it. Ask for missing details in plain chat. For a decision outside `gate`, put context in chat and keep the question to one short sentence. Use
AskUserQuestion in Claude or the o-harness `confirm` tool in Codex. Describe what the choice does
in the person's work. At routine checkpoints, explain the proposed result and the available actions.
For example: “The task preview is ready: it updates the output and its existing test.” Use the actual
scope and limits from OH. Keep skill names, instruction citations and internal authority diagnostics
out of ordinary product explanations; reserve diagnostic explanations for actual blockers.

Start with the person's task. Recover routine internal problems quietly; do not open with retry
counts or saved-transcript diagnostics. If recovery fails, explain the concrete obstacle and next
step once. Missing-input questions below are plain conversation, not approval menus.

When OH refuses, the command you were given stays valid until OH carries it out, so the person never types it
again. Fix what is yours to fix and run the same OH command again without mentioning it. When the fix is the
person's call, such as their own uncommitted changes, a merge conflict or another run still open, say what is in
the way in one sentence and ask only with a menu, never in plain chat: anything they type instead sets the command
aside. Do what they pick, with exactly the commands OH names for it, then run it again; run `cancel` only when
they pick dropping the command, and `stop` only when they pick ending the other run. Never commit, stash or
discard their changes unless they pick that, and never switch, pull or create branches for OH: it does that
itself. After opening a pull request, give its link; don't wait for or watch its checks.

Resolve the selected Git checkout; the typed command registers it with OH. If OH says the name is taken or
ambiguous, ask the user which name to use and run `init --name <name>`. Designing runs no project checks: OH
checks every plan file it writes against the plan rules itself. No OH files, hooks or settings belong in the product.

The argument is one roadmap slug, such as `/oh-design auth`. Without one, ask “Which roadmap
initiative would you like to design?” in plain chat and end your turn. You may use `plans list`
to show existing initiatives when plan storage is configured; listing is optional and must not
stand in the way of asking. Do not call `run` to establish a waiting state. The person's next
message supplies the slug; then follow the steps below. Never pick one yourself.

Run `plans path`. If it says to choose where plans live, ask the user once:
in the repository (recommended: the design is reviewed and approved through a pull request)
or private (OH's folder, nothing in the repository). Save the answer with
`config set plans.location repo` or `private`. Private plans default to `~/oh-plans/<project name>/`.
Show the exact folder from `plans path`; `plans.private_folder` changes its parent.

Give the process introduction once, in the opening progress message before starting work. Use two or three welcoming sentences.
Name their initiative, explain that a planning agent drafts the document, a fresh independent
reviewer agent challenges the approach, tasks and assumptions against their repository's requirements, and OH repairs blockers before presenting
it for approval. Say this can take several minutes, especially when revision is needed. For example:
“I’ll turn intake-smoke into a plan you can build from. A planning agent will draft it, then an
independent reviewer agent will check the approach and tasks against your repository’s requirements.
OH will repair blocking findings before showing you the plan for approval; this can take several minutes.”
Adapt the name and approval path to this project. Keep later progress updates brief and tied to actual
phase changes or findings; do not repeatedly restate unchanged constraints or inspect raw internal
transcripts to fill a waiting update. `status` is the supported source of progress.

Run `run`. It verifies the native human invocation and starts the design
(repository plans use a new `design/<slug>` branch from `main`, which OH brings up to date and switches to
itself; private plans need no branch). OH reads the roadmap row, a fresh worker writes the prose, and OH numbers
the doc, links it from the row, checks its task list, has it reviewed independently. Repository plans are
committed; private plans wait for your approval. Never write or edit plan files yourself, and never run your own
worker or review loop. Repository plans need the checkout that has `main`: when OH says another worktree holds it, tell the
person to type the command there.

If the status is `approval_checkpoint`, show the private plan path, task count and summary,
then **approve** / **refine: <what to change>** / **Cancel** (discard the unapproved draft and end the run). Approval binds the reviewed
file contents; editing an approved design invalidates that approval. Run `run` after the
human choice. An edited existing private design goes directly to review, preserving the
person's text. A proposed decision remains undecided after approval of the document.
Only drafts and designs edited since approval can be reapproved; frozen and abandoned designs stay closed.
When OH's output has a `gate`, explain `gate.summary` briefly in chat. For concern/scope decisions,
briefly explain every actual finding and what fixing, accepting, routing or dismissing will do. For a
review renewal, state how many reviews were used, what remains and the exact additional allowance.
`gate.details` retains full history for inspection; it is not popup text. Keep the question itself short.
Concern decisions, review renewal, recovery and batch boundaries do not open a side panel.
If `gate.preview` is present,
show its file link and open it in Codex's right panel with `open_in_codex` when available (target
file path `gate.preview`, placement `right`). This is the complete review copy; keep it readable
beside the question. Do not paste the document or runner diagnostics into the question. In other
hosts, provide the same file for the person's editor and a concise explanation in chat; lack of a
panel never blocks the workflow.
In Codex, use `gate.native_ask` with `request_user_input_async` when the native question and an
interruptible wait tool are available. Once the question is accepted, keep the turn open and wait
quietly with `clock.sleep` (at most 60 seconds per call) until the human replies. Do not send a
separate final response while the decision question is pending: tool acceptance is not a human
answer or proof that the menu is visible. After the reply, call OH `run`; OH reads the native answer.
Otherwise use the o-harness `choose` tool, which waits for the click itself.
If the person says the menu is missing, call `status` for the existing run and reopen its current
choice with `choose`, keeping the review copy available. Do not just repeat that a menu should
be there or make them restart the proposal. Typed choices remain available when a host cannot
show either menu.
In Claude, call AskUserQuestion with exactly `gate.ask` and no `answers` field.
After Refine, OH returns `waiting.ask`: ask it in plain chat and end your turn, keeping the review
copy available. Do not open another popup. After the person replies, call `run`; OH reads their
actual message. They do not need to repeat it or add a `refine:` prefix. When `prepare` is returned,
revise the unapproved task list using `feedback` and call `prepare` again. Present the revised preview
and its fresh approval menu before execution. A refinement grants no implementation or extra reviews.
Then run `run` to carry out an execution choice, unless the result is `pr` or `choose` says nothing is left to run.
Never answer for the person. Typed
choices (`gate.choices`) stay valid everywhere, and are the fallback when no menu can be shown.

Use “implementation agent” and “independent reviewer agent” as the role names in user-facing
updates; retain the word “agent” when naming either role. Planning uses “proposal agent” or
“planning agent”. Explain that invariant review challenges correctness, failure paths, tests and
project requirements, as well as the agreed scope; it does more than check unchanged files.

Use `status.progress` to tell the story of the work in your own words. It includes the latest
implementation report and completed review's outcome and findings, with attempt IDs for recognizing
new results. Briefly say what the implementation agent changed, then what the independent
reviewer agent is checking. When findings send work back, summarize the actual issues and
say who is fixing them. For example: “OH’s independent reviewer agent found a missing failure check;
the implementation agent is adding it before the next review.” For planning, name the
proposal or planning agent instead. Give each observed handoff or next task one update.
Use short bullets when several findings matter; if the bounded list omits findings, say how many
more are recorded. Be warm and specific, without inventing activity or using a fixed script.
During an unchanged stage, keep any host-required update brief and useful; avoid a sequence of
“still running” messages, promises to commit, repeated allowances, or “taking longer than expected”.
Reports are claims, findings are reviewer observations, and neither is human authority. Use these
retained summaries, not raw worker transcripts or guesses from uncommitted files. The runner owns
automatic execution; do not reproduce its loop.

Review completion can arrive between status polls. Use `last_review` for the latest finished
review, including at an approval checkpoint before the task is completed. Report each attempt
once: a previous review still present after Refine is history, not a new result. Focus that
update on the person's requested change; do not narrate OH exposing or omitting fields.
Before presenting the reviewed plan or completion decision,
announce that the independent reviewer agent finished, give the actual outcome and round count,
and explicitly say “no findings” when its clean result has `finding_count: 0`. Then report the
commit or saved planning document and present the next decision. For example: “The independent
reviewer agent finished cleanly in one round, with no findings. The change is now committed.
Open a pull request?” A result with accepted concerns must describe those decisions, not claim
no findings. The runner continues automatically; no extra wait or gate is needed for this update.

Report completed invariant review with the recorded `review_rounds` count, including private-plan
results. Explain `gate.summary` once and use the returned menu's short, neutral labels. Approval and PR choices
are the person's decisions, not recommendations. Keep task/review allowances in the preview or chat;
do not append descriptions, commit IDs, destinations or policy quotations to the option labels.
After `status: pr` / `publication`, publish directly. On the normal path the next user-facing message
is the PR number/link and short result, not another confirmation or an announcement of what will be
published. Do not call `run` again or repeat implementation/review.
Use `pr_summary` (Claude: `pr-summary`), preserve the generated body including its hidden review
metadata, and save it to an external temporary file. Do not paste machine JSON into the visible
PR description. Push the
approved branch to its configured remote, and create the PR with that body. Check for an existing PR
first so recovery reuses it. In Codex, attach the resulting PR with `attach_artifact` when available. Report
“PR #<number> opened” with its link, a short summary of the work and verification, and the recorded
`review_rounds` count (for example, “Invariant review passed in 2 rounds”);
never merge. If the host sandbox rejects publication, preserve the grant and completed work, explain
its actual reason and request only the specific authorization it requires using a trusted native human
question. Do not retry a rejected publication through another confirmation tool. Do not rerun tasks or reviews.

Handle the returned status before offering publication:
- `review_checkpoint`: explain the retained findings and offer **Allow N more reviews** / **Stop and take over**. Repository work also offers
  **Stop and hand off to a PR**, which stops with unresolved evidence for human PR triage; it grants
  no completion, review renewal or publication approval. Private plans have no PR handoff.
- `needs_attention`: show the failure and its concrete recovery step, then **retry** / **stop**.
- `findings_checkpoint`: show every finding and exactly the returned menu. Concerns can be
  fixed or accepted; scope can be routed or dismissed, never implemented. A combined menu
  pairs those choices. Never treat prose or silence as a disposition.
After a recovery choice, call `run` again. For `paused`, wait for **resume** or **stop**;
for `pausing` or `stopping`, report the pending state. A stopped run offers no publication.

Only when `completed`, present the returned `plan`:
- a design: its path, task count and `summary`. Say that approving the design means merging
  its pull request for repository plans; private approval is bound to the file contents.
- a decision record: the question, the recommendation in `summary`, and that the design
  waits for a human decision in that record.

Show **pr** / **stop** only when repository files were committed. Private plans have no PR. After the user chooses **pr**, push the branch and open one pull
request whose body ends with the output of `pr-summary`. Never merge it.

For a completed private design, report its path, task count and readiness for `$oh-deliver <number>`.
It has no Git commit or PR, and no extra Stop choice is required when OH returns no gate.
