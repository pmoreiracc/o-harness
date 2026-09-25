#!/usr/bin/env bash
# Human-owned local window policy cannot be changed through model editing tools (ADR-0051).
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/lib.sh" || exit 2
hook_init

TOOL=$(hook_field '.tool_name')
case "$TOOL" in Edit|Write) ;; *) exit 0 ;; esac
ROOT=$(project_root)
TARGET=$(hook_field '.tool_input.file_path')
[ -n "$TARGET" ] || TARGET=$(hook_field '.tool_input.path')
case "$TARGET" in /*) ;; *) TARGET="$ROOT/$TARGET" ;; esac
PARENT=$(cd "$(dirname "$TARGET")" 2>/dev/null && pwd -P) || exit 0
TARGET="$PARENT/$(basename "$TARGET")"
ROOT=$(cd "$ROOT" && pwd -P) || exit 2
case "$TARGET" in
  "${OH_HOME:-$ROOT}/core/delivery-policy.local.json")
    echo "BLOCKED: core/delivery-policy.local.json is human-owned checkout policy." >&2
    echo "No write applied. Continue under the current snapshot. If changing future defaults is needed, offer keeping them or having the human edit and save this file directly; existing grants retain their snapshots." >&2
    exit 2 ;;
esac
exit 0
