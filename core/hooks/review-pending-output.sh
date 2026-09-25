#!/usr/bin/env bash
# Refuse ordinary Codex edits while an admitted reviewer result is awaiting retention.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/lib.sh" || exit 2
hook_init
[ -n "${CODEX_HOOK:-}" ] || exit 0
. "$DIR/../review-workflow.sh" || exit 2

ROOT=$(project_root)
BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 2
SERIES=$(review_series_current "$ROOT" "$BRANCH" 2>/dev/null) || exit 0
ATTEMPT=$(review_attempt_pending_for "$ROOT" "$SERIES" codex 2>/dev/null)
case $? in
  0)
    echo "REFUSED — the admitted Codex review output has not been retained." >&2
    echo "Run core/scripts/review-retain.sh with the exact reviewer response on stdin, then retry the edit." >&2
    echo "Wait if the reviewer is live. For confirmed non-cancelled zero-output completion use review-retain.sh --no-result; for uncertain/cancelled termination use --interrupted and its human gate." >&2
    exit 2
    ;;
  1) exit 0 ;;
  *) echo "GUARDRAIL CANNOT RUN: pending Codex review state is ambiguous." >&2; exit 2 ;;
esac
