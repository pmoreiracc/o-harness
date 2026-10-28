# Publication and CI

Read when reviewed work reaches publication, or when recovering an existing PR handoff.
Read `workflows/decisions.md` before the publication question.
Follow the `continuation` returned by `complete`: a local commit with a pending
publication decision still needs that checkpoint. Repair recoverable preparation
failures within scope; report any unresolved step instead of claiming the handoff finished.
If the person already chose the checkpoint's PR option, bind that answer using its
existing decision identity and proceed; do not request a second publication approval.

Publication requires the human decision bound to reviewed HEAD and destination. Use
`publication` to reconcile the existing PR before pushing or creating one. A failed
lookup is not permission to create another. Use `pr-summary` as verified facts for a
human-readable PR body, rather than copying an audit dump. Per task, explain the
completed behavior, review round count, final receipt identity and elapsed time,
verification, final verdict, and concise findings with their actual dispositions.
Read the complete final review receipt and summarize its evidence: anchors read,
scope examined, concrete attacks and results, and limits. Keep that narrative fluid;
no rigid receipt headings or prose parser are required. Summarize earlier rounds
and recurring findings; do not paste full receipts, repeated findings, raw JSON,
transcripts or local evidence paths. Do not move an audit dump into PR comments
as a size workaround. Include why work stopped and the short task checkpoint history. Full original receipts, findings and decisions stay in OH's
saved workflow history; a PR summary never replaces them or grants authority.
Retain the single generated `oh-publication` comment unchanged so reconciliation
can recognize an updated description independently of its prose. For a large batch,
summarize and group the findings further; never split approved work or rerun reviews
because of description length. Write the finished body to an external file, push
the authorized head/branch without force, and create or update only the matching
PR with `--body-file`. Re-run publication reconciliation after an uncertain
response. Attach the PR in Codex with `attach_artifact` when available. Human merging
remains separate; published cycles stay terminal.

After reconciliation records the PR, follow its CI with `ci-wait` (Codex `ci_wait`)
instead of a single status read. It reads the published reviewed head's checks until
they reach a result, and returns one `outcome` with its `next` step. In Claude, run the
`ci-wait` command as a background Bash command: waiting costs nothing and its exit
wakes you with the result. In Codex, call `ci_wait` with a bounded `timeout` (for
example 300 seconds) and call it again while it returns `pending`, reporting only
meaningful check changes between calls. Do not end the handoff while CI is pending.

An empty, pending, failed, cancelled or skipped check set is not success. On `pass`,
report it; merging stays with the person. On `fail`, read the failed jobs' logs
(`gh run view <run-id> --log-failed`), give a short diagnosis, then ask one native question:

- **Prepare a fix for PR #N** starts the existing-PR quick-fix correction for this PR. It
  still needs its own scope approval, implementation, checks and fresh review before
  the same PR is updated.
- **Re-run the failed jobs** suits a diagnosed flaky or infrastructure failure: run
  `gh run rerun <run-id> --failed`, then follow CI again with `ci-wait`.
- **Leave it** keeps the published PR and a resumable handoff.

This question routes the person's next action; it grants nothing by itself. For
`no_checks`, `skipped`, `head_changed`, `unavailable`, `merged` or `closed`, report what
the outcome means and keep the resumable handoff. Do not make code changes under
publication-only authority, or enable auto-fix, auto-merge or a persistent monitor
without the person's request. A resumed publication reuses its grant and PR; it never
reruns implementation just to recover publication.
