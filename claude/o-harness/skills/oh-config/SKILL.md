---
name: oh-config
description: Show or change your OH settings.
disable-model-invocation: true
---
Resolve the `scripts/oh` command at the plugin root, two levels above this skill directory (from PowerShell or cmd on Windows, use `scripts\oh.cmd` there). Use that absolute path; never create integration files in a product repository. If setup is missing, run the command with `setup` explicitly.

Read the settings: in Codex, call the o-harness `config` tool with the checkout's absolute path as `root`; in Claude, run `<plugin>/scripts/oh --root <project-root> config`. It returns every setting that exists, with its value, default, source, allowed values and meaning, this project's `checks`, and the settings `file`. That list is the only source of truth: never mention, suggest or write a setting that isn't in it.

If Codex lists no o-harness tools, OH's tool server did not start: tell the person to type `/mcp` to see why, then start a new Codex session; don't run these OH commands from Codex's shell instead.

**No request:** show a short list of the settings (key, value, meaning) and the checks, give the `file` path, say that `oh config open` opens it and that editors explain each key through its `$schema`, and report any `note`.

Explain settings through their practical effect, for example “This project will run two tasks per batch instead of one.” Keep the decision context in chat and the menu short; report the actual result without quoting this skill as the reason for the question.

**A request in words** (for example "let OH run 15 tasks per batch"):
1. Map it to the keys in the list it names; one request may change several. If a part matches nothing in the list, say that OH has no such setting and leave it out; don't invent one. If it's ambiguous, ask which of the matching keys they mean.
2. A change applies to this project unless the user says it's for every project; then add `--global`. Checks always belong to the project.
3. Show each `key: current → new` with its meaning, allowed values and whether it's for this project or every project, and ask the user to confirm, offering the choices as a menu: in Claude, the question tool (AskUserQuestion); in Codex, the o-harness `confirm` tool, which waits for the click. If no answer comes back, ask in plain text and end your turn.
4. Only after they confirm, run `<plugin>/scripts/oh --root <project-root> config set <key> <value>` in the shell on either host (configuration writes use this command, not an OH tool) once per key (or `config unset <key>` to go back to the value before it). `config set checks '<JSON list>'` replaces the whole list, so show the full new list before confirming.
5. Report the command's result exactly, including its note. Never edit the settings file yourself: `oh config set` is the only writer, and it rejects unknown keys and invalid values.
