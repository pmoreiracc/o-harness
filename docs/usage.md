# Using OH

OH does nothing until you invoke one of its commands. An ordinary prompt such as "design a
login page" never starts OH. Claude uses `/`, Codex uses `$`. The first command in a checkout
registers it.

You type a command once. If something is in the way, the agent fixes it and OH carries the
command out, without asking you to type it again. Only choices that are yours reach you, as a
menu: for example, what to do with your own uncommitted changes, or whether to stop a run that
is still open. Answer in the menu: if you type something else instead, OH sets the command
aside and tells you so. A new command replaces one that hasn't run yet.

In Codex you can select an OH skill or type its command. OH reads the native human message;
the skill instructions added by the host do not count as another request. If either host is
still saving the evidence, OH retries the read briefly without asking you to repeat yourself.
A missing transcript from another chat cannot block a verified current request. Its unverified
locator grants nothing; if the source becomes readable later, OH checks it against the newer
request before doing anything. A newer human message supersedes an older pending command, and retrying an already consumed
command does not grant work twice. An unrecognized invocation cannot stand in for a stopped
run: use `status` to inspect that run. These paths are covered by
`test_native_transcript_binds_host_turn_text_and_checkout`,
`test_desktop_fallback_uses_only_current_native_human_turn`, and
`test_a_real_command_runs_through_the_launcher`.

## Plan: oh-propose and oh-design

`/oh-propose <idea>` finds where the idea belongs, such as
`/oh-propose search across my notes`. A fresh worker reads your roadmap, designs, decisions
and code and picks one route:

- a new **roadmap row** (and a new milestone, or a proposed decision record when where it
  belongs is genuinely contested);
- a **task** added to an approved design;
- an **improvement** to existing behaviour, which needs no document;
- or **unclear**, with the two readings and the question to answer.

Proposal, design and quick-fix approvals provide a complete Markdown review copy in OH's
external storage. In Codex Desktop, OH opens it in the right panel and uses the small native
question, so you can keep reading and scrolling while deciding. The question names that exact
preview through a short checkpoint reference. OH verifies the displayed question and native human answer, records the choice once,
and refuses an edited preview or a reply to an older one. Refine asks what to change in plain
chat. Reply normally, without a prefix or another form; OH returns a new preview for approval. Private-plan approvals do not promise a Git commit.
Other hosts get the same review file and their existing question controls; opening a side panel
is optional. These paths are covered by `test_codex_native_question_binds_preview_and_preserves_the_human_answer`,
`test_prepared_claude_menu_binds_scope_limits_and_expires`, and
`test_a_row_is_shown_first_then_written_reviewed_and_committed`.

Before writing anything, OH shows what it understood, the route and why, and the exact lines it
would write, and waits for **approve**, **refine: <what to change>** (ask again with your words)
or **Cancel** (end the proposal without saving it or asking another question). After approve, OH writes the row, milestone, decision record or task itself (on a new
`propose/<topic>` branch from `main`, which OH brings up to date and switches to first), checks
the plan rules and has it reviewed independently, then commits it. You see everything it will
write (the lines, the milestone, a new milestone's "Done when", a task's track, a decision
record's text); if the review would change any of it, OH asks you again first. An improvement or an unclear idea writes
nothing and needs no review. After the commit, **pr** opens the pull request; merging it
approves the plan change. Plans run none of your project's checks: OH checks every plan file
it writes against the plan rules and undoes a write that breaks one.

Typed without its argument, `/oh-propose` asks what you would like to propose and `/oh-design`
asks which roadmap initiative to design. These are ordinary questions, asked before starting
OH; they need no saved waiting state. Your next message supplies the input. When starting,
OH verifies both the invocation and your answer in the native conversation. Another OH command
replaces the question, and `/oh-stop` drops it. The shared-host regression is
`test_conversational_intake_needs_no_waiting_state`.

With repository plans, `/oh-propose` and `/oh-design` work in the checkout that has `main`; in
another worktree of the project, OH asks you to type the command there.

`/oh-design <slug>` writes the design doc for one row of your roadmap, such as
`/oh-design auth`. A fresh worker writes the design; OH numbers the doc, links it from the
row and checks its task list. An independent reviewer checks the design, and OH commits it
(on a new `design/<slug>` branch from an up-to-date `main`). Type **pr** to open the pull request; merging it approves the
design. When a question has to be answered before the design can be written, OH writes a
proposed decision record instead, with the question, the options and a recommendation, and
leaves the decision to you.

The first time, choose where plans live ([configuration](configuration.md)). The repository
flow above uses pull requests. With `plans.location=private`, documents live outside the
checkout, normally in `~/oh-plans/<project name>/`, with no Git branch or commit. `/oh-propose`
asks before it writes, as above; `/oh-design` waits for **approve**, **refine: <what to change>**,
or **Cancel** (discard the unapproved draft) after independent review.
Approving a private design records its exact content hash; later edits invalidate approval.
Run `/oh-design <slug>` on an edited private design to review the existing text and approve it
again. `oh plans list` distinguishes approved, draft, and edited-since-approval designs.
A proposed decision document still needs a human decision; approving its saved text does not
choose an option.

## Build: oh-deliver

- `/oh-deliver` lists ready designs and explains why others are unavailable, then asks which
  design or quick fix you want. Reply in the same chat; an empty list never resumes an old batch.
- `/oh-deliver 0005` starts the next ready tasks from approved design 0005 immediately.
  Add a track name to select only that track. When several tracks need a choice, OH asks for
  one before switching branches or starting tasks. Repository designs must match their approved
  revision on `origin/main`; private designs must match their saved human approval.
- `/oh-deliver fix the sign-in timeout` proposes a bounded task list. The agent prepares
  it and shows the tasks and limits in an **Approve / Refine / Cancel** menu. Approve grants exactly
  that saved task list. The trigger `$o-harness:oh-deliver request:<id>` stays available as a typed fallback. The approved scope cannot grow afterwards.

Ready tasks are selected in dependency order; blocked work stays pending. OH owns task
checkboxes and freezes a design when its last task completes. For private plans, the reviewer
sees the proposed document update alongside the code; OH publishes the update only after the
reviewed code commit, with recovery if saving is interrupted. Private documents stay out of Git.
Private progress also records its code revision: OH continues on the design's delivery branch,
and progress made on any other branch needs that branch merged first. An older private plan with completed tasks but no recorded revision needs
review and reapproval through `/oh-design <slug>` from the checkout containing that completed code.

OH then runs the tasks on `deliver/0005` (`deliver/0005-<track>` for one track), made from
an up-to-date `main`. If that branch still holds unfinished work, from a delivery you stopped,
OH resumes it and merges `main` into it; one pull request then publishes all of it. If `main`
conflicts with that work, you choose: start over from `main` (the branch is discarded), finish
without `main`'s changes (you resolve the conflict when the pull request merges), or let the agent
plan a resolution for you to approve; the next task's review then covers it, as it covers commits of
your own on that branch. A branch that already holds the whole design goes to its pull request: typing the command
again offers **pr** again, even after **stop**, and new tasks for that design come after it merges. Typing the
same command while its run is open continues that run. For each task a
fresh worker implements it, your project checks run, an independent reviewer checks the
exact result, blockers get fixed, and the reviewed tree is committed. Workers can't write
OH's state, your settings or Git internals.

Proposal authors and reviewers receive the same routing policy, including new product areas.
Planning handoffs state whether designs use private human approval or a repository PR merge.
Reviewers receive saved planning-author reports as well as code implementation reports.
Repair and refinement agents receive the existing review history and human dispositions;
that history preserves earlier fixes and does not grant additional scope or reopen accepted,
dismissed or routed findings. Recorded human refinements also reach subsequent reviewers and
blocker-driven repairs; a review renewal does not replace the person's requested approach.
Planning agents self-review their document changes and defect
families before returning them. Covered by
`test_a_row_is_shown_first_then_written_reviewed_and_committed`,
`test_a_design_is_written_by_oh_reviewed_on_its_branch_and_committed`,
`test_a_repair_rewrites_the_same_doc_from_the_reviewed_parent`,
`test_private_design_waits_for_hash_bound_human_approval_without_git_changes` and
`test_repair_review_retains_prior_family_and_exact_subject`.

Tasks continue automatically within the granted batch; another task does not need another approval.
`status` includes the current task and phase (specialist work, checks, independent review or completion)
with bounded implementation reports and the last completed review’s findings, so the chat can
explain what the implementation agent changed, what the independent reviewer agent found and who
is fixing it. Invariant review challenges correctness, failure paths, tests and project requirements,
as well as scope. At approval and completion checkpoints, `last_review` retains the latest
finished review's outcome, round count and finding count, even when it finished between status
polls. The chat reports that result once per attempt
before the commit or saved document, explicitly identifying a clean review with no findings.
It avoids repeated promises to commit or publish. At a batch boundary, **Stop and take over** retains the work
without publishing. Once all tasks finish, that option becomes **Finish without a PR**.
The chat summarizes the work and finite Continue allowance; approval copies show their complete
scope and limits. Menus use short, neutral labels such as **Approve**, **Refine**, **Cancel** and
**Open a PR**, without recommending approval or publication. A completed repository task asks
“Open a pull request?”; an unfinished batch offers Continue, PR or Stop with the next task and finite
allowance explained in chat. Choosing PR returns the retained
publication grant and routes directly to push/PR, without executing or reviewing the work again.
On the normal publication path, the next chat message is the PR number/link and result, including
the recorded review-round count. The host may still require its own publication authorization; OH
does not retry a rejected payload through another confirmation tool. Covered by
`test_initial_and_continue_same_batch_snapshot_and_idempotent_restart`,
`test_codex_menu_records_the_click_itself` and `test_native_pr_evidence_binds_all_commits_and_refuses_tampering`.

Every new OH execution or repository-planning branch starts from refreshed main. Task preparation
also refreshes main after Refine, before showing the revised list; the previous branch remains intact.
Preparing starts no worker or execution branch. Numbered delivery retains its existing branch-resume
behavior: bring main into unfinished work, or start fresh when main already contains it. Local main is
fast-forwarded when it is available and has no divergent work; another worktree's main stays untouched.
New branches use fixed prefixes: `propose/<topic>`, `design/<initiative>`, and
`deliver/<approved-task-title>` for quick fixes or generic tasks. Numbered deliveries keep
`deliver/<design-number>[-<track>]`. OH normalizes task titles into readable names; occupied names
get `-2`, `-3`, and so on, including tracked origin names. Existing branches remain intact. An interrupted
quick-fix approval resumes with the same human choice; it does not ask again just because branch creation
was interrupted. Private planning creates no branch. Covered by `test_proposals_start_from_main_wherever_the_checkout_was`,
`test_new_plans_start_from_main_brought_up_to_date`,
`test_repository_design_starts_once_and_uses_existing_batch_runner`,
`test_a_worktree_delivers_while_main_is_checked_out_elsewhere` and
`test_prepared_claude_menu_binds_scope_limits_and_expires`,
`test_codex_native_question_binds_preview_and_preserves_the_human_answer` and
`test_a_design_branch_never_reuses_an_existing_branch`.

The approved scope never grows. For example, while fixing a login timeout, OH can record
that logout needs a timeout, but does not build it in that task. A reviewer’s unrelated
findings go under `## Open review scope` in the draft or approved design; **Dismiss scope**
records them under `## Scope decisions`. With no mutable design, **Route scope** files a
GitHub issue and **Dismiss scope** retains the finding in the PR evidence. A review with
both bugs and scope records scope first, then sends only bugs and concerns to the fixing
agent. The person's merge accepts the recorded future work; it does not add it to the run.
Workers report unrelated observations separately. OH records them in the design before
review, or under “Found along the way” in a quick-fix PR. Private designs use the same
reviewed candidate and approval hash as task progress. A changed design candidate needs a
fresh review before commit, within the existing review allowance.

These rules are covered by `test_scope_routing_and_repairs_preserve_the_approved_task` and
`test_scope_choice_recovery_reviews_the_exact_private_candidate` in `runtime/oh/test_delivery.py`,
and `test_scope_without_a_mutable_design_routes_or_dismisses_but_never_grants_work` and
`test_native_pr_evidence_binds_all_commits_and_refuses_tampering` in `runtime/oh/test_workflow.py`.

A batch has 5 tasks and each task gets up to 3 review rounds by default; change that with
`/oh-config` ([configuration](configuration.md)). If a task still has findings after its review rounds,
OH pauses and shows the choices. At the end of a batch, choose **continue**, **pr** or
**stop**. The agent shows the choices as a menu where the host can show one: Claude's
question menu, or a Codex pop-up. Menus were checked in the Claude CLI, desktop app and phone
(Remote Control), and in the Codex CLI, desktop app and iPhone. Typing the word always works too,
and is the way to choose where no menu can be shown, such as `codex exec`. At an approval, pick **Refine** on either host to say what to change in chat. **pr** lets the agent push the branch and open a pull request with the
review summary; you merge it.

Codex sends one question per form. Choosing **Other** in a general confirmation opens a text
question afterward; closing it applies nothing. **Refine** at a proposal, design or prepared-task
approval instead asks in ordinary chat and preserves the next human reply. Covered by
`test_confirm_waits_for_the_person_and_never_answers_for_them` and
`test_refine_asks_again_with_the_person_s_words`.

You can still code, commit and open PRs without OH at any time.

## Pause, resume and stop

- `/oh-pause` finishes the current step, then waits. The status is PAUSING until it is
  quiet, then PAUSED.
- `/oh-resume` continues the same batch with what is left of its approval.
- `/oh-stop` stops the batch and keeps all files, commits and evidence. A stopped batch
  can't resume; new work needs a new approval.

If the agent is busy, run `oh --root <project> pause` or `oh --root <project> stop` in a
terminal. `oh --root <project> status` shows the current run.

If files change while a batch is paused, OH refuses to resume until you restore them or
stop the batch. It never discards your edits.

## Projects

- `oh init` registers a checkout, named after its repository (`--name` picks another name).
  It grants no work.
- Another worktree of the same project: `oh init` joins that project (or
  `--attach <project-id>`).
- A checkout you moved: `oh init --reattach <checkout-id>`.
- A new checkout at an old path: `oh init --replace`.

To reuse a project's settings and checks elsewhere, run `oh profile-export <file>` and
`oh --root <other-checkout> profile-import <file>` (add `--name <name>` when a project on
that machine already has the name). Exports contain no credentials,
sessions or evidence. Export fails unless every check runs a script tracked in the
repository, such as `["./scripts/check.sh"]`.

## Dashboard

On macOS and Windows, `oh service-install` starts the dashboard at <http://localhost:4318> and keeps it
running across logins. On Linux, run `oh serve`. See [dashboard and data](analytics.md).

Execution and recovery checkpoints include the branch, current task, completed and pending
work, checks, findings, and the available options with their effects. Proposal, design and quick-fix
approvals instead explain the complete subject in their Markdown review copy. When review rounds run out, OH shows each round,
new or repeated findings, open findings and the allowance used. These are recorded facts;
waiting or restarting grants nothing. Approval menus show the complete Markdown review copy beside a
short question. Other gates summarize the decision in chat and keep full history in the retained report;
they do not open a side panel. Approval covers the complete saved list; the short question does not limit its scope. Covered by `test_large_menus_bound_the_handoff_and_preserve_complete_details`,
`test_checkpoint_offers_its_choices_as_a_menu_that_expires_when_the_run_moves` and
`test_review_budget_survives_failures_and_restart`.

Quick-fix approval also works after `/oh-start`. Preparing creates no execution branch and
runs no worker. Replaced preparations are marked stopped in dashboard observations, and
the new preparation is marked as waiting for approval. An old menu or another conversation cannot approve the saved scope; editing
the source task list or changing settings after preparation cannot widen its grant. Covered by
`test_prepared_claude_menu_binds_scope_limits_and_expires` and
`test_prepared_codex_menu_uses_native_click_and_can_stop`.

Before publishing a design batch, OH checks that its completed tasks—and only those tasks—are
marked done, that approval came from main (or the unchanged private approval), that dependencies
were done before each task, and that the branch and task commits match the design and track.
Dependencies completed earlier in the same batch count. A multi-track design must name a track;
finalizing an already completed design remains separate. Quick fixes skip these design checks.
Covered by `test_repository_design_starts_once_and_uses_existing_batch_runner` and
`test_ready_selection_skips_blocked_tasks_and_orders_dependencies`.

`oh pr-summary` gives the PR a readable change summary, verification results, independent review
outcome, and actual findings, decisions and scope destinations. Execution logs remain in OH's journal.
New publication evidence uses repository-relative paths and public references before its digest is
sealed into the commit. Original local reports remain in OH’s journal. Portable machine evidence
stays in hidden PR metadata, preserved verbatim for validation; it does not
appear in the rendered description. Existing PRs with visible JSON still validate. OH reads its retained journal,
and text inside a finding cannot expose the hidden packet. Covered by
`test_native_pr_evidence_binds_all_commits_and_refuses_tampering` and
`test_scope_without_a_mutable_design_routes_or_dismisses_but_never_grants_work`.

Concern/scope decisions, review renewals, recovery and task boundaries use a short explanation in
chat and a compact menu. They do not open side-panel documents or put the retained run history
inside the question. Review renewal shows the exact additional review count and offers taking
over manually. Repository work also offers a stop with an unresolved PR handoff for human triage;
it does not approve completion or normal publication. Private plans have no PR handoff.
Private-plan completion and conversational refinements emit the same dashboard observations as
code delivery. Durable spool events are indexed when the collector runs; observations never grant work.
