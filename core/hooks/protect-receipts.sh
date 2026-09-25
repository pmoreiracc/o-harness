#!/usr/bin/env bash
# GUARDRAIL — the model may not write its own harness evidence.
#
# Accepted rounds and human grants use supported host-hook writers. Review requests are
# non-authoritative implementer claims, but still go through review-ready.sh so task/tree
# binding and their structural contract cannot be skipped by an ordinary Edit/Write.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/lib.sh" || {
  echo "GUARDRAIL CANNOT RUN: core/hooks/lib.sh is missing or unreadable." >&2
  echo "No operation was inspected. Restore this reviewed harness file in the checkout and retry; do not disable the guardrail." >&2
  exit 2
}
hook_init

FILE=$(hook_field '.tool_input.file_path')
[ -n "$FILE" ] || exit 0

if [ -n "${OH_STATE_ROOT:-}" ]; then
  case "$FILE" in "$OH_STATE_ROOT"|"$OH_STATE_ROOT"/*)
    echo "BLOCKED: OH evidence is written only by host workflow entry points." >&2
    exit 2 ;;
  esac
fi
REL=$(repo_rel "$FILE")
case "$REL" in
  .deliver/*) ;;
  *) exit 0 ;;
esac

echo "BLOCKED — .deliver/ is written through harness entry points, never by hand." >&2
echo "" >&2
echo "  $REL" >&2
echo "" >&2
case "$REL" in
  .deliver/review-requests/*)
    echo "Stage implementer claims with core/scripts/review-ready.sh; they are not receipts." >&2
    ;;
  *)
    echo "Accepted rounds and human grants are local workflow evidence written through" >&2
    echo "supported host hooks. This guard blocks direct Edit/Write; arbitrary Bash is outside" >&2
    echo "ADR-0047's provenance boundary." >&2
    echo "If reviewer output is pending, use review-retain.sh with the exact response. Use round-status.sh/task-status.sh and the supported host choice adapter for grants; never fabricate evidence. Correct the operation and continue." >&2
    ;;
esac
exit 2
