# Publication and CI

Read when reviewed work reaches publication, or when recovering an existing PR handoff.
Read `workflows/decisions.md` before the publication question.
Follow the `continuation` returned by `complete`: a local commit with a pending
publication decision still needs that checkpoint. Call Claude `AskUserQuestion`
or Codex Default mode `functions.request_user_input_async` for its returned choices,
using the shared chat fallback when needed. Repair recoverable preparation
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
response. Include a clickable Markdown link, `[PR #N](URL)`, in the first published
update and the final handoff, using the URL returned by GitHub or the saved receipt.
Keep that link visible when reporting pending CI or a reconciliation error.
Attach the PR in Codex with `attach_artifact` when available; the attachment does
not replace the chat link. Human merging remains separate; published cycles stay terminal.

After reconciliation records the PR, follow its CI with `ci-wait` (Codex `ci_wait`)
instead of a single status read. It reads the published reviewed head's checks until
they reach a result, and returns one `outcome` with its `next` step. In Claude, run the
`ci-wait` command as a background Bash command: waiting costs nothing and its exit
wakes you with the result. In Codex, call `ci_wait` with a bounded `timeout` (for
example 300 seconds) and call it again while it returns `pending`, reporting only
meaningful check changes between calls. Do not end the handoff while CI is pending.

An empty, pending, failed, cancelled or skipped check set is not success. On `pass`,
report it; merging stays with the person. On `fail`, name the PR and failed checks,
then call Claude `AskUserQuestion` or Codex Default mode
`functions.request_user_input_async` with these choices:

- **Investigate CI failures** authorizes diagnosis, focused reproductions and environment
  checks, followed by preparing a justified repair proposal for approval. Include that
  proposal in the option's description. This choice does not approve a repair or rerun.
- **Stop and take over** leaves the PR and its evidence available to the person.

After **Investigate CI failures**, investigate through ordinary native tools without
another approval merely to analyze. Follow the diagnosis-first guidance in
`workflows/runtime.md` under "Failed required checks": read the failed logs
(`gh run view <run-id> --log-failed`), relevant application paths, test setup and CI
environment. Distinguish symptoms from causes and check behavior beyond the first failing
assertion. Use the smallest useful experiment to resolve material uncertainty; do not
repeat an unchanged full suite. Temporary diagnostic fixtures and normal build/test
artifacts are allowed; preserve tracked implementation and tests until a repair is approved.
Do not start an authoring run or reopen the published run just to investigate.

Present confirmed causes with evidence, remaining uncertainty, the proposed remedy and
its verification. Explain whether application behavior, tests or CI configuration need
to change and why. A timeout does not establish flakiness; a stale selector or disabled
feature does not prove the behavior behind it works. Continue useful investigation when
the remedy is unresolved, or report the concrete blocker and supported next step. Do not
present a speculative repair as ready for approval.

If changes are needed, prepare an existing-PR quick-fix scope from those conclusions,
preserving this PR's destination and original reviewed work. Describe the required
outcome and acceptance checks without turning unproven implementation guesses into
scope restrictions. Preparing the proposal is part of the accepted investigation, even
when the proposed repair needs new scope. It makes no repair and grants no execution
authority. Once the remedy is justified, prepare its scope and present the actual preview
and returned approval question below. Do not end at a recommendation or ask permission
to prepare the proposal; this approval is the person's decision about the proposed fix:

- **Approve and fix** binds that prepared scope through the existing `scope approve`
  path. Then follow normal assessment, implementation, checks and fresh review before
  updating the same PR through the existing publication process. This is the repair
  approval; do not ask a third time whether to start the fix.
- **Stop and take over** starts no correction and leaves the prepared scope available.

Use the host's native plan acceptance when that surface is available, as described in
`workflows/deliver/SKILL.md`; it replaces this repair menu rather than adding another gate.
For a retained older scope question, honor its saved labels and decision identity.
If evidence instead supports a rerun without changes, offer **Re-run failed checks**
or **Stop and take over**, explaining why a rerun is justified. Only after the rerun
choice, run `gh run rerun <run-id> --failed` and follow CI again with `ci-wait`.

For either Stop choice, finish the handoff; do not interpret it as a request to keep
planning or ask what should change in the scope. For
`no_checks`, `skipped`, `head_changed`, `unavailable`, `merged` or `closed`, report what
the outcome means and keep the resumable handoff. Do not make code changes under
publication-only authority, or enable auto-fix, auto-merge or a persistent monitor
without the person's request. A resumed publication reuses its grant and PR; it never
reruns implementation just to recover publication.
