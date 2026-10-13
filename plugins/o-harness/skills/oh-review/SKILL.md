---
name: oh-review
description: Request a fresh OH invariant review of manual changes, code, documents, a commit or completed delivery work, with optional repairs after scope approval.
---
Read `workflows/review/SKILL.md` through OH's `resource` tool with the checkout's absolute
root. In Claude use `<plugin>/scripts/oh --root <checkout> resource workflows/review/SKILL.md`,
where the plugin root is two levels above this skill (`scripts\oh.cmd` on native Windows).

Introduce the requested subject and the fresh independent reviewer agent briefly. The review
can take several minutes. Follow the shared runtime for execution, meaningful progress,
Stop, decisions and publication. Keep the coordinator small; use the returned native results.

Use the existing connected OH installation. If its tools are absent in Codex, report the
missing connection and the `/mcp` recovery step; do not substitute a shell invocation.
