#!/usr/bin/env bash
# Route required SCOPE, or resume publication of an already saved human disposition.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
. "${OH_HOME:-$ROOT}/core/review-receipt.sh" || exit 2
. "${OH_HOME:-$ROOT}/core/round-ledger.sh" || exit 2

[ "$#" -eq 0 ] || { echo "usage: review-route-scope.sh" >&2; exit 2; }
TREE=$(CLAUDE_PROJECT_DIR="$ROOT" "$DIR/tree-digest.sh") || exit 2
BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 2
KEY=$(round_key_for "$ROOT" "$BRANCH" 2>/dev/null) || exit 2
ATTEMPT=$(review_attempt_latest_for_tree "$ROOT" "$KEY" "$TREE" 2>/dev/null) || {
  echo "review-route-scope: no retained attempt covers the current tree." >&2
  exit 2
}
OUTCOME=$(jq -r '.outcome' "$ATTEMPT/completion.json" 2>/dev/null) || exit 2
case "$OUTCOME" in
  blocking+scope|blocking+concern+scope) ;;
  *)
    CHOICE=$(jq -r '.choice // ""' "$ATTEMPT/resolution.json" 2>/dev/null) || CHOICE=""
    case "$CHOICE" in
      accept-concerns)
        SOURCE=$(jq -er '.source | select(type=="string" and length>0)' "$ATTEMPT/resolution.json") || exit 2
        review_resolution_record "$ROOT" "$ATTEMPT" "$CHOICE" "$SOURCE" "$TREE" || {
          echo 'review-route-scope: saved concern acceptance could not be published; preserve it, repair the named filesystem/evidence failure and retry.' >&2; exit 2;
        }
        echo 'review-route-scope: published the already saved concern acceptance; no new human decision required.'
        exit 0 ;;
      take-over)
        SOURCE=$(jq -er '.source | select(type=="string" and length>0)' "$ATTEMPT/resolution.json") || exit 2
        review_resolution_record "$ROOT" "$ATTEMPT" "$CHOICE" "$SOURCE" "$TREE" || exit 2
        SERIES=$(jq -er .seriesId "$ATTEMPT/start.json") || exit 2
        review_series_close "$ROOT" "$SERIES" take-over || exit 2
        echo 'review-route-scope: completed the saved takeover; no completion authorized.'
        exit 0 ;;
      *route-scope*) ;;
      *dismiss-scope*)
        review_scope_apply "$ROOT" "$ATTEMPT" dismiss-scope && exit 0
        echo 'review-route-scope: saved dismissal could not be applied; inspect the cause and retry, preserving its record.' >&2; exit 2 ;;
      *) echo "review-route-scope: $OUTCOME needs a human scope disposition first; nothing routed." >&2; review_completion_diagnose "$ROOT"; exit 2 ;;
    esac ;;

esac
if review_scope_apply "$ROOT" "$ATTEMPT" route-scope; then
  echo "review-route-scope: routed retained scope findings; follow the saved disposition. Only blocker/concern fixes require a fresh review."
else
  STATUS=$(jq -r '.status' "$ATTEMPT/scope-transition.json" 2>/dev/null || echo failed)
  echo "review-route-scope: durable routing requires human completion ($STATUS)." >&2
  if [ "$STATUS" = human-route-required ]; then
    echo "After the human authorizes a repository issue and it exists, confirm its exact URL through the host review-choice gate." >&2
  fi
  exit 3
fi
