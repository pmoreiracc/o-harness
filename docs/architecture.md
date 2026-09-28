# Architecture

| Path | Contents |
|---|---|
| `runtime/oh/` | The OH engine: run state, host adapters, checks, reviews, analytics and the dashboard server |
| `plugins/o-harness/` | The plugin both hosts install: skills, the prompt hook and the launcher |
| `workflows/` | Instructions the plugin skills load for each workflow |
| `prompts/` | The shared independent-reviewer prompt |
| `config/` | Default settings and OH's own invariants |
| `dashboard/` | Static dashboard files, no build step |
| `integrations/` | Test and packaging scripts |
| `.claude/`, `.codex/` | Settings for developing OH itself |

## Install layout

A built plugin contains the engine. On the first OH command, the plugin's launcher copies it
to `~/.local/share/o-harness/versions/<commit>` and marks it active when its version is
newer than the active one. Each run records its version and keeps using it until it ends,
so an update never changes a running batch. Both hosts share the installed engine and the
data folder.

## Authority

Only your own typed message approves work. The prompt hook records where to find it, and
OH confirms it in the host's saved transcript before starting. Model output, elapsed time
and restarts never approve anything. Approved scope is fixed when prepared.

A choice can also be a click. In Claude, the agent shows OH's menu with Claude's own question
tool; a hook refuses a menu whose answer the model filled in, and OH reads the click from the
saved transcript of the conversation that owns the run. Nothing is handed over in between, and
only the latest click on exactly the menu OH is waiting on counts, so a click on an older menu,
in another conversation or on an altered menu never applies. A menu word typed in Claude
is read from the transcript the same way, so only the person's single latest answer to the
current menu counts, typed or clicked; if OH refuses it, no earlier answer applies instead. Only
messages Claude saved as the person's count, never another agent's or a notification; if OH can't
read a typed menu word as the latest answer, it applies nothing and asks the person to choose again.
In Codex, OH's MCP server shows the menu itself and records the click, which travels from the
Codex menu to OH without passing through the model; a click spends any menu word typed before it.

In Codex, the agent runs OH through that same server rather than the shell. Codex's sandbox lets
shell commands write only inside the project, while OH's state lives in its own folder so the
model can't write it; Codex runs a plugin's MCP server outside that sandbox. Each everyday OH
command (status, init, deliver, prepare, start, run, pause, resume, stop and a few read-only ones)
is a tool that runs the command through the plugin's `oh` launcher, as the shell would: with the
person's own shell setup (read once from their login shell, since Codex gives the server almost
none of it) and Codex's values for OH on top. OH's progress lines become progress notifications.
The server runs from the core the plugin carries, so its tools exist before setup and right after
an update; the launcher still picks and activates the installed core. Stopping a tool call does
not stop OH, which keeps working within its grant; `status` and `stop` still apply.
Commands that change what OH runs on the machine (settings and checks, setup, host trust,
backups, services) are not tools, so Codex asks the person before they run. Codex puts the
calling conversation in each request's metadata, which the model can't set: a tool acts only on
the Git checkout that conversation works in (read from Codex's saved session), never on a
repository around a nested one, a menu answers only in
the conversation that started the run, and OH checks a typed choice against that conversation's
saved turn as before. The server is started only by Codex from the plugin, never by an `oh`
command. OH's worker commands turn OH's Codex plugin off, and the server refuses any tool when an
OH worker started it.

The runner keeps a hash-chained journal per run. For each task it picks a model profile,
starts a fresh worker, runs the checks, starts an independent reviewer on the exact tree
and commits only the reviewed tree, with an `OH-Evidence` trailer. `oh pr-summary` checks
that trailer against every commit on the branch.

Workers run through the checked host CLI with API-key variables removed. They can't write
OH state or Git internals; reviewers are read-only. Pause and stop share a lock with commit,
so a stop never leaves a half-recorded task.

## Data

The SQLite analytics database is rebuilt from saved events and never grants anything.
Backup and restore lock the data folder.

## Not yet supported

- One task runs at a time. Parallel tasks are tracked in
  [issue 1](https://github.com/pmoreiracc/o-harness/issues/1).
- Other hosts need a tested adapter first
  ([issue 4](https://github.com/pmoreiracc/o-harness/issues/4)).
