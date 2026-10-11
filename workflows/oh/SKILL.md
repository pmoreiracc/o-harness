---
name: oh
description: Explicit OH workflow through the shared external runner.
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

When OH refuses, the command you were given stays valid until OH carries it out, so the person never types it
again. Fix what is yours to fix and run the same OH command again without mentioning it. When the fix is the
person's call, such as their own uncommitted changes, a merge conflict or another run still open, say what is in
the way in one sentence and ask only with a menu, never in plain chat: anything they type instead sets the command
aside. Do what they pick, with exactly the commands OH names for it, then run it again; run `cancel` only when
they pick dropping the command, and `stop` only when they pick ending the other run. Never commit, stash or
discard their changes unless they pick that, and never switch, pull or create branches for OH: it does that
itself. After opening a pull request, give its link; don't wait for or watch its checks.

Resolve the selected Git checkout; the typed command registers it with OH. If OH says the name is taken or
ambiguous, ask the user which name to use and run `init --name <name>`. If OH says the project has no checks,
save the checks the product's own instructions and CI run, never invented ones, with
`config set checks '<JSON list>'`; give a check `when` paths when the product runs it only for changes there,
so OH runs what is affected. Tell the user which, and run the command again; never replace existing checks here. No OH files, hooks or settings belong in the product.
Read existing product instructions and business documents. Generic OH does not require ADRs.

Give the process introduction once, in the opening progress message before starting the approved work:
an implementation agent builds the selected task, OH runs the project's checks, then a fresh independent
reviewer agent challenges the implementation and code, looking for bugs, weak tests, failure-path defects and invariant violations within the agreed scope. OH repairs blocking findings within the approved scope before
committing, and asks at the next real decision. Say this can take several minutes. For a quick fix,
describe the task preview as the first result for the person to review.
For the introduction, name the concrete review subject: “An independent reviewer agent will
challenge the implementation and code, looking for bugs and gaps in tests or failure handling.”
Use the full role name; “check the result” does not explain this review.
Keep later progress updates brief and factual; use `status` instead of raw internal transcripts.

For already prepared scope, run `start` to verify the native human
invocation and execute its batch. For new task scope, call `run` once to bind the human request and
refresh the base branch before inspecting the work; it returns preparation without starting workers. Then inspect the agreed work and prepare a bounded
task list: in Codex, pass it to the `prepare` tool as `tasks`; in Claude, save it as a JSON object with `tasks`
under the project's external OH directory and run `prepare <absolute-path>`.
Tasks need id, title, instructions and optional needs/dependency IDs, ordered by dependency.
Give each task `difficulty` (simple, standard or complex) and a short `difficulty_reason`: OH picks
the model that builds it from them. Present the
scope and returned `limits` through the Approve / Refine / Cancel menu in `gate`. The host records the click,
which grants exactly that prepared scope. If a menu cannot be shown, the returned `request:` trigger
remains a typed fallback; never echo it yourself as approval. For a product with the
external consumer-v1 profile, `prepare-design <number> [track]` binds its approved design.

The runner owns automatic models, fresh workers, checks, review, final rendering, commits
and batch boundaries. Do not reproduce that loop in the parent conversation. At a batch
checkpoint use the returned actions for continuing, publishing or finishing. Exact choices from the
owning human session are verified by `run`; they never silently renew another allowance.
When OH's output has a `gate`, explain `gate.summary` briefly in chat. For concern/scope decisions,
briefly explain every actual finding and what fixing, accepting, routing or dismissing will do. For a
review renewal, state how many reviews were used, what remains and the exact additional allowance.
`gate.details` retains full history for inspection; it is not popup text. Keep the question itself short.
Concern decisions, review renewal, recovery and batch boundaries do not open a side panel.
If `gate.preview` is present,
show its file link and open the complete review copy beside the question. In Codex, open
`gate.preview` in the right panel with `open_in_codex` when available (target file path
`gate.preview`, placement `right`). In Claude, when `mcp__ccd_view__show_pane` is available, copy
`gate.preview` into your scratchpad directory under its `.md` name, open that copy with `show_pane`
(pane `file`), and still show the original path; the copy is display only, so never pass it back to
OH or write it into the product checkout. Do not paste the document or runner diagnostics into the
question. In other hosts, or when a panel tool is missing or refuses, give the link and a concise
explanation in chat; lack of a panel never blocks the workflow.
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
If OH returns `handoff`, explain that the run ended with unresolved work retained for human PR triage.
A handoff is not a clean review or permission to use the normal OH publication path.
Keep results concise and link saved evidence. Human merging remains separate.

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
Before presenting the reviewed work or completion decision,
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
