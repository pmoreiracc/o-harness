#!/usr/bin/env bash
# A deterministic fingerprint of the working tree.
#
# This is what binds a review to the thing that was reviewed. The reviewer runs, the
# start hook records the digest of the tree the reviewer sees, and complete.sh refuses to tick
# a box unless an authorized attempt covers the tree as it stands *now*. Edit anything after
# review and the digest moves, so that attempt no longer authorizes the transition.
#
# Covers the actual bytes, modes, links, deletions, and nested-repository commits of every
# tracked or untracked non-ignored path. Staging does not change that subject, so `git add`
# cannot invalidate an otherwise identical review. A Git index flag can hide a tracked
# working-tree edit from ordinary tooling; refuse that state.
set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$ROOT" || exit 1

check_index_flags() {
  local entries flagged
  entries=$(git ls-files -v 2>/dev/null) || {
    echo "tree-digest: cannot inspect Git index flags; refusing to trust the working tree." >&2
    return 1
  }
  # `git ls-files -v` renders assume-unchanged entries with a lower-case tag and
  # skip-worktree entries with `S`. Both detach `git diff HEAD` from bytes on disk.
  flagged=$(printf '%s\n' "$entries" | awk '/^[a-zS] / { print }') || {
    echo "tree-digest: cannot classify Git index flags; refusing to trust the working tree." >&2
    return 1
  }
  if [ -n "$flagged" ]; then
    echo "tree-digest: tracked files carry assume-unchanged or skip-worktree flags; refusing to trust the working tree:" >&2
    printf '%s\n' "$flagged" >&2
    echo "No fingerprint issued. If these flags are yours, clear only the listed flags with git update-index --no-assume-unchanged / --no-skip-worktree -- <path>, inspect the revealed diff, and retry. Otherwise ask their owner before changing them." >&2
    return 1
  fi
}

EXCLUDE_PATH=""
case "${1:-}" in
  "") ;;
  --check-index)
    [ "$#" = 1 ] || exit 1
    check_index_flags
    exit $?
    ;;
  --exclude-path)
    [ "$#" = 2 ] || exit 1
    EXCLUDE_PATH="$2"
    case "$EXCLUDE_PATH" in ""|/*|../*|*/../*|*/..|.deliver|.deliver/*|*$'\n'*) exit 1 ;; esac
    ;;
  *)
    echo "usage: tree-digest.sh [--check-index | --exclude-path RELATIVE_PATH]" >&2
    exit 1
    ;;
esac

check_index_flags || exit 1

# Git's untracked-file enumeration omits filesystem objects it cannot add (for
# example FIFOs and Unix sockets). Refuse any such non-ignored object before
# hashing, otherwise two different on-disk trees can collapse to one digest.
check_unsupported_untracked() {
  find . -name .git -type d -prune -o -path './.deliver' -prune -o \
    \( ! -type d ! -type f ! -type l \) -print0 \
    | while IFS= read -r -d '' f; do
        f=${f#./}
        [ -n "$EXCLUDE_PATH" ] && [ "$f" = "$EXCLUDE_PATH" ] && continue
        if git check-ignore -q -- "$f" 2>/dev/null; then
          continue
        fi
        echo "tree-digest: unsupported untracked filesystem object: $f" >&2
        echo "No fingerprint issued. Identify its owner; relocate your temporary runtime object to an already ignored scratch location or stop its producer, then retry. Preserve unknown objects and ask if necessary." >&2
        return 1
      done
}

check_unsupported_untracked || exit 1

if command -v shasum >/dev/null 2>&1; then HASH="shasum -a 256"
elif command -v sha256sum >/dev/null 2>&1; then HASH="sha256sum"
else
  echo "tree-digest: no shasum or sha256sum available" >&2
  exit 1
fi

list_tree_paths() {
  if [ -n "$EXCLUDE_PATH" ]; then
    git ls-files -z --cached --others --exclude-standard -- . ':(exclude).deliver/**' ":(exclude)$EXCLUDE_PATH" 2>/dev/null || return 1
  else
    git ls-files -z --cached --others --exclude-standard -- . ':(exclude).deliver/**' 2>/dev/null || return 1
  fi

  # Once a deletion is staged, its path is absent from both the index and the filesystem.
  # Add paths deleted relative to HEAD so staging cannot change the reviewed subject. An
  # unstaged deletion appears in both streams; the serialized record is de-duplicated below.
  if git rev-parse --verify HEAD >/dev/null 2>&1; then
    if [ -n "$EXCLUDE_PATH" ]; then
      git diff --no-ext-diff --no-renames --name-only -z --diff-filter=D HEAD -- . ':(exclude).deliver/**' ":(exclude)$EXCLUDE_PATH" 2>/dev/null || return 1
    else
      git diff --no-ext-diff --no-renames --name-only -z --diff-filter=D HEAD -- . ':(exclude).deliver/**' 2>/dev/null || return 1
    fi
  fi
}

{
  git rev-parse HEAD 2>/dev/null || echo "no-head"
  # .deliver/ is excluded unconditionally: the digest keys evidence stored there. Paths are
  # represented by hashes so newlines remain unambiguous, then sorted to make the inventory
  # independent of Git's cached/untracked grouping.
  list_tree_paths \
    | while IFS= read -r -d '' f; do
        if [ -d "$f" ] && [ -e "$f/.git" ]; then f=${f%/}; fi
        PATH_ID=$(printf '%s' "$f" | git hash-object --stdin) || exit 1
        if [ -L "$f" ]; then
          OBJECT_ID=$(perl -e 'defined($t=readlink $ARGV[0]) or exit 1; print $t' "$f" \
            | git hash-object --stdin) || exit 1
          printf '%s 120000 %s\n' "$PATH_ID" "$OBJECT_ID"
        elif [ -f "$f" ]; then
          OBJECT_ID=$(git hash-object --no-filters -- "$f") || exit 1
          if [ -x "$f" ]; then MODE=100755; else MODE=100644; fi
          printf '%s %s %s\n' "$PATH_ID" "$MODE" "$OBJECT_ID"
        elif [ -d "$f" ] && OBJECT_ID=$(git -C "$f" rev-parse --verify HEAD 2>/dev/null); then
          printf '%s 160000 %s\n' "$PATH_ID" "$OBJECT_ID"
        elif git ls-files --with-tree=HEAD --error-unmatch -- "$f" >/dev/null 2>&1; then
          printf '%s deleted -\n' "$PATH_ID"
        else
          echo "tree-digest: unsupported untracked filesystem object: $f" >&2
        echo "No fingerprint issued. Identify its owner; relocate your temporary runtime object to an already ignored scratch location or stop its producer, then retry. Preserve unknown objects and ask if necessary." >&2
          exit 1
        fi
      done | LC_ALL=C sort -u
} | $HASH | cut -c1-16
