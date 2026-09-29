---
name: oh
description: Explicit OH workflow through the shared external runner.
---
How to run OH commands, such as `config`, `init`, `deliver` or `run`: in Codex, call the o-harness tool of
that name (use `prepare_design` and `pr_summary` for the hyphenated ones) with the checkout's absolute path as
`root`; never run OH from Codex's shell, which cannot write OH's state. In Claude, run the absolute
`<plugin>/scripts/oh` entry supplied by the invoking skill as `<plugin>/scripts/oh --root <checkout> <command>`.
Changing settings (`config set`, `config unset`) is never a tool: run it with `<plugin>/scripts/oh` on either
host, so the person approves it. Stopping a long Codex tool call does not stop OH: call `status` to follow it and
`stop` to end it. When these instructions say to ask the person something that is not a `gate`, offer the choices
as a menu: in Claude, the question tool (AskUserQuestion); in Codex, the o-harness `confirm` tool, which waits for
the click (never Codex's own question tool, which closes when your turn ends).

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
save appropriate ordinary project checks with `config set checks '<JSON list>'`, tell the user which, and run
the command again; never replace existing checks here. No OH files, hooks or settings belong in the product.
Read existing product instructions and business documents. Generic OH does not require ADRs.

For already prepared scope, run `start` to verify the native human
invocation and execute its batch. For new scope, inspect the agreed work and prepare a bounded
task list: in Codex, pass it to the `prepare` tool as `tasks`; in Claude, save it as a JSON object with `tasks`
under the project's external OH directory and run `prepare <absolute-path>`.
Tasks need id, title, instructions and optional needs/dependency IDs, ordered by dependency.
Give each task `difficulty` (simple, standard or complex) and a short `difficulty_reason`: OH picks
the model that builds it from them. Present the
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
