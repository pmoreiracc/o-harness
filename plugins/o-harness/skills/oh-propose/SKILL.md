---
name: oh-propose
description: Route one idea to a roadmap row, a task in an approved design, or an improvement, only when explicitly invoked as /oh-propose <idea>.
argument-hint: "<what you want to add>"
disable-model-invocation: true
---
When invoked without an argument, ask “What would you like to propose?” in plain chat and end your turn before calling any tools. After the person answers, load the workflow below and continue with their answer. Asking needs no saved waiting record or transcript check. Never invent the argument.

Apply these communication requirements from the first process message, including before loading the shared workflow:
- Use the role names “proposal agent” and “independent reviewer agent”; retain “agent” whenever naming either role, including in the opening. The reviewer challenges the assumptions and dependencies of any resulting documents.
- Once the idea is supplied, briefly introduce how the proposal agent finds where it belongs and how document saving and independent review follow the person's approval. Say this can take several minutes and introduce the process once. Use natural wording around the role names.
- During work, explain observed changes, handoffs and actual findings from OH's returned progress. When review finishes, lead with the recorded review outcome, round count and findings (explicitly “no findings” for a clean review with none), then report the saved proposal or commit and next choice. If the approved route writes no document and needs no review, report that actual outcome instead.

Use the workflow below for execution steps and returned decisions.

Describe routine handoffs through the work and its result, for example “The task preview is ready to review.” Keep skill-routing instructions out of product copy; the workflow supplies the current question and its context.

Resolve the `scripts/oh` command at the plugin root, two levels above this skill directory (from PowerShell or cmd on Windows, use `scripts\oh.cmd` there). Use that absolute path; never create integration files in a product repository. If setup is missing, run the command with `setup` explicitly. Never install or start anything merely because this skill was discovered.

Read that workflow and follow it: in Codex, call the o-harness `resource` tool with `path` `workflows/propose/SKILL.md` and the checkout's absolute path as `root`; in Claude, run `<plugin>/scripts/oh --root <project-root> resource workflows/propose/SKILL.md`. Keep the coordinator small; the shared runner owns workers, checks, reviews, commits and batch boundaries. Do not recreate that loop in the parent conversation.

If Codex lists no o-harness tools, OH's tool server did not start: tell the person to type `/mcp` to see why, then start a new Codex session; don't run these OH commands from Codex's shell instead.
