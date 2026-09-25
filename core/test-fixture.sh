#!/usr/bin/env bash
# Test-only fixture hygiene (ADR-0052). Never copy the developer's ignored policy/state.
# Sourced before a suite resolves Git state, including when run directly from a worktree.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
  GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_COMMON_DIR GIT_NAMESPACE GIT_PREFIX

copy_harness() ( # copy_harness <source repo> <destination> <repo-relative directories...>
  set -o pipefail
  local source="$1" destination="$2"
  shift 2
  [ "$#" -gt 0 ] || return 1
  mkdir -p "$destination" || return 1
  # Read working bytes, including new implementation files, but never ignored local files.
  # pipefail is essential: a failed inventory may not produce a successful empty fixture.
  (
    set -o pipefail
    cd "$source" || exit 1
    git ls-files -z --cached --others --exclude-standard -- "$@" | while IFS= read -r -d '' path; do
      if [ -e "$path" ] || [ -L "$path" ]; then printf '%s\0' "$path"; fi
    done | tar -c --null -T - -f -
  ) | tar -x -f - -C "$destination"
)
