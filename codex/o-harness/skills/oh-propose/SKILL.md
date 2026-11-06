---
name: oh-propose
description: Route one supplied idea to a roadmap row, an approved-design task or an improvement when explicitly invoked as /oh-propose.
argument-hint: "<what you want to add>"
---
Load `workflows/propose/SKILL.md` through OH's resource entry and follow it. Introduce
the proposal agent's routing work and the invariant reviewer agent’s review of any resulting documents.

Resolve the absolute plugin launcher two levels above this skill: `scripts/oh`
(`scripts\oh.cmd` on native Windows). Keep OH configuration and evidence outside
consumer repositories. Discovery alone does not authorize setup or execution.

In Codex first call `mcp__o_harness__resource` with the checkout's absolute `root`
and `path: "workflows/propose/SKILL.md"`. In code mode, call
`text(await tools.mcp__o_harness__resource({root: "<checkout>", path: "workflows/propose/SKILL.md"}))`
inside `functions.exec`. In Claude use
`<plugin>/scripts/oh --root <checkout> resource workflows/propose/SKILL.md`.

OH's `resource` is a tool. MCP resource/template listings do not discover OH tools
or establish connection health. If tool lookup is needed, match `mcp__o_harness__`
in the available tool inventory. A failed text search is not a connection failure.
Retry a failed read once using the actual tool. For an uncertain state-changing call,
inspect its saved outcome before retrying with the same inputs. Preserve the current
request and approvals through recovery. Diagnose a connection failure from the actual
OH tool error; report an unavoidable host action only after supported recovery fails.
