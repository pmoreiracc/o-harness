---
name: oh-deliver
description: Deliver design tasks or quick fixes, or list ready work through OH, only when explicitly invoked.
disable-model-invocation: true
---
Apply these communication requirements from the first message, including before loading the shared workflow:
- Use the role names “implementation agent” and “independent reviewer agent”; retain “agent” whenever naming either role, including in the opening. The reviewer challenges the implementation and code for bugs, weak tests, failure-path defects and invariant violations within the agreed scope.
- Briefly introduce the selected task and the implementation → project checks → independent review process once. Say this can take several minutes. Use natural wording around the role names.
- During work, explain observed changes, handoffs and actual findings from OH's returned progress. When work finishes, lead with the recorded review outcome, round count and findings (explicitly “no findings” for a clean review with none), then report the commit and next choice. Do not announce completion without the review outcome.

Use the workflow below for execution steps and returned decisions.

Describe routine handoffs through the work and its result, for example “The task preview is ready to review.” Keep skill-routing instructions out of product copy; the workflow supplies the current question and its context.

Resolve the `scripts/oh` command at the plugin root, two levels above this skill directory (from PowerShell or cmd on Windows, use `scripts\oh.cmd` there). Use that absolute path; never create integration files in a product repository. If setup is missing, run the command with `setup` explicitly. Never install or start anything merely because this skill was discovered.

Read that workflow and follow it: in Codex, call the o-harness `resource` tool with `path` `workflows/deliver/SKILL.md` and the checkout's absolute path as `root`; in Claude, run `<plugin>/scripts/oh --root <project-root> resource workflows/deliver/SKILL.md`. Keep the coordinator small; the shared runner owns workers, checks, reviews, commits and batch boundaries. Do not recreate that loop in the parent conversation.

If Codex lists no o-harness tools, OH's tool server did not start: tell the person to type `/mcp` to see why, then start a new Codex session; don't run these OH commands from Codex's shell instead.
