#!/usr/bin/env bash
# GUARDRAIL — run Claude's reviewer admission chain in a deterministic order.
# Claude runs sibling matching hook commands in parallel, so readiness, the round brake,
# and admission must be one handler rather than three independently matching handlers.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/lib.sh" || exit 2
hook_init

printf '%s' "$PAYLOAD" | "$DIR/review-ready-gate.sh" || exit 2
printf '%s' "$PAYLOAD" | "$DIR/round-refuse.sh" || exit 2
printf '%s' "$PAYLOAD" | "$DIR/review-admit.sh"
