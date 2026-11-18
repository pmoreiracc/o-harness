---
name: oh-deliver
description: Deliver a named approved design, for example “Deliver approved design 0001”, or prepare an explicitly requested OH quick fix. List ready work on request.
---
For an explicit skill invocation or a clear request to deliver through OH, load
`workflows/deliver/SKILL.md` through OH's resource entry. A typed request naming an
approved design, such as “Deliver approved design 0001”, qualifies. A general coding
request does not select OH. A readiness or status question calls for facts only.
Clarify ambiguous delivery intent before preparing scope or changing the checkout.

A number identifies a design. Check for matching saved work before naming the
actual task. For new work, introduce the implementation agent, affected checks and
invariant reviewer once the task is selected. A quick fix needs its scope approval.

Resolve the absolute plugin launcher two levels above this skill: `scripts/oh`
(`scripts\oh.cmd` on native Windows). Keep OH configuration and evidence outside
consumer repositories. Discovery alone does not authorize setup or execution.

In Codex first call `mcp__o_harness__resource` with the checkout's absolute `root`
and `path: "workflows/deliver/SKILL.md"`. In code mode, call
`text(await tools.mcp__o_harness__resource({root: "<checkout>", path: "workflows/deliver/SKILL.md"}))`
inside `functions.exec`. In Claude use
`<plugin>/scripts/oh --root <checkout> resource workflows/deliver/SKILL.md`.

OH's `resource` is a tool. MCP resource/template listings do not discover OH tools
or establish connection health. If tool lookup is needed, match `mcp__o_harness__`
in the available tool inventory. A failed text search is not a connection failure.
Retry a failed read once using the actual tool. For an uncertain state-changing call,
inspect its saved outcome before retrying with the same inputs. Preserve the current
request and approvals through recovery. Diagnose a connection failure from the actual
OH tool error; report an unavoidable host action only after supported recovery fails.
