# Contributing

## Issues

- **Bug:** include the OH version (`version` in `~/.local/share/o-harness/runtime/active.json`),
  your host and OS, steps to reproduce, and what you expected. Never post credentials,
  transcripts or your OH data folder.
- **Feature:** open an issue to agree on the problem and scope before building it. Small
  fixes can go straight to a PR.
- **Security:** see [SECURITY.md](SECURITY.md). Don't open a public issue.

## Development

You need Python 3.12+, Git, Node.js and Bash. Tests need no AI subscription or API key.

```sh
bash integrations/test.sh native   # behavior tests
bash integrations/test.sh syntax   # Python, JavaScript and shell syntax
```

1. Fork the repository and branch from `main`.
2. Read `config/invariants.json` and the code you are changing. Make the smallest complete
   change.
3. Add tests for the behavior or regression you fix. Tests use temporary repositories and
   fake model responses; never use a real project as a fixture.
4. For dashboard changes, check it in a browser at desktop and narrow widths.
5. Open a PR against `main` that explains the problem, the new behavior, how you checked it
   and any limits. Keep docs in sync with what the code actually does.

Maintainers run an independent review of every PR before merging. Only maintainers merge.
Merging to `main` releases nothing unless the merge changes the version; see
[releasing](docs/installation.md#releasing-maintainers).

To try your change as a real plugin, see the local build steps in the same section. Your
installed OH doesn't change when you edit this checkout.
