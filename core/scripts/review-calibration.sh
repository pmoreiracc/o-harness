#!/usr/bin/env bash
# Prepare and validate reviewer calibration inputs. Promotion remains an explicit reviewed
# human decision: this command creates ignored candidates and never commits or activates one.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
. "${OH_HOME:-$ROOT}/core/accepted-rounds.sh" || exit 1

usage() {
  echo "usage: review-calibration.sh candidate <id> <review-key> <round-id> <family> <failure-file>" >&2
  echo "       review-calibration.sh verify-candidate <case-directory>" >&2
  echo "       review-calibration.sh verify-case <case-directory>" >&2
  echo "       review-calibration.sh replay <case-directory>" >&2
  exit 1
}

sha256_file() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else sha256sum "$1" | awk '{print $1}'
  fi
}

verify_case() {
  local case_dir="$1" expected_id="${2:-}" lifecycle="${3:-}" id family key round tree request_tree request_head status
  local request_doc request_task snapshot_tree snapshot_head review_tree review_request expected_family scenario
  local request_sha snapshot_sha review_sha expected_sha body prior source_prior
  [ -d "$case_dir" ] && [ ! -L "$case_dir" ] || return 1
  [ -f "$case_dir/case.json" ] && [ -f "$case_dir/request.md" ] \
    && [ -f "$case_dir/snapshot.txt" ] && [ -f "$case_dir/review.md" ] \
    && [ -f "$case_dir/expected.md" ] || return 1
  [ ! -L "$case_dir/case.json" ] && [ ! -L "$case_dir/request.md" ] \
    && [ ! -L "$case_dir/snapshot.txt" ] && [ ! -L "$case_dir/review.md" ] \
    && [ ! -L "$case_dir/expected.md" ] || return 1
  jq -e '
    .caseVersion == 1 and
    (.id | type == "string" and test("^[a-z0-9][a-z0-9-]+$")) and
    (.family | type == "string" and test("^[a-z0-9][a-z0-9-]+$")) and
    (.source.key | type == "string") and (.source.round | type == "string" and test("^[0-9a-f]{16}-[0-9]+-[0-9a-f]{16}$")) and
    (.source.tree | type == "string" and test("^[0-9a-f]{16}$")) and
    (.source.priorRounds | type == "number" and . >= 0 and floor == .) and
    (.artifacts.requestSha256 | type == "string" and test("^[0-9a-f]{64}$")) and
    (.artifacts.snapshotSha256 | type == "string" and test("^[0-9a-f]{64}$")) and
    (.artifacts.reviewSha256 | type == "string" and test("^[0-9a-f]{64}$")) and
    (.artifacts.expectedSha256 | type == "string" and test("^[0-9a-f]{64}$")) and
    (.expected == "family-and-failure-scenario-not-exact-prose") and
    (.status | type == "string")
  ' "$case_dir/case.json" >/dev/null || return 1
  id=$(jq -r '.id' "$case_dir/case.json") || return 1
  family=$(jq -r '.family' "$case_dir/case.json") || return 1
  key=$(jq -r '.source.key' "$case_dir/case.json") || return 1
  round=$(jq -r '.source.round' "$case_dir/case.json") || return 1
  tree=$(jq -r '.source.tree' "$case_dir/case.json") || return 1
  source_prior=$(jq -r '.source.priorRounds' "$case_dir/case.json") || return 1
  status=$(jq -r '.status' "$case_dir/case.json") || return 1
  case "$lifecycle:$status" in
    candidate:candidate-human-confirmation-required|confirmed:confirmed-human-reviewed) ;;
    *) return 1 ;;
  esac
  request_sha=$(jq -r '.artifacts.requestSha256' "$case_dir/case.json") || return 1
  snapshot_sha=$(jq -r '.artifacts.snapshotSha256' "$case_dir/case.json") || return 1
  review_sha=$(jq -r '.artifacts.reviewSha256' "$case_dir/case.json") || return 1
  expected_sha=$(jq -r '.artifacts.expectedSha256' "$case_dir/case.json") || return 1
  [ "$(sha256_file "$case_dir/request.md")" = "$request_sha" ] \
    && [ "$(sha256_file "$case_dir/snapshot.txt")" = "$snapshot_sha" ] \
    && [ "$(sha256_file "$case_dir/review.md")" = "$review_sha" ] \
    && [ "$(sha256_file "$case_dir/expected.md")" = "$expected_sha" ] || return 1
  [ "${expected_id:-$(basename "$case_dir")}" = "$id" ] || return 1
  [ "${round%%-*}" = "$tree" ] || return 1
  case "$key" in [0-9][0-9][0-9][0-9]-t[0-9]*|[0-9][0-9][0-9][0-9]-finalize) ;; *) return 1 ;; esac

  request_tree=$(awk '$1 == "tree:" { if (++n == 1) v=$2 } END { if (n != 1) exit 1; print v }' "$case_dir/request.md") || return 1
  request_head=$(awk '$1 == "head:" { if (++n == 1) v=$2 } END { if (n != 1) exit 1; print v }' "$case_dir/request.md") || return 1
  request_doc=$(awk '$1 == "doc:" { if (++n == 1) v=$2 } END { if (n != 1) exit 1; print v }' "$case_dir/request.md") || return 1
  request_task=$(awk '$1 == "task:" { if (++n == 1) v=$2 } END { if (n != 1) exit 1; print v }' "$case_dir/request.md") || return 1
  [ "$request_tree" = "$tree" ] || return 1
  printf '%s\n' "$request_head" | grep -Eq '^[0-9a-f]{40}$' || return 1
  if [ "$request_task" = finalize ]; then [ "$key" = "$request_doc-finalize" ] || return 1
  else [ "$key" = "$request_doc-t$request_task" ] || return 1
  fi
  body=$(mktemp "${TMPDIR:-/tmp}/calibration-request.XXXXXX") || return 1
  sed '1,/^---[[:space:]]*$/d' "$case_dir/request.md" > "$body" || { rm -f "$body"; return 1; }
  . "${OH_HOME:-$ROOT}/core/review-request.sh" || { rm -f "$body"; return 1; }
  review_manifest_check "$body" >/dev/null || { rm -f "$body"; return 1; }
  rm -f "$body"
  snapshot_tree=$(awk '$1 == "tree:" { if (++n == 1) v=$2 } END { if (n != 1) exit 1; print v }' "$case_dir/snapshot.txt") || return 1
  snapshot_head=$(awk '$1 == "head:" { if (++n == 1) v=$2 } END { if (n != 1) exit 1; print v }' "$case_dir/snapshot.txt") || return 1
  [ "$snapshot_tree" = "$tree" ] && [ "$snapshot_head" = "$request_head" ] || return 1
  accepted_snapshot_validate "$case_dir/snapshot.txt" "$tree" "$request_head" || return 1

  review_tree=$(awk '$1 == "tree:" { if (++n == 1) v=$2 } END { if (n != 1) exit 1; print v }' "$case_dir/review.md") || return 1
  review_request=$(awk '$1 == "request:" { if (++n == 1) v=$2 } END { if (n != 1) exit 1; print v }' "$case_dir/review.md") || return 1
  grep -q '^receipt-version: 3$' "$case_dir/review.md" || return 1
  [ "$review_tree" = "$tree" ] && [ "$review_request" = request.md ] || return 1
  . "${OH_HOME:-$ROOT}/core/review-receipt.sh" || return 1
  review_output_check "$case_dir/review.md" >/dev/null || return 1
  prior=$(awk '$1 == "prior-rounds:" { if (++n == 1) v=$2 } END { if (n != 1 || v !~ /^[0-9]+$/) exit 1; print v }' "$case_dir/review.md") || return 1
  [ "$prior" = "$source_prior" ] || return 1
  if [ "$prior" -eq 0 ]; then review_series_output_check "$case_dir/review.md" 0 >/dev/null || return 1
  else review_series_output_check "$case_dir/review.md" 1 >/dev/null || return 1
  fi
  review_normalize "$case_dir/review.md" | grep -qE "^- Finding [0-9]+ \\| Family: $family \\| Relation: " || return 1

  expected_family=$(awk -F': ' '/^family: / { if (++n == 1) v=substr($0,9) } END { if (n != 1) exit 1; print v }' "$case_dir/expected.md") || return 1
  scenario=$(awk -F': ' '/^failure-scenario: / { if (++n == 1) v=substr($0,19) } END { if (n != 1 || v !~ /[^[:space:]]/) exit 1; print v }' "$case_dir/expected.md") || return 1
  [ "$expected_family" = "$family" ] && [ -n "$scenario" ] || return 1
}

case "${1:-}" in
  candidate)
    ID="${2:-}"; KEY="${3:-}"; ROUND_ID="${4:-}"; FAMILY="${5:-}"; FAILURE="${6:-}"
    printf '%s\n' "$ID" | grep -Eq '^[a-z0-9][a-z0-9-]+$' || usage
    printf '%s\n' "$FAMILY" | grep -Eq '^[a-z0-9][a-z0-9-]+$' || usage
    case "$KEY" in [0-9][0-9][0-9][0-9]-t[0-9]*|[0-9][0-9][0-9][0-9]-finalize) ;; *) usage ;; esac
    printf '%s\n' "$ROUND_ID" | grep -Eq '^[0-9a-f]{16}-[0-9]+-[0-9a-f]{16}$' || usage
    DIGEST="${ROUND_ID%%-*}"
    SOURCE="$(review_series_state_root "$ROOT")/accepted/$KEY/$ROUND_ID"
    [ -f "$SOURCE/accepted" ] && [ ! -L "$SOURCE/accepted" ] \
      && [ -f "$SOURCE/request.md" ] && [ ! -L "$SOURCE/request.md" ] \
      && [ -f "$SOURCE/snapshot.txt" ] && [ ! -L "$SOURCE/snapshot.txt" ] \
      && [ -f "$SOURCE/review.md" ] && [ ! -L "$SOURCE/review.md" ] \
      && [ -f "$FAILURE" ] && [ ! -L "$FAILURE" ] || {
      echo "review-calibration: accepted source round or failure scenario is missing." >&2; exit 2;
    }
    SOURCE_PRIOR=$(accepted_header "$SOURCE/review.md" prior-rounds) || exit 2
    SOURCE_ROUNDS=$(accepted_rounds_list "$ROOT" "$KEY") || exit 2
    [ "$(printf '%s\n' "$SOURCE_ROUNDS" | sed -n "$(( SOURCE_PRIOR + 1 ))p")" = "$ROUND_ID" ] || {
      echo "review-calibration: source round is not in the canonical accepted sequence." >&2; exit 2;
    }
    BASE="$ROOT/.deliver/calibration-candidates"
    OUT="$BASE/$ID"
    mkdir -p "$BASE" || exit 1
    LOCK="$BASE/.reserve-$ID"
    if ! mkdir "$LOCK" 2>/dev/null; then
      echo "review-calibration: candidate $ID is already published or being prepared." >&2
      exit 2
    fi
    [ ! -e "$OUT" ] || { rmdir "$LOCK"; echo "review-calibration: candidate $ID already exists." >&2; exit 2; }
    TMP=$(mktemp -d "$BASE/.candidate-$ID.XXXXXX") || { rmdir "$LOCK"; exit 1; }
    cp "$SOURCE/request.md" "$TMP/request.md" \
      && cp "$SOURCE/snapshot.txt" "$TMP/snapshot.txt" \
      && cp "$SOURCE/review.md" "$TMP/review.md" \
      && cp "$FAILURE" "$TMP/expected.md" || { rm -rf "$TMP"; rmdir "$LOCK"; exit 1; }
    REQUEST_SHA=$(sha256_file "$TMP/request.md") || { rm -rf "$TMP"; rmdir "$LOCK"; exit 1; }
    SNAPSHOT_SHA=$(sha256_file "$TMP/snapshot.txt") || { rm -rf "$TMP"; rmdir "$LOCK"; exit 1; }
    REVIEW_SHA=$(sha256_file "$TMP/review.md") || { rm -rf "$TMP"; rmdir "$LOCK"; exit 1; }
    EXPECTED_SHA=$(sha256_file "$TMP/expected.md") || { rm -rf "$TMP"; rmdir "$LOCK"; exit 1; }
    jq -n --arg id "$ID" --arg family "$FAMILY" --arg key "$KEY" --arg round "$ROUND_ID" --arg tree "$DIGEST" --argjson prior "$SOURCE_PRIOR" \
      --arg request_sha "$REQUEST_SHA" --arg snapshot_sha "$SNAPSHOT_SHA" \
      --arg review_sha "$REVIEW_SHA" --arg expected_sha "$EXPECTED_SHA" '{
      caseVersion:1,id:$id,family:$family,source:{key:$key,round:$round,tree:$tree,priorRounds:$prior},
      artifacts:{requestSha256:$request_sha,snapshotSha256:$snapshot_sha,reviewSha256:$review_sha,expectedSha256:$expected_sha},
      expected:"family-and-failure-scenario-not-exact-prose",status:"candidate-human-confirmation-required"
    }' > "$TMP/case.json" || { rm -rf "$TMP"; rmdir "$LOCK"; exit 1; }
    verify_case "$TMP" "$ID" candidate || { rm -rf "$TMP"; rmdir "$LOCK"; exit 1; }
    mv "$TMP" "$OUT" || { rm -rf "$TMP"; rmdir "$LOCK"; exit 1; }
    rmdir "$LOCK" || exit 1
    echo "review-calibration: candidate staged at .deliver/calibration-candidates/$ID"
    echo "Candidate family: $FAMILY. Failure scenario: $OUT/expected.md. Nothing promoted."
    echo "Summarize that scenario and recommend whether it is a useful regression. Offer Confirm (eligible for a later reviewed promotion), Revise (correct the candidate), or Discard (leave it unpromoted)."
    ;;
  verify-candidate)
    verify_case "${2:-}" "" candidate || { echo "review-calibration: invalid candidate" >&2; exit 2; }
    echo "review-calibration: valid candidate"
    ;;
  verify-case)
    verify_case "${2:-}" "" confirmed || { echo "review-calibration: invalid confirmed case" >&2; exit 2; }
    echo "review-calibration: valid confirmed case"
    ;;
  replay)
    CASE_DIR="${2:-}"; verify_case "$CASE_DIR" "" confirmed || { echo "review-calibration: invalid confirmed case" >&2; exit 2; }
    echo "Review this preserved input independently. The expected result is a defect family and"
    echo "concrete failure scenario, never exact historical wording."
    echo ""
    echo "--- readiness request ---"; cat "$CASE_DIR/request.md"
    echo "--- reviewed snapshot ---"; cat "$CASE_DIR/snapshot.txt"
    ;;
  *) usage ;;
esac
