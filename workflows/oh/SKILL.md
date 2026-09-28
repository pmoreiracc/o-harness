---
name: oh
description: Explicit OH workflow through the shared external runner.
---
How to run OH commands, such as `config`, `init`, `deliver` or `run`: in Codex, call the o-harness tool of
that name (use `prepare_design` and `pr_summary` for the hyphenated ones) with the checkout's absolute path as
`root`; never run OH from Codex's shell, which cannot write OH's state. In Claude, run the absolute
`<plugin>/scripts/oh` entry supplied by the invoking skill as `<plugin>/scripts/oh --root <checkout> <command>`.
Changing settings (`config set`, `config unset`) is never a tool: run it with `<plugin>/scripts/oh` on either
host, so the person approves it.

Resolve the selected Git checkout. Run `config`; if unregistered, run `init` once: it
joins the project of the same repository, or names a new one after the repository (pass
`--name` only when the user asks for another name, or when `config` or `init` says the name is
taken or ambiguous; then ask the user which name to use). If `config` then lists no checks, save appropriate ordinary
project checks with `config set checks '<JSON list>'` and tell the user which; never replace
existing checks here. No OH files, hooks or settings belong in the product.
Read existing product instructions and business documents. Generic OH does not require ADRs.

For already prepared scope, run `start` to verify the native human
invocation and execute its batch. For new scope, inspect the agreed work and prepare a bounded
task list: in Codex, pass it to the `prepare` tool as `tasks`; in Claude, save it as a JSON object with `tasks`
under the project's external OH directory and run `prepare <absolute-path>`.
Tasks need id, title, instructions and optional needs/dependency IDs, ordered by dependency.
Use explicit simple/standard/complex difficulty with rationale when known. Present the
scope, the returned `limits` sentence and the trigger once; only a new genuine human invocation grants that prepared
scope. Never echo the trigger yourself and treat it as approval. For a product with the
external consumer-v1 profile, `prepare-design <number> [track]` binds its approved design.

The runner owns automatic models, fresh workers, checks, review, final rendering, commits
and batch boundaries. Do not reproduce that loop in the parent conversation. At a batch
checkpoint show continue / PR / stop with the returned `limits` sentence; at completion show PR / stop. Exact choices from the
owning human session are verified by `run`; they never silently renew another allowance.
When OH's output has a `gate`, show its choices as a menu. In Claude, call the question tool (AskUserQuestion)
with exactly `gate.ask` and no `answers` field. In Codex, call the o-harness `choose` tool. Then run `run`,
which carries out the answer, unless `choose` says nothing is left to run. Never answer for the person. Typed
choices (`gate.choices`) stay valid everywhere, and are the fallback when no menu can be shown.
Keep results concise and link saved evidence. Human merging remains separate.
