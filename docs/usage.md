# Using OH

Install the **o-harness** plugin at user scope in Codex or Claude Code. Installation makes
its explicit skills available; opening a project or asking an ordinary coding question
never activates OH. Both hosts use one local core and data store. No product repository
files, Git hooks, API keys or separately billed API calls are needed.

## First setup

This is an early local plugin distribution. Build each host package from a reviewed clean
OH checkout with `./oh build-plugin <new-directory>/o-harness --host codex` (or `claude`).
Install the package through that host's native user plugin manager. A polished public
installer is tracked in [issue 2](https://github.com/pmoreiracc/o-harness/issues/2).

Run the installed plugin's `scripts/oh setup` explicitly. It verifies the bundled core,
installs an immutable version and creates `~/.local/share/o-harness/bin/oh`. Add that
single directory to your PATH if you want the short `oh` command. Development packages
require `setup --development`; do not distribute them as reviewed releases.

Authorize the installed native binary with `oh trust-host codex <absolute-binary-path>`
or `oh trust-host claude <absolute-binary-path>`. OH validates the binary and requires
subscription login. A changed binary needs renewed trust. It never copies credentials.
Plugin prompt hooks require the host's normal trust approval; installation alone does
not authorize hook execution. Codex Desktop also supports a bounded native-turn fallback.

For each checkout, `oh --root <checkout> init --name <name>` registers an external profile.
`oh config` reports its directory. The agent can inspect existing scripts and configure
ordinary product checks there. Registration does not grant implementation work. Existing
project instructions and business policies remain authoritative.

## Workflows

Explicitly invoke **propose**, **design** or **deliver**. Hosts may display namespaced
commands, for example `$o-harness:deliver` or `/o-harness:deliver`. **oh-start** is an
optional general entry, not a required on-switch. Propose and design are read-only,
independently reviewed artifacts saved outside the product. They do not authorize coding.

For delivery, the coordinator prepares the agreed task list externally and presents its
exact request trigger. Submit it once to authorize that scope. Prepared scope cannot be
expanded after your response. The runner selects difficulty profiles, starts fresh workers
and reviewers, runs checks, records findings and commits the reviewed final tree. Do not
run another agent loop in the parent conversation.

At a batch boundary choose **continue / PR / stop**; at completion choose **PR / stop**.
Initial and continued batches use the same configured count. PR preparation retains the
review evidence and remains subject to human merge. Normal coding, commits and PRs outside
OH remain available at any time; they are not counted as OH performance.

## Pause, resume and stop

- **oh-pause** drains the current worker or check, then prevents another step or commit.
  PAUSING means work is still draining; PAUSED means it is quiet.
- **oh-resume** validates the same checkout and retained work, then continues with remaining
  allowances. A paused batch checkpoint stays a checkpoint until you choose continue.
- **oh-stop** interrupts owned processes, force-kills after a grace period if necessary,
  and ends the run. It keeps files, commits, partial work and receipts. STOPPING is not STOPPED.
  Stopped runs cannot resume; further work needs newly authorized scope.

If a busy host cannot dispatch a skill, run `oh --root <checkout> pause` or `stop` directly
in a terminal. Resume requires the owning conversation's explicit human event; the CLI
verifies that event. `oh status` reports the actual run and evidence. Neither elapsed time
nor natural-language model prose renews task or review allowances.

Manual edits while paused are preserved and may invalidate the retained review. Reconcile
and re-review changed work instead of deleting evidence. Branch recreation or reflog
replacement invalidates the old binding. OH reads filesystem birth identity and Git's
existing reflog; it writes no OH marker into `.git`. Unsupported filesystems fail visibly.

## Projects and upgrades

Sibling worktrees can attach to one project with `init --attach <project-id>`; each has
separate checkout authority. Clones receive separate identities. A moved checkout needs
`init --reattach <checkout-id>`. A replaced checkout at an old path needs `init --replace`;
its old identity is archived and its grants are never reused. These actions grant no tasks.

Use `oh profile-export <new-file-outside-product>` to share effective configuration and
check definitions. `oh --root <new-checkout> profile-import <file>` creates fresh identities
and grants no work. Exports exclude host trust, sessions, evidence, and credentials.
Portable checks require existing tracked ordinary scripts in the exporting/importing checkout;
missing files and symlinks are refused. Direct invocation requires executable permissions
and an explicit relative path such as `./checks.sh`, so it never searches PATH for the script.
Scripts can run directly or through bash, sh, python3,
or node, with `{base}`, `{mode}`, or standard OH check-mode arguments. Toolchain probes
support known tools with `--version`. Arbitrary arguments, flags, environment assignments,
and inline programs are refused on both export and import. Wrap complex commands in a
repository script that reads credentials locally. This restriction applies only to sharing
profiles; local verification commands remain unrestricted. Modes, input paths, affected-path
patterns and timeouts are preserved. Whole-state backup is separate.

The optional external `design_profile: consumer-v1` supports approved numbered product
Markdown designs through `prepare-design <number> [track]`. It uses the same runner and
reviews the final rendered lifecycle tree. Generic OH imposes no ADR process.

Install an updated host plugin, then run its explicit setup. Active runs retain their old
core; do not remove installed versions while those runs exist. Removing either host plugin
through its native manager leaves the shared core, other host, dashboard and evidence intact.

## Dashboard

Run `oh service-install` once on macOS, then open [localhost:4318](http://localhost:4318).
The service starts at login and restarts after exits. Reinstall the service after selecting
a reviewed core upgrade. `oh serve` runs it in the foreground on other platforms; automatic
service installation currently supports macOS. `oh service-uninstall` preserves all data.
Opening the dashboard makes no model call. Improvement suggestions are saved and on-demand.
See [analytics](analytics.md) for coverage, comparisons, backup and privacy.
