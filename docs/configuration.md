# Configuration

The easy way: `/oh-config` (Codex: `$oh-config`). With nothing after it, it lists every
setting with its value and meaning. Or say what you want, for example
`/oh-config let OH run 15 tasks per batch`; it shows and applies the authorized change.
If the request leaves a real choice, the agent asks through the native host or chat.
There is no separate OH confirmation menu.

## Your settings file

All your settings live in one file that belongs to you: `~/.config/o-harness/settings.json`
(or `$XDG_CONFIG_HOME/o-harness/settings.json`). OH creates it when you register a project,
and never puts anything in your repositories. `oh config open` opens it. If you run OH with
its own data folder (`OH_DATA_HOME`), that folder keeps its own settings in
`<OH_DATA_HOME>/config/settings.json`, so it never reads or changes yours.

OH remembers where your settings are. If a process looks elsewhere, for example a host that
doesn't see the `XDG_CONFIG_HOME` your shell sets, or the file disappears, OH stops and says
so instead of using its defaults. `oh config open` or `oh config set` starts a new file.

Top-level values apply to every project. A project's section under `projects`, named as you
named the project at `oh init`, overrides them for that project and holds its checks:

```json
{
  "$schema": "./settings.schema.json",
  "models": {"claude": {"review": {"effort": "max"}}},
  "projects": {
    "my-app": {
      "tasks_per_batch": 15,
      "review_rounds": 12,
      "checks": [{"name": "tests", "command": ["npm", "test"]}]
    }
  }
}
```

Leave out anything you don't want to change: OH's defaults fill the rest, so a better
default in a new release still reaches you. The `$schema` line makes VS Code, Cursor and
JetBrains explain each key, suggest allowed values and underline mistakes.

Each layer overrides the one before it, key by key:

1. OH's defaults (`config/defaults.json` in this repository)
2. Your top-level settings, for every project
3. The project's section, `projects.<name>`

A section belongs to one repository: `oh init` asks unrelated repositories for different
names, while sibling worktrees join their repository's project. Historical same-name
profiles of a verified Git repository can share the section without merging their IDs,
work or approvals. New worktrees prefer the present main checkout's profile when these
records coexist; `oh config` names the project an unregistered checkout would join.
A same-path restore retaining the saved Git history keeps its registration and name.
`oh rename <new name>` renames a project and its section; it refuses a name whose section
already holds other settings. If a section is left from an earlier project with that name,
`oh init` says which settings in it apply.
Renaming a historical same-repository profile copies its shared settings and leaves the
original section for its peers. Private documents owned by that profile retain their
location; a folder owned by a sibling is left untouched and the new name gets its own
folder. Conflicting explicit private locations still require resolution.

## Changing settings

- `oh config` lists every setting with its value, where it comes from, the allowed values
  and its meaning, plus this project's checks.
- `oh config set <key> <value>` changes this project's value; add `--global` to change it
  for every project.
- `oh config unset <key>` (optionally `--global`) goes back to the value from the layer before.
- `oh config open` opens the file, if you prefer to edit it yourself.

OH checks the whole file each time it reads it. An unknown key, a bad value, a key written
twice or broken JSON stops OH with the file and the exact key named, such as
`projects.my-app.review_rounds`.
Settings are captured when a run is prepared, so a change applies to the next run you start;
**continue** keeps the settings the run was approved with. Each prepared approval and each
**continue** checkpoint repeats the numbers it covers, for example "Runs 5 of 12 tasks, then
asks you to continue, up to 3 review rounds each".

Updates never rewrite your settings. If a release renames or removes a setting, OH moves it
for you once and keeps the previous file in `backups/` next to `settings.json`. Settings
files from older versions of OH (`checks.json`, `config.json` and `config.local.json` in a
project's OH folder, and `settings/defaults.json`) are moved into `settings.json` the same
way, and each project keeps the values it had. A file OH can't move (a value it doesn't
accept, or a value its section already sets differently) stays where it is and stops only
its own project, or all historical profiles sharing that repository's section (the shared
`settings/defaults.json` stops every project), with the reason named. Same-name profiles
from unrelated repositories still need distinct names through `oh rename`.
An unverifiable legacy registration keeps its settings files in place until identity
is restored; a failed verification does not retire its settings. Files of registrations that were replaced, or of
deleted checkouts whose name another project now uses, are kept in `backups/` without being
applied.

Native agents are instructed not to hand-edit OH settings or evidence; their actual
filesystem permissions remain host-owned. Use `oh config set/unset` for validated changes.
`oh backup` includes `settings.json`.

| Setting | Default | Meaning |
|---|---|---|
| `tasks_per_batch` | 5 | Tasks approved per batch, and per **continue** (1–100) |
| `review_rounds` | 3 | Review rounds each task may use before OH asks you (1–100) |
| `context.handoff_chars` | 12000 | Maximum inline task context; complete scope and evidence are referenced externally |
| `context.result_chars` | 4000 | Maximum concise feedback retained in attempt summaries |
| `plans.location` | ask | Where roadmaps, design docs and decisions live: `repo` (committed in the repository) or `private` (OH's folder) |
| `plans.private_folder` | ~/oh-plans | Parent of visible private project plan folders; absolute or home-relative |
| `plans.roadmap` | docs/roadmap.md | Roadmap file, relative to where plans live |
| `plans.designs` | docs/design | Design docs folder |
| `plans.decisions` | docs/decisions | Decision records (ADRs) folder |

Worker context compaction follows the native host/model settings. OH no longer overrides it
with a fixed token threshold. Older `context.compact_at_tokens` settings are removed through
the existing migration with a backup.

`oh plans path` shows where a project's plans live; `oh plans check` checks the roadmap and
design docs against their rules. `oh plans list` shows each initiative's design and approval
status. New private plans live at `~/oh-plans/<project name>/`; the relative document paths
above apply inside that folder. Renaming a project preserves its existing document folder.
Folders remain reserved to their project after rename or checkout deletion, including case-only
aliases. OH refuses an existing unowned folder; preserve its contents and choose another project
name or `plans.private_folder`. Only explicit checkout replacement can transfer ownership, without
transferring approvals, including when a reserved folder has no documents yet. Settings changes
reserve the affected private folders before saving; a collision leaves the settings unchanged.
Private edits hold both the project lock and the canonical folder lock.
Private plans from older installations remain at their existing OH state path; `plans path`
is authoritative. `init --replace` preserves that document location but creates fresh checkout
authority. Profile export excludes private documents and approvals explicitly; copy those
documents separately when moving machines and review them again. `oh backup` covers OH state,
not the external `~/oh-plans` folder: include your visible plan folder in your regular backups.

`max_escalations` is retired. OH removes it from older settings through the existing
migration, preserving a backup. Checks are repaired automatically on the current profile;
only a blocking defect family appearing in a second independent review escalates the
implementer. No Retry approval is required for delivery.

## Models

OH labels each task **simple**, **standard** or **complex** before it starts, then picks
that profile's model and effort for the fresh native implementation agent. Reviews have
a separate profile. These settings do not change the coordinating chat's model.
The retained `insights` settings preserve compatibility, but new dashboard analysis
and the retired `oh suggest` entry are unavailable in this candidate.

| Profile | Claude | Codex |
|---|---|---|
| simple | haiku / high | gpt-6-luna / high |
| standard | sonnet / medium | gpt-6.1-sol / medium |
| complex | opus / high | gpt-6-astra / high |
| review | opus / high | gpt-6.1-sol / high |
| insights | opus / high | gpt-6-astra / high |

If Codex's CLI catalog omits the requested model, OH continues with the newest listed earlier
version in the same family that supports the requested effort. For example, `gpt-6.1-sol / high`
can use `gpt-6-sol / high`. OH gives a short notice with the update command and `$oh-config`,
and records the actual model before admitting the attempt; saved settings, scope and review
allowances stay unchanged. This works during an existing run. A changed CLI executable refreshes
capability discovery. `$oh-config` changes apply to new OH runs, including in the same chat.
No compatible earlier model, unsupported effort, discovery failure or a rejected native request
still fails visibly with a recovery step; OH never switches to another family or paid API calls.
OH does not change the model of the session you are talking to; select that in your
host app or CLI. Native execution and Stop support still require the validation described
in [usage](usage.md); configured model names alone do not establish host availability.

Older `models.<host>.orchestrator` settings migrate to `models.<host>.insights` with a backup,
preserving model and effort overrides. Old leaf names remain accepted by `config set/unset`,
and old exported profiles remain importable; `oh-config` and new exports show only `insights`.
If saved settings are read-only, OH interprets the old names in memory without rewriting them.
Existing runs retain their frozen settings. An older executable may require restoring the
settings backup after a downgrade; development and release settings remain separate.

Compatibility coverage: `test_renamed_settings_are_moved_once_with_a_backup`,
`test_a_read_only_settings_folder_never_stops_oh`,
`test_an_imported_profile_keeps_only_what_differs_from_your_settings` and
`test_editors_get_a_schema_for_the_running_version`.

## Checks

A project's `checks` list the commands that must pass before OH commits a task. Set them
with `oh config set checks '<JSON list>'`, which replaces the whole list:

```json
[
  {"name": "tests", "command": ["npm", "test"]},
  {"name": "lint", "command": ["./scripts/lint.sh"], "when": ["src/**"], "timeout_seconds": 300}
]
```

Commands run without a shell. `when` limits a check to changes matching those paths.
`inputs` and `toolchain` let OH reuse a passing result when nothing relevant changed; leave
them out if you're unsure. `modes` picks when a check runs (`review`, `pre-push`, `ci`).

A cancelled or timed-out check fails even if its cleanup exits with code `0`. OH skips
the remaining checks and cannot advance that attempt to review or commit. `oh verify`
returns failure, and task and PR summaries label the result failed while retaining the
actual exit code and cancellation reason.

Checks and toolchain probes retain complete stdout and stderr in OH's external
`verification/<project-id>/logs/` folder. Verification results, saved status and
subsequent agent packets expose `logs` references to capture records containing
the stream paths, byte counts and SHA-256 hashes. Inline output stays bounded;
read the referenced files when a noisy check hides its original error.
Logs remain available after failure, timeout or cancellation. A helper killed
before finalization leaves its initial record and captured bytes, with unknown
exit status and hashes rather than a claimed result. Logs are private local
diagnostics; do not copy them into public issues or PRs.


Before each new Deliver task, a fresh read-only assessment uses the configured `standard`
profile to examine the actual scope and relevant code. Its difficulty, rationale, references,
uncertainty and usage stay in OH's external records, and select the configured simple, standard
or complex implementation profile. Material uncertainty selects complex. The rating is reused
for repairs and resume; already-started older tasks retain their original selection. Consumer
design documents contain no model or effort recommendations.
