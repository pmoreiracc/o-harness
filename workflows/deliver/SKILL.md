---
name: deliver
description: Deliver approved design tasks, prepare a bounded quick fix, or list ready work through OH.
---
Read `workflows/runtime.md` once through the same OH resource entry and follow its shared execution protocol.

A numbered invocation selects a design, not a task. Introduce the design number; name the actual
task and work only after OH selects it. For a quick fix, the first result is a scope preview.

Pass the user's arguments to `deliver` without reinterpreting a refusal as a different workflow:

- No arguments lists ready/unavailable designs and reasons. Show the ready commands and limits,
  then ask which design or quick fix they want. An empty list does not authorize an older run.
- `0005 [track]` starts or resumes approved work directly. OH preserves a stopped task's useful
  draft, findings, settings and remaining allowance before any branch refresh. Relay its brief
  continuation message. No preparation step or second trigger is required.
  If the saved batch is complete, show its existing final decision. Do not start another task
  or rerun implementation, checks or review. A recorded publication choice continues publication.
- Prose returns `quick_fix`. Inspect that bounded change and prepare tasks with `id`, `title`,
  `instructions` and optional ordered `needs`. In Codex call `prepare`; in Claude save the
  manifest under external OH project storage and use `prepare <path>`. Present the returned
  preview, limits and approval question. OH assesses difficulty at runtime.
  Inspect the configured base for ordinary new work, or the existing PR's head when the
  person explicitly asks to update that PR. Pass its number as `prepare.pr` in Codex or
  `prepare --pr NUMBER <path>` in Claude. Preparation selects and validates that branch;
  do not reset, rebase or switch branches to bypass a refusal. A published delivery remains
  finished; this is a new bounded correction with its own approval and fresh review.
- `request:<id>` runs the already prepared scope; the older consumer-profile spelling remains
  supported. A prepared identifier is not an approval until the human sends or approves it.

If OH asks for a track or missing selection, ask in ordinary conversation. Their next reply
supplies that input. For a bare/prose invocation, call `run` when the input is complete so OH
binds it before preparation. Never choose a different active design or write plan files yourself.
A completed design returns its publication decision and admits no more implementation.

Use the shared execution protocol for progress, decisions, review results and publication.
