# Use OH

## Local setup

This release targets a single developer's local machine. You need Python 3.11+, Git,
Bash, jq, Node 22, and a subscription-authenticated Codex CLI or Claude Code CLI.
The macOS service runs independently of your product's application or Docker stack.
Other operating systems can run the foreground server; their service setup is not automated.

A consumer keeps `.oh/project.json`, `.oh/checks.json`, a full revision in
`.oh/harness.lock.json`, and the small `.oh/oh` and `.oh/setup.py` bootstraps.
`setup.py` installs the committed pin into `~/.local/share/o-harness/versions/REVISION`.
Run `python3 -I .oh/setup.py` from an integrated project. The GitHub repository must be
accessible with your existing Git credentials. Never put a token in the lock file.

The first integration copies the templates from `integrations/project/`, registers a
stable project ID with `oh init --name NAME`, supplies the project's required checks,
and commits the pin before normal execution. Public self-service onboarding remains
[issue 2](https://github.com/pmoreiracc/o-harness/issues/2).

Trust the installed native host binary once with `.oh/oh trust-host codex ABSOLUTE_PATH`
or `.oh/oh trust-host claude ABSOLUTE_PATH`. OH records its path and SHA-256; PATH lookup,
project-local wrappers and temporary binaries cannot silently choose the executable.
A damaged pinned installation is never reported as installed: setup names the directory
to preserve separately, after which rerunning setup reinstalls the committed revision.
A host update requires trusting its new installed binary. Sign in through the host's
subscription login; API credentials are not used by OH child execution.

Run `.oh/oh configure-hosts` to generate thin host discovery. Existing conflicting files
are preserved and reported. Previously generated files may be updated or retired only
while their bytes still match the ownership record. Do not hand-edit generated files;
keep product policies in `.oh/policy/` and settings in `.oh/config.json`.

For OH development itself, use `./oh` and `./oh configure-hosts --development`.

## One conversation, several tasks

The coordinator prepares `.oh/runtime/tasks.json` from the work you agreed to:

```json
{
  "tasks": [
    {"id": "1", "title": "Fix empty-state copy", "instructions": "Use the approved wording in the empty state.", "paths": ["web/empty-state.tsx"]}
  ]
}
```

The agent runs `.oh/oh prepare .oh/runtime/tasks.json` and shows you the exact returned
trigger, such as `$oh request:HASH` in Codex or `/oh request:HASH` in Claude.
Preparation seals the task list, required checks, effective settings, checkout and base.
It does not start a model or grant work. Your subsequent native human turn authorizes
that request. Editing a manifest or local settings afterwards cannot widen it.
A changed base needs preparation again. Do not type the placeholder `HASH` literally.

After that trigger the agent runs `.oh/oh run`. The deterministic runner owns the loop;
you do not select a model or open a separate conversation for each task. Dependencies
must refer to earlier tasks. Each task gets its own worker and fresh independent reviewer.
The coordinator keeps summaries short and waits for completion events.

At a non-final batch boundary, **continue** grants the next configured number, **PR** publishes
completed work for your review, and **stop** retains the current state. No automatic merge. The agent includes `.oh/oh pr-summary` output in the PR body;
CI can check commit/body consistency with `.oh/oh pr-summary --validate-event EVENT_JSON BASE_REF`.
The command supports native commit evidence and the optional legacy design profile.
Local export requires the retained journal and your recorded PR choice. The portable
summary is not a signed identity attestation; CI does not independently authenticate
the reviewer or replace human merge review.
After the final task, show exactly **PR** or **stop**; do not automatically publish.
At a spent review window, **grant review** grants another configured review window or
**stop** ends execution. Blocking findings require a fix and a new review. Nonblocking
findings may be accepted or routed only through their displayed human choices.

An interrupted process resumes with the same `.oh/oh run`; no allowance is replenished.
A deliberately stopped native run needs **resume**. A failure checkpoint offers **retry**
for one bounded recovery window. Read `.oh/oh status` for the retained state and evidence.
Do not delete receipts or edit a journal to bypass a refusal.

## Optional product design workflow

Generic projects receive only the neutral OH skill. A product can explicitly select
`"design_profile": "consumer-v1"` in `.oh/project.json` and own its design, proposal and
delivery policies in `.oh/policy/{design,propose,deliver}.md`. The current design adapter
supports the extracted numbered Markdown task grammar. It is optional, not a requirement
for new OH consumers. Geoffrey owns its ADR and product rules; OH does not impose them.

Before a new design run, the agent uses `.oh/oh prepare-design DOC [TRACK]` and presents
the returned request trigger. `.oh/oh deliver DOC [TRACK]` then starts or resumes the
retained run. Exact initial task IDs and settings stay fixed through recovery.

## Dashboard service

Run `.oh/oh service-install` once on macOS. It installs a LaunchAgent that starts at login
and restarts the server if it exits. Open http://localhost:4318 whenever you want; no report
script is needed. `./oh serve` runs the server in the foreground for development.
`.oh/oh service-uninstall` stops the service and removes its registration, preserving data.

The service runs a specific installed OH revision. After upgrading a product pin, reinstall
the service from the desired installed revision. Its logs live in the OH data directory.

Task grants require Git with `reflog write` support; Git 2.55 is verified. OH records a
unique branch marker so deleting and recreating a branch cannot reuse an old grant,
even when the filesystem reuses an inode within the same second. Removing or expiring
that marker invalidates the grant; preserve the evidence and prepare a new run.
