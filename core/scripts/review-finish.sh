#!/usr/bin/env bash
# Prepare an authorized staged non-delivery tree and print its required commit trailers.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"

[ "$#" = 0 ] || {
  echo "usage: review-finish.sh" >&2
  exit 1
}
. "${OH_HOME:-$ROOT}/core/review-receipt.sh" || exit 1

review_non_delivery_finish "$ROOT" || {
  echo "review-finish.sh: commit preparation refused. Inspect git status; stage only the authorized final tree, then retry. No commit created." >&2
  review_completion_diagnose "$ROOT"
  exit 5
}
