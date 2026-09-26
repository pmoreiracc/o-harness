---
name: oh-config
description: Show or change OH's settings for this project.
disable-model-invocation: true
---
Resolve the `scripts/oh` command at the plugin root, two levels above this skill directory. Use that absolute path; never create integration files in a product repository. If setup is missing, run the command with `setup` explicitly.

Run `<plugin>/scripts/oh --root <project-root> config`. It returns every setting that exists, with its value, default, source, allowed values and meaning. That list is the only source of truth: never mention, suggest or write a setting that isn't in it.

**No request:** show a short list of the settings (key, value, meaning), say where they live (`file`), and that editors explain each key through the `$schema` in `oh.json`.

**A request in words** (for example "let OH run 15 tasks per batch"):
1. Map it to the keys in the list it names; one request may change several. If a part matches nothing in the list, say that OH has no such setting and leave it out; don't invent one. If it's ambiguous, ask which of the matching keys they mean.
2. Show each `key: current → new` with its meaning and allowed values, and ask the user to confirm, offering the choices as selectable options (your host's native question tool) when it has one.
3. Only after they confirm, run `<plugin>/scripts/oh --root <project-root> config set <key> <value>` once per key (or `config unset <key>` to go back to the default). If the result says the project has no settings file yet, ask whether to keep settings in the repository (`--location repo`, creates `oh.json`) or only on this machine (`--location private`), then run it again with their choice.
4. Report the command's result exactly, including its note. Never edit the settings file yourself: `oh config set` is the only writer, and it rejects unknown keys and invalid values.
