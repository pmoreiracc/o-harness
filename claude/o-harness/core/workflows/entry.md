# Reconcile entry evidence

For current planning/delivery advice, listing ready work or recovery, call `entry`
(Codex `entry`) before choosing a path or reporting current tasks/blockers. It reads
saved work and the checkout, and fetches the configured origin base without pulling,
switching branches or editing files. If it returns an observation reference, read
that complete artifact before drawing conclusions.

Treat its commit IDs and observation time as evidence. `fetched` means the named
base was observed at that commit; `unavailable` carries the failed-fetch reason and
any cached commit, not verified current origin. `local_only` means there is no origin.
When offline, explain the freshness limit and reason from the available evidence;
choose whether that evidence supports continuing rather than assuming a new approval
or automatically requiring an online restart.

Reconcile the relevant saved scope/results, native attempts and tool ownership with
HEAD, local edits/commits and the observed base. Saved status labels and historical
reports alone establish neither live execution nor unfinished work. Merged output
does not create missing review/completion evidence. Preserve grants, spent allowances,
findings and existing publication destinations.
Discovery and selected reads now separate the workflow's retained `status` from
`execution` interruption/cleanup facts. Use those facts rather than a status-only
Stop request; see `workflows/recovery.md` for idle selection and retained requests.

Use native Git to inspect the full staged/unstaged/untracked changes, local commits,
other worktrees and the relevant plan on both HEAD and the observed base. Returned
path lists are bounded; inspect the complete differences when deciding their effect.
Plan/list results labelled `source: checkout` describe that local view. Reconcile
material differences before presenting them as current blockers or ready tasks.
A clean `git status` comparing local tracking refs does not prove remote freshness.

## Resolve the actual checkout choice

Choose an appropriate continuation, safe base update, new branch in this checkout or
genuine human decision from those facts. Fetching information and changing the checkout are
separate actions. A safe update that loses no work can proceed within existing
authority. Newer origin commits do not make local work disposable.

Keep repository work in the person's selected checkout throughout Propose, Design,
Deliver, review and publication. Never create or switch to a parallel worktree, clone
or repository copy, including a nested one, to obtain a clean base. Preserve unrelated
edits and unmerged commits. Continue matching work or select a separate branch here
for genuinely independent work. Uncommitted edits belong to this checkout, so merely
switching branches does not separate them.

## Save, switch and restore in this folder

For a branch change, use `workspace <branch> --human <initiating-native-locator.json>`
(Codex `workspace` with `branch` and `human`). Add `--base <observed-commit-or-ref>`
(Codex `base`) to create a new branch from the intended base; omit it when returning
to an existing branch. Choose the branch after inspecting entry facts, ownership and
the requested outcome. Preserve included quick-fix edits on their current execution
branch instead of parking them as unrelated work. For a retained request after an
accepted prerequisite, pass its same `after` identity to this helper too.

The initiating request authorizes this lossless preparation; do not ask another
permission question merely to save work or switch. The helper verifies the request
and native writer settlement, saves tracked/staged/untracked edits with an exact byte
backup and a retained Git stash, switches without overwriting ignored files, and
restores any parked changes for the destination branch, including its staged state.
It never commits unfinished work, creates a checkout or grants task/review/publication
authority. Branch commits remain on their branches. OH's records and byte backups
stay in external checkout state; safety stashes are retained rather than popped.
Report a meaningful save/switch/restore briefly, without making the person manage IDs.

After a successful switch, continue the original scope preparation with
`--keep-checkout` (Codex `keep_checkout: true`) so it uses that exact branch and contents.
Propose, Design, Deliver and standalone-review repairs use this same preparation
before binding a new scope that needs a branch change. Do not move an already bound
scope to another branch. Read-only inspection does not park work.
For saved work, the existing verified Resume/Continue decision automatically saves
current work and restores the saved branch, including for its remaining publication
step; never add a separate Git confirmation.

On a recoverable failure, preserve the original request or Resume answer and retry
after fixing the reported prerequisite. Interrupted saves/restores reuse their retained
record. A failed switch restores the source work when Git leaves that branch selected.
Changed branch history, restore collisions, conflicts, hidden index flags, nested
repositories and dirty submodules need their concrete remedy; never force a switch,
overwrite a competing file or clear partial restoration with reset/clean. The saved
stash and byte snapshot remain available. Inspect both versions and resolve within
existing authority; ask only for genuinely missing ownership, scope or discard choices.

If discarding is the appropriate resolution, show the exact affected paths and local
commits, the destination commit and what will be lost before asking native human
approval. An existing explicit approval of that same effect needs no second question.
Use the saved delivery's existing recovery decision when applicable; otherwise use
Claude `AskUserQuestion` or Codex Default mode `functions.request_user_input_async`
for a separate Git disposition question, with the shared direct-reply fallback. Stop preserves files;
it is not discard permission. Offer preservation in this checkout where appropriate,
without making backups or stashes mandatory after explicit discard approval.

Before acting, recheck the shown branch/HEAD, complete local differences and target
commit. Changed work needs its own accurate disposition; an old answer cannot discard
unseen edits. Perform only the approved Git action, preserve other branches, ignored
files and nested worktrees, and verify the resulting state. Execute routine supported
repairs as the agent; do not hand Git commands back to the person merely to unblock OH.

Continue the original requested outcome after the prerequisite. A checkout decision
does not grant new task scope, renew reviews or fabricate old completion. Later human
cancellation or changed instructions still take precedence. Subsequent OH operations
must retain their native scope/decision provenance.

When the agent has deliberately selected/reconciled the checkout, use
`scope prepare ... --keep-checkout` (Codex `scope_prepare` with `keep_checkout: true`)
to preserve that selection. It disables automatic branch/base changes only; the
normal approved-design, task, scope, ownership and candidate checks still apply.
Default preparation can still perform its safe automatic branch selection, but a
failed fetch is reported rather than silently treated as current origin.
