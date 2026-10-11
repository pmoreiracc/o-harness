---
name: oh-design
description: Turn one roadmap initiative into an actionable plan through specialist drafting and independent review, only when explicitly invoked as /oh-design <slug>.
argument-hint: "<roadmap-slug>"
disable-model-invocation: true
---
When invoked without an argument, ask “Which roadmap initiative would you like to design?” in plain chat and end your turn before calling any tools. After the person answers, load the workflow below and continue with their answer. Asking needs no saved waiting record or transcript check. Never invent the argument.

Apply these communication requirements from the first process message, including before loading the shared workflow:
- Use the role names “planning agent” and “independent reviewer agent”; retain “agent” whenever naming either role, including in the opening. The reviewer challenges the document's approach, tasks and assumptions against the project's requirements.
- Once the initiative is supplied, briefly introduce its drafting and independent review process once, including any skill-use announcement in that same explanation. Say this can take several minutes. Use natural wording around the role names.
- During work, explain observed changes, handoffs and actual findings from OH's returned progress. When review finishes, lead with the recorded review outcome, round count and findings (explicitly “no findings” for a clean review with none), then report the saved document or commit and next choice. Do not announce completion without the review outcome.

Use the workflow below for execution steps and returned decisions.

Describe routine handoffs through the work and its result, for example “The task preview is ready to review.” Keep skill-routing instructions out of product copy; the workflow supplies the current question and its context.

Resolve the `scripts/oh` command at the plugin root, two levels above this skill directory (from PowerShell or cmd on Windows, use `scripts\oh.cmd` there). Use that absolute path; never create integration files in a product repository. If setup is missing, run the command with `setup` explicitly. Never install or start anything merely because this skill was discovered.

Read that workflow and follow it: in Codex, call the o-harness `resource` tool with `path` `workflows/design/SKILL.md` and the checkout's absolute path as `root`; in Claude, run `<plugin>/scripts/oh --root <project-root> resource workflows/design/SKILL.md`. Keep the coordinator small; the shared runner owns workers, checks, reviews, commits and batch boundaries. Do not recreate that loop in the parent conversation.

If Codex lists no o-harness tools, OH's tool server did not start: tell the person to type `/mcp` to see why, then start a new Codex session; don't run these OH commands from Codex's shell instead.
