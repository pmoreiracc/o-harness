#!/usr/bin/env bash
# SessionStart — make the committed git hooks the active ones.
#
# `.git/hooks` is not versioned, so a hook that lives there exists on exactly one machine
# and arrives on no clone. Pointing core.hooksPath at a committed directory fixes that,
# but only once someone runs the command — and "run this after cloning" is a README line
# people skip. Setting it at session start means the repo configures itself.
#
# Repo-local: writes to .git/config, touches nothing outside this checkout.
set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 || exit 0
if [ -n "${OH_HOME:-}" ]; then
  [ -d "$ROOT/.oh/git-hooks" ] || exit 0
  git -C "$ROOT" config extensions.worktreeConfig true || exit $?
  git -C "$ROOT" config --worktree core.hooksPath .oh/git-hooks
  exit $?
fi
[ -d "$ROOT/.githooks" ] || exit 0

CURRENT=$(git -C "$ROOT" config --get core.hooksPath 2>/dev/null || true)
[ "$CURRENT" = ".githooks" ] && exit 0

if git -C "$ROOT" config core.hooksPath .githooks 2>/dev/null; then
  echo "core.hooksPath set to .githooks — the committed pre-push and commit-msg hooks are now active."
fi

exit 0
