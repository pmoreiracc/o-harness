# Changelog

## v1.0.0

OH's first stable release brings Propose, Design and Deliver together in Claude Code and Codex. OH uses your existing host subscription and keeps project settings and saved workflow evidence outside your repository.

### Workflows

- **Propose and Design.** Shape an idea into ordered tasks and acceptance checks. Inspect the proposed work alongside the approval choices. Resume unfinished work or explicitly start fresh when that choice is available.
- **Deliver.** Ask in plain language to deliver an approved design or continue saved work. OH can select eligible tasks across tracks and implements them one at a time. Each task runs the configured checks and receives a fresh independent review. Unresolved blockers pause delivery.
- **Recovery and publication.** Continue from a saved checkpoint with the original scope and remaining allowances. Review what was completed before deciding whether to stop, continue, or open a PR. OH follows the published head's GitHub checks and reports the result.
- **Installation.** The release workflow packages both plugins and checks that they install and start on Linux, macOS and Windows. Windows native workflows remain in preview.

### Fixes since v0.9.5

- First-run setup identifies blocked write paths and explains how to retry from a host sandbox. [#218](https://github.com/pmoreiracc/o-harness/issues/218)
- Shell environment discovery runs without terminal input and stops the probe when its deadline expires. [#219](https://github.com/pmoreiracc/o-harness/issues/219)
- An update blocked by host executable ownership gives a native-permission retry while preserving ownership checks. [#220](https://github.com/pmoreiracc/o-harness/issues/220)
- The first-run plans question shows both exact paths and carries forward the original Propose or Design request, including after a corrected question. [#221](https://github.com/pmoreiracc/o-harness/issues/221)
- Recommendation-only proposals can finish directly. For roadmap additions, OH prepares a single chat message with the complete preview, destination and choices, then binds the reply to that preview. [#222](https://github.com/pmoreiracc/o-harness/issues/222)

### Updating from v0.9.5

Finish or cancel active native work. Run `/oh-update` in Claude Code or `$oh-update` in Codex, then start a fresh host session. Your saved workflows, project settings and used allowances carry forward. In Codex, use `/hooks` to review any changed OH hooks. See the [installation and update guide](docs/installation.md#update) for upgrade and rollback details.

See [Known limits](docs/known-limits.md) for current host and workflow boundaries. The [v0.9.5 release history](https://github.com/pmoreiracc/o-harness/releases/tag/v0.9.5) lists the changes in the stable baseline.
