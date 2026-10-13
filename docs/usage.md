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
external storage. In Codex Desktop, OH opens it in the right panel and uses OH’s blocking
menu, so you can keep reading and scrolling while deciding. The menu waits for your click
without repeatedly waking the coordinator. Cancelling it grants nothing. In Claude desktop, the
coordinator opens a scratchpad copy of it in the side pane (`show_pane`) when that pane tool is
available; the stored preview stays the one OH checks, and without the pane you get the link only.
Covered by `test_prepared_claude_menu_binds_scope_limits_and_expires`. The question names that exact
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
`propose/<topic>` branch from the base branch, which OH brings up to date and switches to first), checks
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

With repository plans, `/oh-propose` and `/oh-design` work in the checkout that has the base branch; in
another worktree of the project, OH asks you to type the command there.

`/oh-design <slug>` writes the design doc for one row of your roadmap, such as
`/oh-design auth`. A fresh worker writes the design; OH numbers the doc, links it from the
row and checks its task list. An independent reviewer checks the design, and OH commits it
(on a new `design/<slug>` branch from the up-to-date base branch). Type **pr** to open the pull request; merging it approves the
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
  revision on the selected base branch; private designs must match their saved human approval.
- `/oh-deliver fix the sign-in timeout` proposes a bounded task list. The agent prepares
  it and shows the tasks and limits in an **Approve / Refine / Cancel** menu. Approve grants exactly
  that saved task list. The trigger `$o-harness:oh-deliver request:<id>` stays available as a typed fallback. The approved scope cannot grow afterwards.

Ready tasks are selected in dependency order; blocked work stays pending. Delivery workers
have read-only access to the approved plan files at their configured paths. Codex uses an
invocation-local permission profile; Claude denies document edits/writes and sandboxed shell
writes (Windows workers have no shell). User settings and file permissions are not rewritten.
Covered by `test_codex_document_permissions_preserve_configured_paths` and
`test_claude_workers_on_windows_edit_files_but_have_no_shell`.

The visible task stays unchecked during implementation, checks and independent review.
OH prepares the proposed completion/freeze separately and includes it in the review subject.
Only native completion can publish that document, after passing checks and an authorized
review, and commit exactly the reviewed tree. An interrupted completion resumes from its
recorded intent. Covered by `test_repository_task_stays_pending_through_check_repairs_and_review`,
`test_stop_after_delivery_review_keeps_task_pending_until_explicit_continuation` and
`test_repository_completion_recovers_after_document_publish_before_commit` in `runtime/oh/test_delivery.py`.
Private progress is published after the reviewed code commit, with recovery if saving is
interrupted. Private documents stay out of Git.
Private progress also records its code revision: OH continues on the design's delivery branch,
and progress made on any other branch needs that branch merged first. An older private plan with completed tasks but no recorded revision needs
review and reapproval through `/oh-design <slug>` from the checkout containing that completed code.

OH then runs the tasks on `deliver/0005` (`deliver/0005-<track>` for one track), made from
the up-to-date base branch. If that branch still holds unfinished work, from a delivery you stopped,
OH first recognizes its saved unfinished task, preserves the draft and continues from the last valid
implementation/check/review stage. This also works in a new conversation in either Codex or Claude after Stop,
including with a newer installed OH: the original scope, settings, findings and remaining review allowance stay intact. The checkout
must match the saved branch, HEAD and file contents, and the previous runner must have stopped.
An explicit `/oh-resume` also transfers the saved run or decision to the current session. OH waits
briefly for already-requested Stop/Pause cleanup; a live run cannot be taken over. The destination
uses its profiles from the run's saved settings with the same task difficulty and escalation history.
Old receipts retain their originating host, and old-session menu answers or cancellation events
cannot control the resumed work. This uses the same checkout and OH data, not cross-computer migration.
OH finishes that admitted task before refreshing its branch for further work; it never merges or replaces a
branch over the retained draft. One pull request then publishes all of it. For later task admission, if the base branch
conflicts with that work, you choose: start over from the base branch (the branch is discarded), finish
without the base branch's changes (you resolve the conflict when the pull request merges), or let the agent
plan a resolution for you to approve; the next task's review then covers it, as it covers commits of
your own on that branch. A branch that already holds the whole design goes to its pull request: typing the command
again offers **pr** again, even after **stop**, and new tasks for that design come after it merges. Typing the
same command while its run is open continues that run. Covered by
`test_stopped_draft_continues_in_new_session_and_version_on_both_hosts`,
`test_stopped_continuation_rejects_changed_checkout_or_live_runner`,
`test_stop_after_verified_implementation_continues_at_review_without_rebuilding` and
`test_stopped_continuation_preserves_review_findings_and_spent_window` in `runtime/oh/test_delivery.py`. For each task a
fresh worker implements it and runs your project checks, then an independent reviewer checks the
exact result, blockers get fixed, and the reviewed tree is committed. Workers can't write
OH's state, your settings or Git internals.

If an OH update arrives while delivery awaits a review decision, invoking Deliver in a fresh
session adopts the new runtime after checking the saved branch, HEAD and working tree. The
same findings and spent review allowance remain pending; the command grants no extra reviews.
There is no need to stop the waiting run first. The same continuation test covers this path.

Workers have no total execution deadline: implementation, planning and review can continue
as long as the task needs. Explicit stop first interrupts the host so it can cancel shell tools
running in separate sessions, then force-stops its process group if needed. On Windows the
worker's job object contains those commands. When a worker exits, OH closes its remaining
process group so an inherited output pipe cannot keep the attempt waiting.
Project checks and short host operations keep their own timeouts. Covered by
`test_workers_outlive_elapsed_time_and_close_descendants_output` and
`test_explicit_command_deadline_still_cancels` and
`test_worker_cancellation_interrupts_the_host_to_clean_detached_commands` in `runtime/oh/test_system.py`.

Claude workers can read this project's OH task inputs and repair feedback while those files
remain protected from edits. Implementers persist through incomplete work, self-review defects and failed checks, preserving
useful edits. If a worker returns unfinished work, OH continues the same task on the same profile
with concrete remaining steps; no review is spent until implementation completes. A completed
report includes a current task packet: requirements, rules, affected surfaces, proof, self-review,
family closure, every prior finding disposition, verification, repair diagnoses and limits.
Both the implementer and reviewer submit reports before exiting and correct report errors in
the same agent call. A malformed report does not restart implementation or rerun passing checks.
OH preserves recognizable review findings even when other receipt fields are malformed;
incomplete review evidence cannot approve completion. Tests are evidence to examine against approved behavior;
a faulty assertion may be corrected with behavioral proof, but green tests never authorize
changed requirements or lost behavior. The independent reviewer challenges these claims.
Covered by `test_unfinished_work_continues_with_edits_and_remaining_steps_on_both_hosts`.
Report correction and retained findings are covered by
`test_worker_check_tool_runs_only_the_bound_projects_checks`,
`test_repair_review_retains_prior_family_and_exact_subject` and
`test_malformed_host_results_cannot_become_review_evidence`.
A blocked report
must name missing authority or an external dependency, concrete evidence and the next action.
Such work keeps its edits and report; OH stops before checks or independent review and explains
what must be resolved. A successful
host call alone cannot complete a task. Covered by
`test_claude_workers_on_windows_edit_files_but_have_no_shell` and
`test_blocked_or_missing_worker_completion_never_spends_a_review` and
`test_unfinished_work_continues_with_edits_and_remaining_steps_on_both_hosts`.

Proposal authors and reviewers receive the same routing policy, including new product areas.
Planning handoffs state whether designs use private human approval or a repository PR merge.
Reviewers receive the current author report and a complete finding index. Distinct cases and
every original finding remain traceable; earlier author reports are available on demand instead
of being mandatory reading. Repair and refinement agents receive current work and human dispositions;
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
Failed lint, type or test checks go directly back to the implementation agent and are rerun
before independent review. They never change the model or request Retry approval. The model
escalates only after the same blocking defect family appears in two independent review
receipts. Covered by `test_checks_repair_without_escalation_and_only_repeated_review_families_escalate`.
The implementer calls its restricted `verify` tool to run the registered project checks and
repairs failures before returning. The same tool works on native Windows Claude without a shell.
It accepts no commands or paths from the worker and retains the actual results in OH's storage.
The runner admits review only when those results cover the final unchanged work; it does not
execute a second round of tests. Missing or stale results return to the implementer. Covered by
`test_review_requires_implementer_checks_for_the_final_unchanged_tree` and
`test_checks_repair_without_escalation_and_only_repeated_review_families_escalate`.
During a command, the runner reports actual transitions and retains the latest bounded public
worker update. The coordinating chat keeps one execution call active with yielding/background
waits, reads status every 210 seconds and relays only new meaningful work in one short sentence.
Reasoning and tool output never enter that update. The runner also emits fresh public focus
through native progress at this cadence. Covered by
`test_the_runner_reports_progress_where_the_server_forwards_it`,
`test_workers_relay_public_focus_without_repetition_over_thirteen_minutes` and
`test_initial_and_continue_same_batch_snapshot_and_idempotent_restart`.
Persistent external obstacles preserve work and explain the concrete next action. Deliver
has no Retry menu: after the obstacle is repaired, `run` continues the same approved work
without renewing task or review allowances. Planning uses the same continuation after its
external obstacle is resolved. Neither workflow offers a routine Retry approval.
Covered by `test_blocked_or_missing_worker_completion_never_spends_a_review`
and `test_planning_continues_after_external_obstacle_without_new_allowance`.
`status` includes the current task and phase (specialist work, checks, independent review or completion)
with bounded implementation reports and the last completed review’s findings, so the chat can
explain what the implementation agent changed, what the independent reviewer agent found and who
is fixing it. Invariant review challenges correctness, failure paths, tests and project requirements,
as well as scope. At approval and completion checkpoints, `last_review` retains the latest
finished review's outcome, round count and finding count, even when it finished between status
polls. The chat reports that result once per attempt
before the commit or saved document, explicitly identifying a clean review with no findings.
`last_failure` explains the current task's latest failed attempt or check, including a worker's
exit status and cancellation reason when available. A newer active attempt or result supersedes
that current-failure display; the original remains in the history. Check repair feedback
is plain text without terminal colour codes; the complete retained check result stays in the journal.
Review packets carry concise verification results instead of repeating check logs as remaining
work. The receipt index shows active reviews as running and labels an implementer's claimed
repair as awaiting review confirmation; a later clean review confirms closure. Missing results
are labelled unavailable rather than linked to nonexistent files. Original receipts stay unchanged.
Covered by `test_repair_review_retains_prior_family_and_exact_subject`.
Covered by `test_failed_worker_cause_reaches_status_and_automatic_continuation` and
`test_review_requires_implementer_checks_for_the_final_unchanged_tree` in `runtime/oh/test_workflow.py`.
It avoids repeated promises to commit or publish. At a batch boundary, **Stop and take over** retains the work
without publishing. Once all tasks finish, that option becomes **Finish without a PR**.
The chat summarizes the work and finite Continue allowance; approval copies show their complete
scope and limits. Menus use short, neutral labels such as **Approve**, **Refine**, **Cancel** and
**Open a PR**, without recommending approval or publication. A completed repository task asks
a destination-bound publication question; an unfinished batch offers Continue, PR or Stop with
the next task and finite allowance explained in chat. On Codex, publication uses the native question
and actual human reply, so the same decision is visible to OH and Codex. It names the branch,
destination and PR target, while keeping credentials out of the question and report. Choosing PR returns the retained
publication grant and routes directly to push/PR, without executing or reviewing the work again.
Direct bare choices are case-insensitive (`pr`, `Pr` and `PR` select the same offered action);
the original human message is retained unchanged as evidence. Other prose is not inferred as a choice.
Reinvoking the same Deliver design from a fresh session at a saved completed-task gate returns
to that decision. An updated OH runtime verifies the retained commit and plan evidence before
taking over; task/review allowances and any recorded publication choice remain unchanged.
No implementation, checks or review are repeated just to reopen that gate.
If publication was already chosen and the branch now has later descendant commits, a new session
resumes observation of the existing PR. Those commits are not covered by the earlier OH review;
the retained publication grant cannot push them or create a new PR for them.
On the normal publication path, the chat links the PR and observes CI for its current commit.
It reports pending, failed or unavailable checks honestly, diagnoses failures and gives a concrete
next step. A changed PR head needs fresh CI observations and is not covered by an earlier OH review.
Publication recovery reuses the PR; publication permission does not authorize new code edits.
The final result includes the recorded review-round count and actual CI outcome. The host may
still require its own publication authorization; OH
does not retry a rejected payload through another confirmation tool. Covered by
`test_initial_and_continue_same_batch_snapshot_and_idempotent_restart`,
`test_codex_menu_records_the_click_itself` and `test_native_pr_evidence_binds_all_commits_and_refuses_tampering`.

Every new OH execution or repository-planning branch starts from the refreshed base branch. Task preparation
also refreshes the base branch after Refine, before showing the revised list; the previous branch remains intact.
Preparing starts no worker or execution branch. Numbered delivery retains its existing branch-resume
behavior: bring the base into unfinished work, or start fresh when the base already contains it. The local base branch is
fast-forwarded when it is available and has no divergent work; another worktree's base branch stays untouched.
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

Clicking **Stop in Codex** also stops the OH run owned by that execution turn, interrupts its
worker or check and preserves edits, commits and evidence. The run settles as STOPPED after
owned-process cleanup. This works even when the stopped call was a yielding wait rather than
the original OH tool. A prior turn's interruption or a transport failure does not stop another
execution. Covered by `test_stop_during_check_cancels_owned_group_and_preserves_results` and
`test_codex_stop_after_worker_prevents_checks_review_and_commit`.

- `/oh-pause` finishes the current step, then waits. The status is PAUSING until it is
  quiet, then PAUSED.
- `/oh-resume` continues the same batch with what is left of its approval.
- `/oh-stop` stops the batch and keeps all files, commits and evidence. `/oh-resume` does
  not restart a stopped batch. Explicitly invoking `/oh-deliver NNNN [track]` again can
  continue its saved unfinished task with the remaining authority. It does not renew
  a spent review window or accept findings; new scope still needs approval.

If the agent is busy, run `oh --root <project> pause` or `oh --root <project> stop` in a
terminal. `oh --root <project> status` shows the current run.

Once pause or stop is accepted, finishing that control does not require rereading the host's
latest human turn. A stop settles after worker cleanup even when that turn is still being saved.
Covered by `test_stop_during_worker_settles_without_rereading_unsaved_human_turn` in `runtime/oh/test_controls.py`.

If files change while a batch is paused, OH refuses to resume until you restore them or
stop the batch. It never discards your edits.

## Base branch

OH detects the base from `origin/HEAD`, then falls back to `main`, then `master`.
To use a development branch instead of a release default, run `oh config set base_branch develop`.
Use `--global` to set it for every project; a project's own value wins. `oh config unset base_branch`
restores the inherited value, and setting an empty string selects detection explicitly.
`oh config` shows the selected name, comparison ref and source. The branch must exist locally
or as an origin tracking ref; an unavailable override gives a fetch or settings repair step.

Repository proposals, designs and deliveries start from this base. Repository-plan approval and
progress comparisons require `origin/<base>`, preserving the merged-plan requirement; a local
branch alone does not grant approval. `oh verify` uses its comparison ref for changed paths and `{base}`;
an explicit base argument still overrides it. `oh pr-summary` refreshes that ref and reports
the target; the publication checkpoint supplies `base_branch` for creating the PR with an explicit
`--base`. A running batch keeps the branch selected when it started, even if settings change.

Covered by `test_base_branch_precedence_remote_only_checkout_and_checks`,
`test_a_design_is_written_by_oh_reviewed_on_its_branch_and_committed` and
`test_repository_design_starts_once_and_uses_existing_batch_runner` (a master-only delivery), and
`test_missing_remote_base_is_an_actionable_listing_result` and
`test_unapproved_or_blocked_design_cannot_become_native_task_scope`.

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

On native Windows, a registered check using bare `bash` runs with native Bash, such as
Git for Windows, so it can use the installed Windows tools. Your default PowerShell stays
unchanged. To run a check in WSL deliberately, register `wsl` or an explicit interpreter path.
OH records the selected executable and includes it in verification reuse.
Approved repository plans can use CRLF in the checkout while Git stores LF. OH accepts that
line-ending conversion when comparing them with their approved revision; it still compares
all other bytes without applying Git filters. Covered by
`test_crlf_plans_deliver_and_freeze_without_changing_line_endings` and
`test_unapproved_or_blocked_design_cannot_become_native_task_scope`.

If a check executable is missing or a registered toolchain version probe fails, OH keeps the
completed implementation and records the failure without escalating the implementation model.
Restore the tool or fix its version probe, then call `oh run` to retry verification under the
same approval. Ordinary failing checks still follow the existing implementation repair path.
Covered by `test_windows_bash_uses_native_tools_and_preserves_explicit_interpreters` and
`test_pause_drains_worker_and_resume_keeps_allowances_without_repeating_it`.

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
marked done, that approval came from the selected base branch (or the unchanged private approval), that dependencies
were done before each task, and that the branch and task commits match the design and track.
Dependencies completed earlier in the same batch count. A multi-track design must name a track;
finalizing an already completed design remains separate. Quick fixes skip these design checks.
Covered by `test_repository_design_starts_once_and_uses_existing_batch_runner` and
`test_ready_selection_skips_blocked_tasks_and_orders_dependencies`.

`oh pr-summary` gives the PR a short summary of the original implementation and its repairs, recorded check results, independent review
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


### Current task context and readable receipts

`next_action` is the shared execution/status/menu decision. Known defects are repaired and
verified within the task's existing approval before another review allowance is requested.
A stopped older run preserves its work, initial model, findings and consumed allowance.
Each new task receives a fresh runtime difficulty assessment on the standard profile; no
harness difficulty or effort is written into the consumer design.

The returned `report` links to an external Markdown index by task and review round. Each new
attempt has a readable request and immutable result view beside its original structured evidence.
Review receipts show the reviewed state, model, duration, outcome, findings and coverage;
missing historical details are labelled. Native JSON and the journal remain authoritative.
The index distinguishes author repair claims from fixes confirmed by later independent review;
the original findings stay linked. Large proposal details and private designs are linked for
approval instead of being repeated in each status response.

PR descriptions contain concise whole-change summaries, actual verification, review outcomes,
a delivery boundary and expandable review history. Earlier repair notes are not concatenated
into the current summary. A recorded publication choice binds the actual push destination;
changing that destination requires a new choice, while restoring it preserves the original grant.
Older choices without a destination need that missing authority once, without repeating work.
Covered by `test_repair_review_retains_prior_family_and_exact_subject`,
`test_native_pr_evidence_binds_all_commits_and_refuses_tampering`,
`test_codex_menu_records_the_click_itself` and
`test_review_budget_survives_failures_and_restart`.
