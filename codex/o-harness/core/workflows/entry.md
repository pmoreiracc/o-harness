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

Choose an appropriate continuation, safe base update, new branch/checkout or genuine
human decision from those facts. Fetching information and changing the checkout are
separate actions. A safe update that loses no work can proceed within existing
authority. Newer origin commits do not make local work disposable.

If discarding is the appropriate resolution, show the exact affected paths and local
commits, the destination commit and what will be lost before asking native human
approval. An existing explicit approval of that same effect needs no second question.
Use the saved delivery's existing recovery decision when applicable; otherwise use
Claude `AskUserQuestion` or Codex Default mode `functions.request_user_input_async`
for a separate Git disposition question, with the shared direct-reply fallback. Stop preserves files;
it is not discard permission. Offer preservation/isolation where appropriate without
making backups or stashes mandatory after explicit discard approval.

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
