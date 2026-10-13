---
name: oh-deliver
description: Deliver design tasks or quick fixes, or list ready work through OH, only when explicitly invoked.
disable-model-invocation: true
---
Apply these communication requirements from the first message, including before loading the shared workflow:
- Use the role names “implementation agent” and “independent reviewer agent”; retain “agent” whenever naming either role, when describing an active phase. The reviewer challenges the implementation and code for bugs, weak tests, failure-path defects and invariant violations within the agreed scope.
- First check saved work through the shared workflow. Once OH selects active work, briefly introduce the actual task and phase; a saved decision needs its question, not a new implementation introduction. Use natural wording around the role names.
- A numbered invocation selects a design: say “design 0005”, never “task 0005”. Name the actual task number and its work only after OH reports its selection; do not guess them from the design number.
- Keep one native OH execution call in flight using the host’s yielding/background support. Follow the shared workflow’s host-specific observation steps and relay new public worker focus in one short sentence, deduplicating by attempt and focus id; never start a second execution call or repeat unchanged status. Native progress reports actual transitions. When work finishes, lead with the recorded review outcome, round count and findings (explicitly “no findings” for a clean review with none), then report the commit and next choice. Do not announce completion without the review outcome.

Use the workflow below for execution steps and returned decisions.

Describe routine handoffs through the work and its result, for example “The task preview is ready to review.” Keep skill-routing instructions out of product copy; the workflow supplies the current question and its context.

Resolve the `scripts/oh` command at the plugin root, two levels above this skill directory (from PowerShell or cmd on Windows, use `scripts\oh.cmd` there). Use that absolute path; never create integration files in a product repository. If setup is missing, run the command with `setup` explicitly. Never install or start anything merely because this skill was discovered.

Read that workflow and follow it: in Codex, call the o-harness `resource` tool with `path` `workflows/deliver/SKILL.md` and the checkout's absolute path as `root`; in Claude, run `<plugin>/scripts/oh --root <project-root> resource workflows/deliver/SKILL.md`. Keep the coordinator small; the implementer owns implementation and checks; the shared runner owns evidence validation, reviews, commits and batch boundaries. Do not recreate that loop in the parent conversation.

If Codex lists no o-harness tools, OH's tool server did not start: tell the person to type `/mcp` to see why, then start a new Codex session; don't run these OH commands from Codex's shell instead.
