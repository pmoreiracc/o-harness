#!/usr/bin/env bash
# Read-only presenter for exact Codex human-gate commands.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
. "${OH_HOME:-$ROOT}/core/round-ledger.sh" || exit 2

case "$#:${1:-}" in
  1:task|1:review-window) codex_gate_present "$1" - ;;
  2:review|2:scope-destination|2:detached) codex_gate_present "$1" "$2" ;;
  *) echo "usage: codex-gate.sh task|review-window|review OUTCOME|scope-destination URL|detached ID" >&2; exit 2 ;;
esac
