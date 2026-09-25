#!/usr/bin/env bash
# Render locally retained PR-only review resolutions, or validate their durable PR copy in CI.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
. "${OH_HOME:-$ROOT}/core/review-workflow.sh" || exit 1

case "${1:-}" in
  "")
    BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 1
    case "$BRANCH" in
      deliver/*) review_pr_resolutions_render "$ROOT" "$BRANCH" ;;
      *)
        review_non_delivery_handoff_seal "$ROOT" "$BRANCH" && exit 0
        echo "review-pr-summary: no valid handoff for HEAD. Check git status and HEAD trailers against review-finish.sh preparation; repair missing trailers for identical content, or review changed content and prepare/commit it again. Do not publish a stale summary." >&2
        exit 1
        ;;
    esac
    ;;
  --validate-event)
    EVENT="${2:-}"; BASE="${3:-}"
    [ "$#" = 3 ] && [ -f "$EVENT" ] && [ ! -L "$EVENT" ] && [ -n "$BASE" ] || exit 1
    git -C "$ROOT" rev-parse --verify "$BASE^{commit}" >/dev/null 2>&1 || exit 1
    BODY=$(mktemp) || exit 1
    trap 'rm -f "$BODY"' EXIT
    jq -r '.pull_request.body // ""' "$EVENT" > "$BODY" || exit 1
    BRANCH=$(jq -er '.pull_request.head.ref | select(type=="string" and length>0)' "$EVENT") || exit 1
    HEAD_SHA=$(jq -er '.pull_request.head.sha | select(type=="string" and test("^[0-9a-f]{40}([0-9a-f]{24})?$"))' "$EVENT") || exit 1
    [ "$HEAD_SHA" = "$(git -C "$ROOT" rev-parse HEAD 2>/dev/null)" ] || exit 1
    IDS=$(git -C "$ROOT" log --format=%B "$BASE..HEAD" 2>/dev/null \
      | sed -n 's/^Review-Resolution: \([0-9a-f]\{64\}\)$/\1/p' | awk '!seen[$0]++') || exit 1
    case "$BRANCH" in
      deliver/*)
        if [ -n "$IDS" ]; then
          # Deliberately expand the newline-separated IDs here: each remains one hexadecimal word.
          review_pr_resolution_ids_match "$BODY" $IDS
        else
          review_pr_resolution_ids_match "$BODY"
        fi
        ;;
      *)
        [ "$(grep -c '^Review-Handoff: ' "$BODY" 2>/dev/null)" = 1 ] || exit 1
        review_pr_handoff_validate "$BODY" "$BRANCH" "" "$HEAD_SHA" || exit 1
        [ "$(sed -n 's/^Review-Parent: //p' "$BODY")" = "$(git -C "$ROOT" rev-parse HEAD^ 2>/dev/null)" ] || exit 1
        [ "$(sed -n 's/^Review-Git-Tree: //p' "$BODY")" = "$(git -C "$ROOT" rev-parse HEAD^{tree} 2>/dev/null)" ] || exit 1
        PREPARATION=$(sed -n 's/^Review-Preparation: //p' "$BODY") || exit 1
        [ "$(git -C "$ROOT" show -s --format=%B HEAD 2>/dev/null | grep -cFx "Review-Preparation: $PREPARATION")" = 1 ] || exit 1
        if [ -n "$IDS" ]; then review_pr_resolution_ids_match "$BODY" $IDS
        else review_pr_resolution_ids_match "$BODY"
        fi
        ;;
    esac
    ;;
  *)
    echo "usage: review-pr-summary.sh [--validate-event EVENT_JSON BASE_REF]" >&2
    exit 1
    ;;
esac
