# Architecture

| Path | Contents |
|---|---|
| `runtime/oh/` | The OH engine: run state, host adapters, checks, reviews, analytics and the dashboard server |
| `plugins/o-harness/` | The plugin both hosts install: skills, the prompt hook and the launcher |
| `workflows/` | Instructions the plugin skills load for each workflow |
| `prompts/` | The shared independent-reviewer prompt |
| `config/` | Default settings and OH's own invariants |
| `dashboard/` | Static dashboard files, no build step |
| `integrations/` | Test and packaging scripts |
| `.claude/`, `.codex/` | Settings for developing OH itself |

## Install layout

A built plugin contains the engine. On the first OH command, the plugin's launcher copies it
to `~/.local/share/o-harness/versions/<commit>` and marks it active when its version is
newer than the active one. Each run records its version and keeps using it until it ends,
so an update never changes a running batch. Both hosts share the installed engine and the
data folder.

## Authority

A native human message or menu click approves work. For typed commands, the prompt hook records
where to find the message, and OH confirms it in the host's saved transcript before starting. Model output, elapsed time
and restarts never approve anything. Approved scope is fixed when prepared.

Missing arguments are collected in ordinary conversation before starting the runner. The skill
asks directly; no waiting-file write is required to ask. At admission, OH reads the native human
invocation and its replies, checks their checkout and consumption receipts, and passes the completed
input to the existing workflow. The actual human message remains the authority source. Quick-fix
clarifications only prepare scope; its immutable approval menu still grants execution.
Unresolved locators whose source is missing remain non-executable and do not block a verified
request. If their source returns, the recorded request/menu chronology prevents stale work from
reviving. Partially saved existing sources still receive the bounded evidence retry.

Approval checkpoints render their complete subject to a stable Markdown review copy under the
run's menus folder. The native question names its checkpoint-specific preview. Codex Desktop's
async question answer is accepted only from a native human record in the owning conversation,
matched to the exact question the host displayed. Injected user-role text, changed questions,
old previews and replays cannot grant work. This uses the existing transitions and receipts;
opening the preview in a host panel is presentation, not approval authority. The MCP elicitation
path remains available where the native async question is absent.

A choice can also be a click. In Claude, the agent shows OH's menu with Claude's own question
tool; a hook refuses a menu whose answer the model filled in, and OH reads the click from the
saved transcript of the conversation that owns the run. Nothing is handed over in between, and
only the latest click on exactly the menu OH is waiting on counts, so a click on an older menu,
in another conversation or on an altered menu never applies. A menu word typed in Claude
is read from the transcript the same way, so only the person's single latest answer to the
current menu counts, typed or clicked; if OH refuses it, no earlier answer applies instead. Only
records trusted under normal host permissions count; peer, sidechain, meta and notification records
stay excluded. Claude Remote Control menu replies are accepted without asking the person to type
the choice again. Claude 2.1.294 saves genuine phone clicks with the same approval metadata as
programmatic SDK answers. Custom SDK software can also stamp typed inputs with human origin, so
typing does not reliably distinguish that software from a person. OH accepts this SDK automation
risk for both native menu replies and human-marked inputs, as stated in `config/invariants.json`;
it does not claim either is unforgeable proof of a physical human action. This applies to task grants
and review renewals as well as other choices. Exact current-menu matching, unanswered tool input,
owning session and checkout, latest-answer ordering and one-time receipts remain required.
Covered by `test_typed_choices_count_as_saved_by_the_desktop_app_but_not_from_other_senders` and
`test_a_refused_latest_answer_never_lets_an_older_one_apply` and
`test_native_transcript_binds_host_turn_text_and_checkout`. If OH can't read a typed menu word as the
latest answer, it applies nothing and asks the person to choose again.
In Codex's fallback menu path, OH's MCP server shows the menu itself and records the click,
which travels from the Codex menu to OH without passing through the model; a click spends any menu word typed before it.

In Codex, the agent runs OH through that same server rather than the shell. Codex's sandbox lets
shell commands write only inside the project, while OH's state lives in its own folder so the
model can't write it; Codex runs a plugin's MCP server outside that sandbox. Each everyday OH
command (status, init, deliver, prepare, start, run, pause, resume, stop and a few read-only ones)
is a tool that runs the command through the plugin's `oh` launcher, as the shell would: with the
person's own shell setup (read once from their login shell, since Codex gives the server almost
none of it), while OH's and the hosts' own settings come only from Codex, so a command and the
server always use the same OH state. A command runs in its own session, and OH ignores an output
nobody reads any more, so a run keeps working if Codex ends the server. OH's progress lines become progress notifications.
The server runs from the core the plugin carries, so its tools exist before setup and right after
an update; the launcher still picks and activates the installed core. Stopping a tool call does
not stop OH, which keeps working within its grant; `status` and `stop` still apply.
Commands that change what OH runs on the machine (settings and checks, setup, host trust,
backups, services) are not tools, so Codex asks the person before they run. Codex puts the
calling conversation in each request's metadata, which the model can't set: a tool acts only on
the Git checkout that conversation works in (read from Codex's saved session), never on a
repository around a nested one, a menu answers only in
the conversation that started the run, and OH checks a typed choice against that conversation's
saved turn as before. The server is started only by Codex from the plugin, never by an `oh`
command. OH's worker commands turn OH's Codex plugin off, and the server refuses any tool when an
OH worker started it.

The runner keeps a hash-chained journal per run. For each task it picks a model profile,
starts a fresh worker, runs the checks, starts an independent reviewer on the exact tree
and commits only the reviewed tree, with an `OH-Evidence` trailer. `oh pr-summary` checks
that trailer against every commit on the branch and renders work, verification and review decisions
from the journal. Local path prefixes are removed before new publication evidence is sealed into
the commit; local journals retain the originals. Portable evidence stays in hidden PR metadata; validation also accepts existing
PRs with the original visible JSON format.
Design delivery also records its approved starting document and checks actual task transitions,
dependency order, branch ownership and commit subjects before PR. Private designs use their
human-approved hash and retained progress candidates. Prepared quick fixes wait in a journaled
approval checkpoint without a task grant or execution branch; the host's Approve click activates
only that immutable task list and its saved limits. See the behavior tests named in
[usage](usage.md).

Workers run through the checked host CLI with API-key variables removed. They can't write
OH state or Git internals; reviewers are read-only. Pause and stop share a lock with commit,
so a stop never leaves a half-recorded task.

## Git subjects and recovery

Local Git reads, review candidates and commits keep the same user configuration, including
runtime line-ending settings, while discarding inherited selectors for another repository or index.
The explicit checkout root is validated before fingerprinting or constructing a candidate. A candidate
uses a temporary index; status reads do not refresh the person's index. Covered by
`GitSubjectTest.test_git_configuration_agrees_and_inherited_selectors_cannot_choose_a_sibling`.

Replacing a tracked file with a folder, or a folder with a file, has the same fingerprint before and
after staging. Nonignored children and tracked files remain visible, even when newly ignored;
child edits invalidate the reviewed subject. Only indexed gitlinks and actual embedded repositories
are checked as child repositories, and dirty or uninitialized children require repair before review.
This repository's nested worktrees remain separate. Conflicted index entries require resolution.
Covered by `GitSubjectTest.test_file_folder_replacements_are_staging_independent_and_children_remain_visible`,
`GitSubjectTest.test_real_gitlinks_embedded_repositories_and_nested_worktrees` and
`GitSubjectTest.test_unmerged_index_is_not_an_arbitrary_review_subject`.

If the final fingerprint fails after a worker returns, OH retains its complete answer, finishes the
attempt as failed with an unknown post-tree, and stops for attention. Repair the checkout and use the
existing retry choice; restarting does not call the worker again or replenish an allowance. A supported
file/folder replacement also survives an interrupted commit without additional model calls. Covered by
`WorkerCompletionTest.test_post_worker_fingerprint_failure_retains_result_and_spent_attempt` and
`WorkflowTest.test_recover_clean_review_after_commit_without_new_model_calls`.

## Data

The SQLite analytics database is rebuilt from saved events and never grants anything.
Backup and restore lock the data folder.

## Not yet supported

- One task runs at a time. Parallel tasks are tracked in
  [issue 1](https://github.com/pmoreiracc/o-harness/issues/1).
- Other hosts need a tested adapter first
  ([issue 4](https://github.com/pmoreiracc/o-harness/issues/4)).
