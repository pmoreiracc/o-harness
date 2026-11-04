---
name: oh-review
description: Request a fresh OH invariant review of manual changes, code, documents, a commit or completed delivery work, with optional repairs after scope approval.
---
Load `workflows/review/SKILL.md` through OH's resource entry and inspect saved work
before resolving a missing subject or binding another review. For selected unfinished
review work, present the prepared Resume question once with Claude `AskUserQuestion`
or Codex Default mode `functions.request_user_input_async`, even with a matching subject.
Introduce a fresh invariant reviewer agent only when the saved phase actually needs one. Standalone
review produces feedback; fixes use the existing bounded quick-fix approval.

Resolve the absolute plugin launcher two levels above this skill: `scripts/oh`
(`scripts\oh.cmd` on native Windows). Keep OH configuration and evidence outside
consumer repositories. Discovery alone does not authorize setup or execution.

In Codex first call `mcp__o_harness__resource` with the checkout's absolute `root`
and `path: "workflows/review/SKILL.md"`. In code mode, call
`text(await tools.mcp__o_harness__resource({root: "<checkout>", path: "workflows/review/SKILL.md"}))`
inside `functions.exec`. In Claude use
`<plugin>/scripts/oh --root <checkout> resource workflows/review/SKILL.md`.

OH's `resource` is a tool. MCP resource/template listings do not discover OH tools
or establish connection health. If tool lookup is needed, match `mcp__o_harness__`
in the available tool inventory. A failed text search is not a connection failure.
Retry a failed read once using the actual tool. For an uncertain state-changing call,
inspect its saved outcome before retrying with the same inputs. Preserve the current
request and approvals through recovery. Diagnose a connection failure from the actual
OH tool error; report an unavoidable host action only after supported recovery fails.
