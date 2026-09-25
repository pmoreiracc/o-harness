#!/usr/bin/env bash
# Session adapters share one literal-only parser for direct host evidence.
desktop_choice_candidate() {
  local root="$1" family="$2" adapter="$3"
  command -v node >/dev/null 2>&1 || { echo 'Desktop choice: Node is required; install the harness prerequisite and retry.' >&2; return 1; }
  node "${OH_HOME:-$root}/adapters/codex/desktop-choice.mjs" "$root" "$family" "$adapter"
}
desktop_task_choice_candidate() {
  desktop_choice_candidate "$1" task adapters/codex/task-grant-from-session.sh
}
