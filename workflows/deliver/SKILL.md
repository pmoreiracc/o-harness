---
name: deliver
description: Deliver approved design tasks, prepare an approved quick fix, or list ready work through the shared runner.
---
Use the absolute `<plugin>/scripts/oh` entry supplied by the invoking skill. Resolve the
selected Git checkout. Run `--root <checkout> config`; if unregistered, run `init` once: it
joins the project of the same repository, or names a new one after the repository (pass
`--name` only when the user asks for another name, or when `config` or `init` says the name is
taken or ambiguous; then ask the user which name to use). If `config` then lists no checks, save appropriate ordinary
project checks with `config set checks '<JSON list>'` and tell the user which; never replace
existing checks here. No OH files, hooks or settings belong in the product.
Read existing product instructions and business documents. Generic OH does not require ADRs.

Pass the user's arguments to `--root <checkout> deliver [arguments]`; quote prose as one
argument. OH's parser selects the mode; do not infer a different workflow:

- No arguments lists ready designs and unavailable designs with their reasons. Show the
  ready commands and limits. Do not run an older active batch merely because the list is empty.
- `0005 [track]` verifies the native human invocation and immediately runs the next ready
  tasks from that approved design. Plans can live in the repository or privately. There is
  no prepare step or second trigger. Show the resulting checkpoint and limits.
- Prose returns `quick_fix` with the original intent. Inspect that fix, save a bounded JSON
  manifest under the project's external OH directory, and call `prepare <absolute-path>`.
  Tasks need id, title, instructions and optional needs/dependency IDs, ordered by dependency.
  Use simple/standard/complex difficulty with rationale when known. Present the proposed
  tasks, returned `limits` sentence and exact trigger once. Only a new genuine human
  invocation approves that prepared scope; never echo the trigger as approval.
- `request:<id>` verifies and runs the already prepared quick-fix scope. The older
  `0005 [track] request:<id>` consumer-profile spelling remains supported.

If OH refuses a command, explain its concrete recovery step. Do not reinterpret a refused
design number as permission for a quick fix, or run a different active design.

The runner owns automatic models, fresh workers, checks, review, final rendering, commits
and batch boundaries. Do not reproduce that loop in the parent conversation. At a batch
checkpoint show continue / PR / stop with the returned `limits` sentence; at completion show PR / stop. Exact choices from the
owning human session are verified by `run`; they never silently renew another allowance.
Keep results concise and link saved evidence. Human merging remains separate.
