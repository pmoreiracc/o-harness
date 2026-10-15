---
name: oh-review
description: Request a fresh OH invariant review of manual changes, code, documents, a commit or completed delivery work, with optional repairs after scope approval.
---
Resolve the requested subject, then load `workflows/review/SKILL.md` through OH's
resource entry. Introduce the fresh independent reviewer agent briefly. Standalone
review produces feedback; fixes use the existing bounded quick-fix approval.

Resolve the absolute plugin launcher two levels above this skill: `scripts/oh`
(`scripts\oh.cmd` on native Windows). Keep OH configuration and evidence outside
consumer repositories. Discovery alone does not authorize setup or execution.

In Codex use the connected OH tools with the checkout's absolute `root`; read resources
with `resource`. In Claude use `<plugin>/scripts/oh --root <checkout> resource <path>`.
If the Codex connection is missing, report it with the `/mcp` recovery step; do not
bypass it with shell writes to OH state.
