---
name: propose
description: Route one idea to a roadmap row, a task in an approved design, or an improvement, through the shared runner.
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
ambiguous, ask the user which name to use and run `init --name <name>`. Proposing runs no project checks: OH
checks every plan file it writes against the plan rules itself. No OH files, hooks or settings belong in the product.

The argument is the idea in the user's words. Without one, ask “What would you like to propose?”
in plain chat and end your turn. Do this before calling `run`, reading saved conversation evidence or
choosing plan storage. The person's next message supplies the idea; then follow the steps below.
No saved waiting record is needed to ask or answer. Never propose something on their behalf.

Run `plans path`. If it says to choose where plans live, ask the user once:
in the repository (recommended: plans are reviewed and approved through pull requests) or
private (OH's folder, nothing in the repository). Save the answer with
`config set plans.location repo` or `private`. Private plans default to `~/oh-plans/<project name>/`; show `plans path` and allow `plans.private_folder` to choose another parent.

Give the process introduction once, in the opening progress message: a proposal agent reads the project
and finds where this idea belongs, then OH shows exactly what is proposed. Saving and independent
review follow approval when documents are needed. Say this can take several minutes. Keep later
updates brief and tied to actual progress; the supported `status` output supplies the facts.

Run `run`. It verifies the native human invocation; a fresh worker reads the
roadmap, designs, decisions and code and routes the idea; OH works out exactly what it would write, writes
nothing yet, and stops for the person's answer. After **approve**, OH writes it (for repository plans, on a new
`propose/<topic>` branch from the configured base branch, which OH brings up to date and switches to itself; private plans need no
branch), checks the plan rules and has the written change reviewed independently, then commits repository
plans. If the review changes where the idea goes or what is written, OH asks the person again with the new
lines. An improvement or an unclear idea writes nothing and has no review. Never write or edit plan files
yourself, and never run your own worker or review loop. Repository plans need the checkout that has the base branch: when OH says another worktree holds it, tell the
person to type the command there.

When the returned status is `approval_checkpoint` and a `gate` is present, explain the proposal
briefly in chat and put the following details in the review copy:
1. what OH understood the idea to be (`understanding`);
2. the route and its one-line `reason`, with the `evidence`;
3. exactly what OH will write: `lines`, into the files in `intent`, and `writes`, what those lines don't say (the
   milestone a row joins, a new milestone's "Done when", a task's track, a proposed decision record's full text
   and recommendation); for an improvement or an unclear idea, the `text` instead;
4. the choices, as the menu in `gate` (see below) or typed: **approve** (OH writes exactly these lines, has them
   reviewed and commits repository plans), **Refine** (ask for changes in chat; OH revises the preview), or **Cancel** (end this proposal without saving it or asking another question). OH continues after the person chooses.

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
Before presenting the reviewed proposal or completion decision,
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
approved branch to its configured remote, and create the PR with that body, explicitly targeting
`publication.base_branch` from the returned checkpoint (`gh pr create --base <branch>`). Check for an existing PR
first so recovery reuses it. In Codex, attach the resulting PR with `attach_artifact` when available. Report
“PR #<number> opened” with its link, a short summary of the work and verification, and the recorded
`review_rounds` count (for example, “Invariant review passed in 2 rounds”);
never merge. If the host sandbox rejects publication, preserve the grant and completed work, explain
its actual reason and request only the specific authorization it requires using a trusted native human
question. Do not retry a rejected publication through another confirmation tool. Do not rerun tasks or reviews.


After **approve**, run `run` again. If it stops at `approval_checkpoint` again, the review moved the idea: present
it the same way. Then show **pr** / **stop** when something was committed;
after **pr**, push the branch and open one pull request whose body ends with the output of
`pr-summary`, saying plainly what was added and where. Never merge it. For an approved
improvement, say it can be delivered directly; nothing was written.
