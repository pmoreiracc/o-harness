---
name: oh-start
description: Choose an OH workflow only when explicitly invoked.
---
Resolve the `scripts/oh` command at the plugin root, two levels above this skill directory. Use that absolute path; never create integration files in a product repository. If setup is missing, run the command with `setup` explicitly. Never install or start anything merely because this skill was discovered.

Run `<plugin>/scripts/oh --root <project-root> resource workflows/oh/SKILL.md` and follow that workflow. Keep the coordinator small; the shared runner owns workers, checks, reviews, commits and batch boundaries. Do not recreate that loop in the parent conversation.
