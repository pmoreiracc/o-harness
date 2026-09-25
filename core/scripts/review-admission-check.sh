#!/usr/bin/env bash
# Read-only validation of the immutable attempt-start record (ADR-0051).
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
admission_refused() {
  echo "review-admission: no review authorized: $1" >&2
  echo "Correct the named prerequisite; parent must retain this refusal and admit a fresh reviewer within the same series/window. Restart the host only if its runner cannot reload." >&2
  exit 2
}
. "$DIR/../review-workflow.sh" || admission_refused "cannot load $DIR/../review-workflow.sh; restore the reviewed harness file and retry"
. "$DIR/../round-ledger.sh" || admission_refused "cannot load $DIR/../round-ledger.sh; restore the reviewed harness file and retry"
[ "$#" -le 1 ] || admission_refused "unexpected arguments; pass only the exact HARNESS REVIEW ADMISSION path"
REL="${1:-}"
if [ -z "$REL" ]; then
  BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD) || admission_refused "cannot resolve the current branch in $ROOT; repair Git/worktree access and retry"
  if [ "$BRANCH" = HEAD ]; then
    ATTEMPT=""
    for CANDIDATE_SERIES in "$(review_series_state_root "$ROOT")/series"/s-*; do
      [ -f "$CANDIDATE_SERIES/series.json" ] && [ ! -e "$CANDIDATE_SERIES/closed.json" ] || continue
      CANDIDATE_BRANCH=$(jq -er '.branch | select(type=="string")' "$CANDIDATE_SERIES/series.json") || admission_refused "corrupt series metadata: $CANDIDATE_SERIES/series.json; preserve evidence and diagnose its bound context"
      [ "$CANDIDATE_BRANCH" = HEAD ] || continue
      CANDIDATE=$(review_attempt_pending_for "$ROOT" "${CANDIDATE_SERIES##*/}" claude)
      case $? in
        0) ;;
        1) continue ;;
        *) admission_refused "detached pending-attempt lookup failed in $CANDIDATE_SERIES; diagnose the record/ownership failure above before retrying" ;;
      esac
      [ -z "$ATTEMPT" ] || admission_refused "ambiguous detached Claude attempts: $ATTEMPT and $CANDIDATE; preserve both and use the host's explicit detached-context choice"
      ATTEMPT="$CANDIDATE"
    done
    [ -n "$ATTEMPT" ] || admission_refused "no active detached Claude attempt; select or resume the intended detached context through the host and admit its reviewer"
  else
    SERIES=$(review_series_current "$ROOT" "$BRANCH") || admission_refused "no valid open review series for $BRANCH; inspect round-status.sh and any context error above, then admit a fresh reviewer in the intended context"
    ATTEMPT=$(review_attempt_pending_for "$ROOT" "$SERIES" claude)
    case $? in
      0) ;;
      1) admission_refused "no active Claude attempt in $SERIES; pass the host's exact admission path for Codex, or admit a fresh Claude reviewer" ;;
      *) admission_refused "pending-attempt lookup failed in $SERIES; preserve evidence and resolve the corrupt or ambiguous ownership reported above" ;;
    esac
  fi
else
  case "$REL" in
    .deliver/reviews/series/s-*/attempts/*/start.json) ATTEMPT="${ROOT}/${REL%/start.json}" ;;
    "${OH_STATE_ROOT:-/__oh_unset__}"/series/s-*/attempts/*/start.json) ATTEMPT="${REL%/start.json}" ;;
    *) admission_refused "invalid admission path: $REL; pass the exact HARNESS REVIEW ADMISSION path" ;;
  esac
fi
review_attempt_validate_start "$ROOT" "$ATTEMPT" || admission_refused "start record or its bound snapshot/request is missing or invalid: $ATTEMPT/start.json; preserve evidence and diagnose the record"
CURRENT_TREE=$(CLAUDE_PROJECT_DIR="$ROOT" "${OH_HOME:-$ROOT}/core/scripts/tree-digest.sh") || admission_refused "cannot compute the current fingerprint; repair the tree-digest.sh failure above and rerun it before review admission"
CURRENT_BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD) || admission_refused "cannot resolve the current branch in $ROOT; repair Git/worktree access and retry"
if [ "$CURRENT_BRANCH" = HEAD ]; then
  SERIES_ID=$(jq -er '.seriesId | select(type=="string" and length>0)' "$ATTEMPT/start.json") || admission_refused "missing seriesId in $ATTEMPT/start.json; preserve and diagnose the start binding"
  REVIEW_DETACHED_CONTEXT_ID=$(jq -er '.detachedContextId | select(type=="string" and length>0)' \
    "$(review_series_dir "$ROOT" "$SERIES_ID")/series.json") || admission_refused "missing detached-context binding in series $SERIES_ID; preserve its evidence and use the host's explicit context-resume choice"
  export REVIEW_DETACHED_CONTEXT_ID
  review_detached_context_validate "$ROOT" "$REVIEW_DETACHED_CONTEXT_ID" || admission_refused "invalid detached context $REVIEW_DETACHED_CONTEXT_ID; preserve the record and inspect its repository/status binding before choosing a valid context through the host"
fi
CURRENT_KEY=$(round_key_for "$ROOT" "$CURRENT_BRANCH") || admission_refused "cannot resolve the current round key on $CURRENT_BRANCH; run round-status.sh and repair the task/context evidence reported above"
[ "$(jq -r '.tree' "$ATTEMPT/start.json")" = "$CURRENT_TREE" ] || admission_refused "tree changed since admission; retain the old attempt and stage current readiness before a fresh review"
[ "$(jq -r '.branch' "$ATTEMPT/start.json")" = "$CURRENT_BRANCH" ] || admission_refused "branch changed since admission; retain the old attempt and stage current readiness before a fresh review"
[ "$(jq -r '.roundKey' "$ATTEMPT/start.json")" = "$CURRENT_KEY" ] || admission_refused "roundKey changed since admission; retain the old attempt and stage current readiness before a fresh review"
if [ -e "$ATTEMPT/completion.json" ] || [ -L "$ATTEMPT/completion.json" ]; then
  [ -f "$ATTEMPT/completion.json" ] && [ ! -L "$ATTEMPT/completion.json" ] || admission_refused "completion is not a regular evidence file: $ATTEMPT/completion.json; preserve it and diagnose the filesystem entry"
  jq -e '.version == 1 and (.status == "completed" or .status == "empty" or
    .status == "interrupted" or .status == "binding-failed")' \
    "$ATTEMPT/completion.json" >/dev/null || admission_refused "malformed completion record: $ATTEMPT/completion.json; preserve it and diagnose its original retained output before any new admission"
  if [ "$(jq -r '.host' "$ATTEMPT/start.json")" = codex ]; then
    cat "${OH_HOME:-$ROOT}/core/review-missing-fresh-refusal.txt"
    exit 2
  fi
  admission_refused "attempt ${ATTEMPT##*/} is already completed; inspect its retained result and required disposition, then use a freshly admitted reviewer if another review is needed"
fi
printf 'review-admission: valid for attempt %s, tree %s on %s\n' \
  "$(jq -r '.id' "$ATTEMPT/start.json")" "$CURRENT_TREE" "$CURRENT_BRANCH"
