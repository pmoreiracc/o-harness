#!/usr/bin/env bash
# ADR-0051 regression contract for semantic review attempts and configurable windows.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd) || exit 1
. "$ROOT/core/test-fixture.sh" || exit 1
pass=0 fail=0

ok() { pass=$((pass + 1)); printf '  ok    %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf '  FAIL  %s%s\n' "$1" "${2:+ ($2)}"; }

echo "ADR-0051 semantic review workflow"

if ! . "$ROOT/core/review-workflow.sh" 2>/dev/null; then
  bad "the shared ADR-0051 workflow contract is sourceable"
  echo "$pass passed, $fail failed"
  exit 1
fi
. "$ROOT/core/round-ledger.sh" || exit 1
ok "the shared ADR-0051 workflow contract is sourceable"
if git -C "$ROOT" check-ignore -q core/delivery-policy.local.json; then
  ok "the human-owned local delivery policy is gitignored"
else bad "the human-owned local delivery policy is gitignored"; fi

FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT

semantic_case() { # semantic_case <name> <expected outcome> <expected b> <expected c> <expected s> <body>
  local name="$1" expected="$2" blocking="$3" concerns="$4" scope="$5" body="$6" file json
  file="$FIX/$name.md"
  printf '%s\n' "$body" > "$file"
  json=$(review_semantic_json "$file" 2>/dev/null) || {
    bad "$name" "semantic parser failed"
    return
  }
  if printf '%s' "$json" | jq -e \
    --arg outcome "$expected" --argjson b "$blocking" --argjson c "$concerns" --argjson s "$scope" \
    '.outcome == $outcome and .counts.blocking == $b and .counts.concern == $c and .counts.scope == $s' \
    >/dev/null; then ok "$name"; else bad "$name" "$json"; fi
}

semantic_case "duplicate Evidence preserves the concern" "concern" 0 1 0 '[CONCERN] Documentation overclaims proof
  Anchor: ADR-0051
  Where: docs/example.md
  Why: the claim exceeds the test
  Resolve: narrow the claim

## Evidence
- first
## Evidence
- duplicate

VERDICT: findings — 0 blocking, 0 concerns, 0 scope'

semantic_case "declared counts cannot hide a blocker" "blocking" 1 0 0 '[BLOCKING] A real defect survives merge
  Anchor: none — a defect
  Where: src/example.ts:1
  Why: the failing input returns success
  Resolve: fail closed

VERDICT: clean — claimed clean'

semantic_case "all recognized severities are retained" "blocking+concern+scope" 1 1 1 '[SCOPE] Follow-up work exists
[BLOCKING] Current code is broken
[CONCERN] The PR claim is too broad
VERDICT: findings — nonsense'

semantic_case "Markdown decoration cannot hide a blocker" "blocking" 1 0 0 '### **[BLOCKING] Decorated but actionable**
VERDICT: clean — incorrect declared verdict'

semantic_case "token-only emphasis cannot hide a blocker" "blocking" 1 0 0 '- **[BLOCKING]** Decorated marker remains actionable
VERDICT: clean — incorrect declared verdict'

semantic_case "a severity marker without claim text still blocks" "blocking" 1 0 0 '[BLOCKING]
The reviewer omitted the inline claim.
VERDICT: findings'

semantic_case "an explicit clean attempt is clean without exact Markdown" "clean" 0 0 0 'Reviewed the complete tree.
VERDICT: clean — no finding survived.'

semantic_case "empty output is ambiguous" "ambiguous" 0 0 0 ''
semantic_case "finding-free output without an explicit clean result is ambiguous" "ambiguous" 0 0 0 'The review was interrupted before a verdict.'
semantic_case "discussion of a clean verdict is not itself clean" "ambiguous" 0 0 0 'VERDICT: clean was considered but not reached'
semantic_case "a fenced clean example cannot authorize an inconclusive review" "ambiguous" 0 0 0 'The review stopped before a conclusion.
```text
VERDICT: clean — example only
```'
semantic_case "a quoted clean example cannot authorize an inconclusive review" "ambiguous" 0 0 0 'The review stopped before a conclusion.
> VERDICT: clean — quoted example only'
semantic_case "an indented-code clean example cannot authorize an inconclusive review" "ambiguous" 0 0 0 'The review stopped before a conclusion.
    VERDICT: clean — indented example only'
semantic_case "mixed indentation cannot turn a clean example into authority" "ambiguous" 0 0 0 "The review stopped before a conclusion.
 	VERDICT: clean — indented example only"
semantic_case "a draft clean line followed by an incomplete conclusion is ambiguous" "ambiguous" 0 0 0 'VERDICT: clean — draft conclusion
The review stopped before a final conclusion.'

transition_case() { # transition_case <outcome> <expected>
  local got
  got=$(review_required_transition "$1" 2>/dev/null) || got=""
  [ "$got" = "$2" ] && ok "transition $1 -> $2" || bad "transition $1 -> $2" "got ${got:-nothing}"
}
transition_case clean complete
transition_case blocking fix-blockers-review
transition_case blocking+concern fix-blockers-concerns-review
transition_case blocking+scope fix-blockers-route-scope-review
transition_case blocking+concern+scope fix-blockers-concerns-route-scope-review
transition_case concern human-concern
transition_case scope human-scope
transition_case concern+scope human-concern-scope
transition_case ambiguous human-ambiguous

choice_case() { # choice_case <outcome> <answer> <expected semantic choice>
  local got
  got=$(review_choice_parse "$1" "$2" 2>/dev/null) || got=""
  [ "$got" = "$3" ] && ok "$1 accepts exact '$2'" || bad "$1 accepts exact '$2'" "got ${got:-nothing}"
}
choice_case concern "fix concerns" fix-concerns
choice_case concern "accept concerns" accept-concerns
choice_case scope "route scope" route-scope
choice_case scope "dismiss scope" dismiss-scope
choice_case concern+scope "fix concerns and route scope" fix-concerns+route-scope
choice_case concern+scope "fix concerns and dismiss scope" fix-concerns+dismiss-scope
choice_case concern+scope "accept concerns and route scope" accept-concerns+route-scope
choice_case concern+scope "accept concerns and dismiss scope" accept-concerns+dismiss-scope
choice_case ambiguous "review again" review-again
choice_case ambiguous "take over" take-over
if review_choice_parse concern 'please accept concerns' >/dev/null 2>&1; then
  bad "surrounding prose is not a human choice"
else
  ok "surrounding prose is not a human choice"
fi
if review_choice_parse blocking 'accept concerns' >/dev/null 2>&1; then
  bad "a blocker has no bypass choice"
else
  ok "a blocker has no bypass choice"
fi

codex_gate_case() { # codex_gate_case <family> <detail> <expected output>
  local family="$1" detail="$2" expected="$3" got
  got=$(codex_gate_present "$family" "$detail" 2>/dev/null) || got=""
  if [ "$(printf '%s\n' "$got" | sed -n '/Human gate. Send one exact unformatted plain-text line:/,$p')" = "$expected" ]; then
    ok "Codex $family/$detail gate emits each accepted command once as a raw line"
  else
    bad "Codex $family/$detail gate emits each accepted command once as a raw line" "got '$got'"
  fi
}
CODEX_GATE_HEADER='Human gate. Send one exact unformatted plain-text line:'
codex_gate_case review concern "$CODEX_GATE_HEADER
fix concerns
accept concerns"
codex_gate_case review scope "$CODEX_GATE_HEADER
route scope
dismiss scope"
codex_gate_case review concern+scope "$CODEX_GATE_HEADER
fix concerns and route scope
fix concerns and dismiss scope
accept concerns and route scope
accept concerns and dismiss scope"
codex_gate_case review ambiguous "$CODEX_GATE_HEADER
review again
take over"
codex_gate_case review-window - "$CODEX_GATE_HEADER
grant next review window
stop and take it over
stop and escalate to the pr"
codex_gate_case task - "$CODEX_GATE_HEADER
continue
pr
stop"
codex_gate_case scope-destination https://github.com/acme/repo/issues/42 "$CODEX_GATE_HEADER
route scope to https://github.com/acme/repo/issues/42
stop scope routing"
codex_gate_case detached d-1788890000-aaaaaaaaaaaaaaaaaaaaaaaa "$CODEX_GATE_HEADER
resume detached review d-1788890000-aaaaaaaaaaaaaaaaaaaaaaaa
stop detached review"

POL=$(mktemp -d)
mkdir -p "$POL/core"
printf '%s\n' '{"continuation_window_tasks":1,"review_window_rounds":3}' > "$POL/core/delivery-policy.json"
if review_policy_load "$POL" \
   && [ "$REVIEW_POLICY_CONTINUATION" = 1 ] \
   && [ "$REVIEW_POLICY_ROUNDS" = 3 ] \
   && [ "$REVIEW_POLICY_SOURCE" = default ]; then
  ok "tracked defaults load both bounded windows"
else bad "tracked defaults load both bounded windows"; fi
printf '%s\n' '{"review_window_rounds":5,"continuation_window_tasks":2}' > "$POL/core/delivery-policy.local.json"
if review_policy_load "$POL" \
   && [ "$REVIEW_POLICY_CONTINUATION" = 2 ] \
   && [ "$REVIEW_POLICY_ROUNDS" = 5 ] \
   && [ "$REVIEW_POLICY_SOURCE" = local ]; then
  ok "the exact-schema local policy replaces defaults regardless of key order"
else bad "the exact-schema local policy replaces defaults regardless of key order"; fi
for invalid in \
  '{"continuation_window_tasks":1}' \
  '{"continuation_window_tasks":1,"review_window_rounds":0}' \
  '{"continuation_window_tasks":1,"review_window_rounds":3,"extra":1}' \
  'not json'; do
  printf '%s\n' "$invalid" > "$POL/core/delivery-policy.local.json"
  if review_policy_load "$POL" >/dev/null 2>&1; then
    bad "an invalid local policy fails closed: $invalid"
  else
    ok "an invalid local policy fails closed: $invalid"
  fi
done

SER=$(mktemp -d)
printf '.deliver/\n' > "$SER/.gitignore"
printf 'one\n' > "$SER/subject.txt"
(
  cd "$SER" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git switch -qc feature/review-series
) || exit 1
S1=$(review_series_ensure "$SER" feature/review-series 3 2>/dev/null) || S1=""
printf 'two\n' >> "$SER/subject.txt"
git -C "$SER" add subject.txt
git -C "$SER" -c user.email=t@t -c user.name=t commit -qm change
git -C "$SER" -c user.email=t@t -c user.name=t commit --amend -qm amended
S2=$(review_series_ensure "$SER" feature/review-series 9 2>/dev/null) || S2=""
[ -n "$S1" ] && [ "$S1" = "$S2" ] \
  && ok "amending HEAD preserves the non-delivery review series" \
  || bad "amending HEAD preserves the non-delivery review series" "$S1 != $S2"
if [ -n "$S1" ] && [ "$(review_series_window "$SER" "$S1" 2>/dev/null)" = 3 ]; then
  ok "a review series snapshots its configured window"
else bad "a review series snapshots its configured window"; fi
if [ -n "$S1" ] && review_series_close "$SER" "$S1" resolved >/dev/null 2>&1 \
   && review_series_close "$SER" "$S1" resolved >/dev/null 2>&1; then
  S1_CONTEXT=$(jq -r '.context' "$(review_series_dir "$SER" "$S1")/series.json")
  printf '%s\n' "$S1" > "$(review_series_state_root "$SER")/contexts/$S1_CONTEXT/current"
  S3=$(review_series_ensure "$SER" feature/review-series 9 2>/dev/null) || S3=""
  [ -n "$S3" ] && [ "$S3" != "$S1" ] \
    && ok "idempotent closure and stale-pointer recovery create a new series" \
    || bad "idempotent closure and stale-pointer recovery create a new series"
else bad "a review series closes only through an explicit terminal transition"; fi
(
  cd "$SER" || exit 1
  git switch -qc feature/legacy-series
  git -c user.email=t@t -c user.name=t commit -qm legacy --allow-empty
) || exit 1
LEGACY_HEAD=$(git -C "$SER" rev-parse HEAD)
LEGACY_KEY="nd/feature/legacy-series/$LEGACY_HEAD"
LEGACY_SERIES=$(review_series_ensure "$SER" feature/legacy-series 3 invariant-reviewer "$LEGACY_KEY" 2>/dev/null) || LEGACY_SERIES=""
LEGACY_BEFORE=$(review_series_key_for "$SER" feature/legacy-series 2>/dev/null) || LEGACY_BEFORE=""
git -C "$SER" -c user.email=t@t -c user.name=t commit --amend -qm legacy-amended --allow-empty
LEGACY_AFTER=$(review_series_key_for "$SER" feature/legacy-series 2>/dev/null) || LEGACY_AFTER=""
if [ -n "$LEGACY_SERIES" ] && [ "$LEGACY_BEFORE" = "$LEGACY_KEY" ] && [ "$LEGACY_AFTER" = "$LEGACY_KEY" ]; then
  ok "a migrated historical key stays stable across the first start and amended HEAD"
else bad "a migrated historical key stays stable across the first start and amended HEAD"; fi

RACE_CONTEXT=$(jq -r '.context' "$(review_series_dir "$SER" "$LEGACY_SERIES")/series.json" 2>/dev/null)
RACE_DIR="$(review_series_state_root "$SER")/contexts/$RACE_CONTEXT"
if review_context_lock_acquire "$SER" "$RACE_CONTEXT" 2>/dev/null; then
  jq -cn --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{version:1,status:"closed",reason:"resolved",closedAt:$at}' \
    > "$(review_series_dir "$SER" "$LEGACY_SERIES")/closed.json"
  (
    . "$ROOT/core/review-workflow.sh"
    review_series_ensure "$SER" feature/legacy-series 3 invariant-reviewer "$LEGACY_KEY"
  ) >/dev/null 2>&1
  RACE_ENSURE_RC=$?
  RACE_POINTER_BEFORE=$(cat "$RACE_DIR/current" 2>/dev/null || true)
  review_context_lock_release >/dev/null 2>&1
  review_series_close "$SER" "$LEGACY_SERIES" resolved >/dev/null 2>&1
  RACE_NEW=$(review_series_ensure "$SER" feature/legacy-series 3 invariant-reviewer "$LEGACY_KEY" 2>/dev/null) || RACE_NEW=""
  RACE_POINTER_AFTER=$(cat "$RACE_DIR/current" 2>/dev/null || true)
else
  RACE_ENSURE_RC=0; RACE_POINTER_BEFORE=""; RACE_NEW=""; RACE_POINTER_AFTER=""
fi
if [ "$RACE_ENSURE_RC" -ne 0 ] && [ "$RACE_POINTER_BEFORE" = "$LEGACY_SERIES" ] \
   && [ -n "$RACE_NEW" ] && [ "$RACE_NEW" != "$LEGACY_SERIES" ] \
   && [ "$RACE_POINTER_AFTER" = "$RACE_NEW" ]; then
  ok "series close and creation serialize the close-published pointer interleaving"
else bad "series close and creation serialize the close-published pointer interleaving"; fi

if review_context_lock_acquire "$SER" "$RACE_CONTEXT" 2>/dev/null; then
  touch -t 197001010000 "$REVIEW_CONTEXT_LOCK_PATH"
  (
    . "$ROOT/core/review-workflow.sh"
    review_series_ensure "$SER" feature/legacy-series 3 invariant-reviewer "$LEGACY_KEY"
  ) >/dev/null 2>&1
  LIVE_LOCK_RC=$?
  review_context_lock_release >/dev/null 2>&1
else LIVE_LOCK_RC=0; fi
if [ "$LIVE_LOCK_RC" -ne 0 ]; then
  ok "a paused context lock is never reclaimed while its owner generation is alive"
else bad "a paused context lock is never reclaimed while its owner generation is alive"; fi

STALE_NONCE=deadbeefdeadbeefdeadbeef
printf 'pid: %s\ngeneration: %s\nepoch: 1\nnonce: %s\n' "$$" stale-process-generation "$STALE_NONCE" \
  > "$RACE_DIR/.context.lock"
STALE_PID_SERIES=$(review_series_ensure "$SER" feature/legacy-series 3 invariant-reviewer "$LEGACY_KEY" 2>/dev/null) || STALE_PID_SERIES=""
if [ "$STALE_PID_SERIES" = "$RACE_NEW" ] && [ ! -e "$RACE_DIR/.context.lock" ]; then
  ok "a stale lock is reclaimed even when its recorded PID has been reused"
else bad "a stale lock is reclaimed even when its recorded PID has been reused"; fi

stat() {
  if [ "${1:-}" = -f ]; then printf 'GNU filesystem noise that must be discarded\n'; return 1; fi
  if [ "${1:-}" = -c ]; then printf '123:2026-09-09 00:00:00.123456789 +0000\n'; return 0; fi
  command stat "$@"
}
GNU_ID_ONE=$(review_stat_identity "$SER/.git/logs/refs/heads/feature/legacy-series" 2>/dev/null) || GNU_ID_ONE=""
GNU_ID_TWO=$(review_stat_identity "$SER/.git/logs/refs/heads/feature/legacy-series" 2>/dev/null) || GNU_ID_TWO=""
unset -f stat
if [ "$GNU_ID_ONE" = 'gnu:123:2026-09-09 00:00:00.123456789 +0000' ] && [ "$GNU_ID_TWO" = "$GNU_ID_ONE" ]; then
  ok "GNU stat fallback discards failed BSD output and keeps a stable identity"
else bad "GNU stat fallback discards failed BSD output and keeps a stable identity" "$GNU_ID_ONE / $GNU_ID_TWO"; fi

printf 'snapshot\n' > "$SER/snapshot.txt"
RACE_ATTEMPTS="$(review_attempts_dir "$SER" "$RACE_NEW")"
if review_context_lock_acquire "$SER" "$RACE_CONTEXT" 2>/dev/null; then
  (
    . "$ROOT/core/review-workflow.sh"
    . "$ROOT/core/round-ledger.sh"
    review_attempt_start "$SER" "$RACE_NEW" codex interleaved-reviewer session \
      1212121212121212 feature/legacy-series "$LEGACY_KEY" "$SER/snapshot.txt" -
  ) >/dev/null 2>&1
  RACE_START_RC=$?
  review_context_lock_release >/dev/null 2>&1
else RACE_START_RC=0; fi
review_series_close "$SER" "$RACE_NEW" resolved >/dev/null 2>&1
if [ "$RACE_START_RC" -ne 0 ] \
   && ! review_attempt_start "$SER" "$RACE_NEW" codex after-close-reviewer session \
      1212121212121212 feature/legacy-series "$LEGACY_KEY" "$SER/snapshot.txt" - >/dev/null 2>&1 \
   && [ "$(find "$RACE_ATTEMPTS" -name start.json -type f 2>/dev/null | wc -l | tr -d ' ')" = 0 ]; then
  ok "series close and attempt start cannot publish across their lifecycle boundary"
else bad "series close and attempt start cannot publish across their lifecycle boundary"; fi

LOST=$(mktemp -d)
printf '.deliver/\n' > "$LOST/.gitignore"
printf 'subject\n' > "$LOST/subject.txt"
(
  cd "$LOST" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git switch -qc feature/lost-stop
) || exit 1
printf 'snapshot\n' > "$LOST/snapshot.txt"
LOST_SERIES=$(review_series_ensure "$LOST" feature/lost-stop 3 invariant-reviewer nd/lost-stop 2>/dev/null)
LOST_FIRST=$(review_attempt_start "$LOST" "$LOST_SERIES" codex lost-reviewer lost-session \
  1111111111111111 feature/lost-stop nd/lost-stop "$LOST/snapshot.txt" - 2>/dev/null) || LOST_FIRST=""
review_attempt_start "$LOST" "$LOST_SERIES" codex premature-reviewer lost-session \
  1111111111111111 feature/lost-stop nd/lost-stop "$LOST/snapshot.txt" - >/dev/null 2>&1
LOST_PREMATURE_RC=$?
printf '%s\n' 'The review stopped before a conclusion.' > "$LOST/raw.md"
review_attempt_complete "$LOST" "$LOST_FIRST" completed "$LOST/raw.md" >/dev/null 2>&1
review_resolution_record "$LOST" "$LOST_FIRST" review-again human:test 1111111111111111 >/dev/null 2>&1
LOST_NEXT=$(review_attempt_start "$LOST" "$LOST_SERIES" codex fresh-reviewer lost-session \
  1111111111111111 feature/lost-stop nd/lost-stop "$LOST/snapshot.txt" - 2>/dev/null) || LOST_NEXT=""
if [ -n "$LOST_FIRST" ] && [ "$LOST_PREMATURE_RC" -ne 0 ] && [ -n "$LOST_NEXT" ] \
   && [ "$(jq -r '.status' "$LOST_FIRST/completion.json" 2>/dev/null)" = completed ] \
   && [ "$(review_attempt_count "$LOST" "$LOST_SERIES" 2>/dev/null)" = 2 ]; then
  ok "a new Codex reviewer waits for retention and the explicit semantic transition"
else bad "a new Codex reviewer waits for retention and the explicit semantic transition"; fi
rm -rf "$LOST"

FALSE_CLEAN=$(mktemp -d)
mkdir -p "$FALSE_CLEAN/core/scripts" "$FALSE_CLEAN/.deliver"
cp "$ROOT/core/scripts/tree-digest.sh" "$FALSE_CLEAN/core/scripts/tree-digest.sh"
printf '.deliver/\n' > "$FALSE_CLEAN/.gitignore"
printf 'subject\n' > "$FALSE_CLEAN/subject.txt"
(
  cd "$FALSE_CLEAN" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git switch -qc feature/false-clean
) || exit 1
printf 'snapshot\n' > "$FALSE_CLEAN/.deliver/snapshot.txt"
FALSE_CLEAN_TREE=$(CLAUDE_PROJECT_DIR="$FALSE_CLEAN" "$FALSE_CLEAN/core/scripts/tree-digest.sh")
FALSE_CLEAN_SERIES=$(review_series_ensure "$FALSE_CLEAN" feature/false-clean 3 invariant-reviewer nd/false-clean 2>/dev/null)
FALSE_CLEAN_ATTEMPT=$(review_attempt_start "$FALSE_CLEAN" "$FALSE_CLEAN_SERIES" codex false-clean-reviewer false-clean-session \
  "$FALSE_CLEAN_TREE" feature/false-clean nd/false-clean "$FALSE_CLEAN/.deliver/snapshot.txt" - 2>/dev/null)
printf '%s\n' 'Review stopped without a conclusion.' '```text' 'VERDICT: clean — example' '```' \
  '    VERDICT: clean — indented example' \
  > "$FIX/false-clean-attempt.md"
review_attempt_complete "$FALSE_CLEAN" "$FALSE_CLEAN_ATTEMPT" completed "$FIX/false-clean-attempt.md" >/dev/null 2>&1
if [ "$(jq -r '.outcome' "$FALSE_CLEAN_ATTEMPT/completion.json" 2>/dev/null)" = ambiguous ] \
   && ! review_attempt_authorizes "$FALSE_CLEAN" "$FALSE_CLEAN_ATTEMPT" "$FALSE_CLEAN_TREE" >/dev/null 2>&1; then
  ok "quoted, fenced, or indented clean examples cannot authorize a tracked transition"
else bad "quoted, fenced, or indented clean examples cannot authorize a tracked transition"; fi
rm -rf "$FALSE_CLEAN"

ATT=$(mktemp -d)
printf '.deliver/\n' > "$ATT/.gitignore"
printf 'subject\n' > "$ATT/subject.txt"
(
  cd "$ATT" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git switch -qc feature/attempts
) || exit 1
printf 'snapshot\n' > "$ATT/snapshot.txt"
AS=$(review_series_ensure "$ATT" feature/attempts 10 2>/dev/null) || AS=""
AK="nd/$AS"
A1=$(review_attempt_start "$ATT" "$AS" codex reviewer-a session-a 1111111111111111 \
  feature/attempts "$AK" "$ATT/snapshot.txt" - 2>/dev/null) || A1=""
[ -n "$A1" ] && [ "$(review_attempt_count "$ATT" "$AS" 2>/dev/null)" = 1 ] \
  && [ ! -e "$(review_series_dir "$ATT" "$AS")/.start.lock" ] \
  && ok "attempt allocation uses the single OS-released lifecycle lock only" \
  || bad "attempt allocation uses the single OS-released lifecycle lock only"
mkdir -p "$(review_attempts_dir "$ATT" "$AS")/a-999999"
if [ "$(review_attempt_count "$ATT" "$AS" 2>/dev/null)" = 1 ]; then
  ok "a crash before admission does not consume or block the review window"
else bad "a crash before admission does not consume or block the review window"; fi
mkdir -p "$(review_attempts_dir "$ATT" "$AS")/a-999998"
printf '{}\n' > "$(review_attempts_dir "$ATT" "$AS")/a-999998/start.json"
if round_count "$ATT" "$AK" >/dev/null 2>&1; then
  bad "malformed admitted attempt state cannot collapse to zero rounds"
else ok "malformed admitted attempt state cannot collapse to zero rounds"; fi
rm -rf "$(review_attempts_dir "$ATT" "$AS")/a-999998"
printf '%s\n' '[CONCERN] Retained despite duplicated headings
## Evidence
## Evidence
VERDICT: findings — 0 blocking, 0 concerns, 0 scope' > "$ATT/raw.md"
if review_attempt_complete "$ATT" "$A1" completed "$ATT/raw.md" 12 34 \
   && [ "$(jq -r '.outcome' "$A1/completion.json")" = concern ] \
   && [ "$(jq -r '.formatAnomalous' "$A1/completion.json")" = true ] \
   && grep -qF 'Retained despite duplicated headings' "$A1/raw.md"; then
  ok "completion appends raw output and computed semantic findings without correction"
else bad "completion appends raw output and computed semantic findings without correction"; fi
printf '%s\n' '[CONCERN] Different bytes' 'VERDICT: findings' > "$ATT/different-raw.md"
if review_attempt_complete "$ATT" "$A1" completed "$ATT/raw.md" >/dev/null 2>&1 \
   && ! review_attempt_complete "$ATT" "$A1" completed "$ATT/different-raw.md" >/dev/null 2>&1; then
  ok "an identical completion retry is idempotent but different bytes cannot overwrite it"
else bad "an identical completion retry is idempotent but different bytes cannot overwrite it"; fi

if review_resolution_record "$ATT" "$A1" accept-concerns codex:user-message 1111111111111111 \
   && review_attempt_authorizes "$ATT" "$A1" 1111111111111111; then
  ok "exact-tree human concern acceptance authorizes only the review outcome"
else bad "exact-tree human concern acceptance authorizes only the review outcome"; fi
CONCERN_ID=$(review_attempt_pr_resolution_id "$ATT" "$A1" 2>/dev/null) || CONCERN_ID=""
CONCERN_SECTION=$(review_pr_resolutions_render "$ATT" feature/attempts "$AS" "${A1##*/}" 2>/dev/null) || CONCERN_SECTION=""
printf '%s\n' "$CONCERN_SECTION" > "$FIX/concern-section.md"
if printf '%s' "$CONCERN_ID" | grep -Eq '^[0-9a-f]{64}$' \
   && grep -qF '[CONCERN] Retained despite duplicated headings' "$FIX/concern-section.md" \
   && grep -qF 'Review-Choice: accept-concerns' "$FIX/concern-section.md" \
   && review_pr_resolution_section_validate "$FIX/concern-section.md" "$CONCERN_ID"; then
  ok "an accepted concern is retained with its human choice in the generated PR section"
else bad "an accepted concern is retained with its human choice in the generated PR section"; fi
if review_attempt_authorizes "$ATT" "$A1" 2222222222222222 >/dev/null 2>&1; then
  bad "a human resolution cannot authorize a changed tree"
else ok "a human resolution cannot authorize a changed tree"; fi

printf 'changed\n' >> "$ATT/subject.txt"
A2_TREE=$(CLAUDE_PROJECT_DIR="$ATT" "$ROOT/core/scripts/tree-digest.sh")
A2=$(review_attempt_start "$ATT" "$AS" codex reviewer-b session-a "$A2_TREE" \
  feature/attempts "$AK" "$ATT/snapshot.txt" - 2>/dev/null) || A2=""
[ -n "$A2" ] && [ "$A1" != "$A2" ] && [ "$(review_attempt_count "$ATT" "$AS" 2>/dev/null)" = 2 ] \
  && ok "a newly spawned reviewer follows the evidenced prior transition" \
  || bad "a newly spawned reviewer follows the evidenced prior transition"
if [ "$(jq -r '.ordinal' "$A1/start.json" 2>/dev/null)" = 1 ] \
   && [ "$(jq -r '.ordinal' "$A2/start.json" 2>/dev/null)" = 2 ]; then
  ok "attempt ordinals increase instead of depending on random directory names"
else bad "attempt ordinals increase instead of depending on random directory names"; fi
printf 'review output was not classifiable\n' > "$ATT/ambiguous.md"
review_attempt_complete "$ATT" "$A2" completed "$ATT/ambiguous.md" >/dev/null 2>&1
review_resolution_record "$ATT" "$A2" review-again codex:user-message "$A2_TREE" >/dev/null 2>&1

if review_attempt_start "$ATT" "$AS" codex reviewer-a session-a "$A2_TREE" \
   feature/attempts "$AK" "$ATT/snapshot.txt" - >/dev/null 2>&1; then
  bad "a reused Codex reviewer cannot claim fresh admission"
else ok "a reused Codex reviewer cannot claim fresh admission"; fi

CA=$(review_attempt_start "$ATT" "$AS" claude claude session-one "$A2_TREE" \
  feature/attempts "$AK" "$ATT/snapshot.txt" - 2>/dev/null) || CA=""
if review_attempt_start "$ATT" "$AS" claude claude session-one "$A2_TREE" \
   feature/attempts "$AK" "$ATT/snapshot.txt" - >/dev/null 2>&1; then
  bad "a second Claude reviewer in the same live session is refused"
else ok "a second Claude reviewer in the same live session is refused"; fi
CB=$(review_attempt_start "$ATT" "$AS" claude claude session-two "$A2_TREE" \
  feature/attempts "$AK" "$ATT/snapshot.txt" - 2>/dev/null) || CB=""
if [ -n "$CB" ] && [ "$(jq -r '.status' "$CA/completion.json" 2>/dev/null)" = interrupted ] &&
   [ "$(jq -r '.noResult' "$CA/completion.json")" = true ] &&
   review_attempt_chain_valid_through "$ATT" "$CB"; then
  ok "a new Claude session automatically replaces its abandoned zero-byte attempt within the same series"
else bad "a new Claude session automatically replaces its abandoned zero-byte attempt within the same series"; fi
cp "$CA/completion.json" "$FIX/current-interruption.json"
jq 'del(.noResult)' "$CA/completion.json" > "$FIX/legacy-interruption.json"
cp "$FIX/legacy-interruption.json" "$CA/completion.json"
if ! review_attempt_allows_next "$ATT" "$CA" "$A2_TREE" &&
   review_attempt_allows_next "$ATT" "$CA" "$A2_TREE" true; then
  ok "legacy interrupted chains remain readable without permitting new automatic retries"
else bad "legacy interrupted chains remain readable without permitting new automatic retries"; fi
cp "$FIX/current-interruption.json" "$CA/completion.json"
if review_attempt_complete "$ATT" "$CB" empty "$ATT/ambiguous.md" "" "" true >/dev/null 2>&1; then
  bad "no-result classification cannot discard nonempty review output"
else ok "no-result classification cannot discard nonempty review output"; fi
review_attempt_complete "$ATT" "$CB" empty - "" "" true >/dev/null 2>&1
if review_attempt_allows_next "$ATT" "$CB" "$A2_TREE" &&
   ! review_attempt_allows_next "$ATT" "$CB" 0000000000000000 &&
   ! review_attempt_authorizes "$ATT" "$CB" "$A2_TREE"; then
  ok "zero-output completion permits same-tree replacement but never completion or stale binding"
else bad "zero-output completion permits same-tree replacement but never completion or stale binding"; fi

printf '%s\n' '[BLOCKING] Cannot be waived
VERDICT: findings' > "$ATT/blocking.md"
BA=$(review_attempt_start "$ATT" "$AS" codex reviewer-c session-a "$A2_TREE" \
  feature/attempts "$AK" "$ATT/snapshot.txt" - 2>/dev/null) || BA=""
cp "$ATT/blocking.md" "$BA/raw.md"
if review_attempt_complete "$ATT" "$BA" completed "$ATT/blocking.md" >/dev/null 2>&1 \
   && [ "$(jq -r '.outcome' "$BA/completion.json")" = blocking ]; then
  ok "completion recovers an identical raw file left before atomic publication"
else bad "completion recovers an identical raw file left before atomic publication"; fi
if review_resolution_record "$ATT" "$BA" accept-concerns codex:user-message "$A2_TREE" >/dev/null 2>&1; then
  bad "no human record can bypass a blocker"
else ok "no human record can bypass a blocker"; fi
if review_attempt_start "$ATT" "$AS" codex reviewer-d session-a "$A2_TREE" \
   feature/attempts "$AK" "$ATT/snapshot.txt" - >/dev/null 2>&1; then
  bad "a later clean reviewer cannot supersede an unresolved same-tree blocker"
else ok "a later clean reviewer cannot supersede an unresolved same-tree blocker"; fi

mkdir -p "$ATT/.deliver/reviews/rejected" "$ATT/.deliver/reviews/inflight/pending-fixture"
printf 'rejected: historical format\nat: 2026-09-08T20:00:00Z\n' > "$ATT/.deliver/reviews/rejected/a-000001.md"
PENDING_TOKEN=aaaaaaaaaaaaaaaaaaaaaaaa
PENDING_ROUND=3333333333333333-1788890000-aaaaaaaaaaaaaaaa
printf '%s\n' "$PENDING_TOKEN" > "$ATT/.deliver/reviews/inflight/pending-fixture/owner"
printf '3333333333333333\t1788890000\tfeature/old\tnd/old\t/tmp/input\t-\t-\t%s\t%s\tclaude\n' \
  "$ATT/.deliver/reviews/inflight/pending-fixture" "$PENDING_TOKEN" \
  > "$ATT/.deliver/reviews/inflight/pending-fixture/admission"
printf 'rejected: correction still active\nat: 2026-09-08T20:00:00Z\n' \
  > "$ATT/.deliver/reviews/rejected/$PENDING_ROUND.md"
printf 'rejected: correction ended without acceptance\nat: 2026-09-08T20:00:00Z\n' \
  > "$ATT/.deliver/reviews/rejected/4444444444444444-1788890000-bbbbbbbbbbbbbbbb.md"

DASH=$(CLAUDE_PROJECT_DIR="$ATT" node "$ROOT/core/scripts/review-dashboard.mjs" --stdout 2>/dev/null) || DASH=""
if printf '%s' "$DASH" | jq -e '
  .reportVersion == 2 and .summary.nonDeliveryReviews == 5 and
  .summary.reviewsSalvaged == 2 and .summary.pendingAttempts == 0 and
  .summary.interruptedAttempts == 1 and .summary.hostTokenUsage.input == 12 and
  .summary.corrections.attempted == 3 and .summary.corrections.succeeded == 1 and
  .summary.corrections.failed == 1 and .summary.corrections.pending == 1 and
  ([.historicalCorrections[].status] | sort) == ["failed","pending","succeeded"] and
  .tasks[0].rounds[0].attemptId == "a-000001"
' >/dev/null 2>&1; then
  ok "dashboard correlates non-delivery attempts, salvaged output, lifecycle, and actual tokens"
else bad "dashboard correlates non-delivery attempts, salvaged output, lifecycle, and actual tokens" "$DASH"; fi

CON=$(mktemp -d)
printf '.deliver/\n' > "$CON/.gitignore"
printf 'subject\n' > "$CON/subject.txt"
(
  cd "$CON" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git switch -qc feature/concurrent
) || exit 1
printf 'snapshot\n' > "$CON/snapshot.txt"
CON_SERIES=$(review_series_ensure "$CON" feature/concurrent 3 invariant-reviewer nd/concurrent 2>/dev/null)
for CON_N in 1 2; do
  CON_ATTEMPT=$(review_attempt_start "$CON" "$CON_SERIES" codex "pre-$CON_N" session 5555555555555555 \
    feature/concurrent nd/concurrent "$CON/snapshot.txt" - 2>/dev/null) || break
  printf 'unclassifiable\n' > "$CON/raw-$CON_N.md"
  review_attempt_complete "$CON" "$CON_ATTEMPT" completed "$CON/raw-$CON_N.md" >/dev/null 2>&1
  review_resolution_record "$CON" "$CON_ATTEMPT" review-again human:test 5555555555555555 >/dev/null 2>&1
done
(
  . "$ROOT/core/round-ledger.sh"
  review_attempt_start "$CON" "$CON_SERIES" codex racer-a session 5555555555555555 \
    feature/concurrent nd/concurrent "$CON/snapshot.txt" - > "$CON/race-a" 2>/dev/null
) & CON_PID_A=$!
(
  . "$ROOT/core/round-ledger.sh"
  review_attempt_start "$CON" "$CON_SERIES" codex racer-b session 5555555555555555 \
    feature/concurrent nd/concurrent "$CON/snapshot.txt" - > "$CON/race-b" 2>/dev/null
) & CON_PID_B=$!
wait "$CON_PID_A"; CON_RC_A=$?
wait "$CON_PID_B"; CON_RC_B=$?
if [ $((CON_RC_A == 0 ? 1 : 0)) -ne $((CON_RC_B == 0 ? 1 : 0)) ] \
   && [ "$(review_attempt_count "$CON" "$CON_SERIES")" = 3 ]; then
  ok "atomic allocation admits exactly one concurrent start at the review ceiling"
else bad "atomic allocation admits exactly one concurrent start at the review ceiling"; fi
rm -rf "$CON"

DET=$(mktemp -d)
printf '.deliver/\n' > "$DET/.gitignore"
printf 'detached\n' > "$DET/subject.txt"
(
  cd "$DET" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git checkout -q --detach HEAD
) || exit 1
DET_ID=$(review_detached_context_for_session "$DET" detached-session-one 1 2>/dev/null) || DET_ID=""
REVIEW_DETACHED_CONTEXT_ID="$DET_ID"; export REVIEW_DETACHED_CONTEXT_ID
DET_SERIES=$(review_series_ensure "$DET" HEAD 3 invariant-reviewer nd/detached 2>/dev/null) || DET_SERIES=""
unset REVIEW_DETACHED_CONTEXT_ID
DET_SAME=$(review_detached_context_for_session "$DET" detached-session-one 0 2>/dev/null) || DET_SAME=""
if [ -n "$DET_ID" ] && [ "$DET_SAME" = "$DET_ID" ] && [ -n "$DET_SERIES" ]; then
  ok "detached HEAD creates an explicit context bound to the live host session"
else bad "detached HEAD creates an explicit context bound to the live host session"; fi
if review_detached_context_for_session "$DET" detached-session-two 1 >/dev/null 2>&1; then
  bad "a different host session cannot silently resume an open detached context"
else ok "a different host session cannot silently resume an open detached context"; fi
if review_detached_context_bind_session "$DET" detached-session-two "$DET_ID" human:test \
   && [ "$(review_detached_context_for_session "$DET" detached-session-two 0 2>/dev/null)" = "$DET_ID" ]; then
  ok "the explicit detached context ID resumes only the same repository"
else bad "the explicit detached context ID resumes only the same repository"; fi
rm -rf "$DET"

SCOPE_ROOT=$(mktemp -d)
mkdir -p "$SCOPE_ROOT/core/scripts" "$SCOPE_ROOT/.deliver"
cp "$ROOT/core/scripts/tree-digest.sh" "$SCOPE_ROOT/core/scripts/tree-digest.sh"
printf '.deliver/\n' > "$SCOPE_ROOT/.gitignore"
printf '# Harness backlog\n' > "$SCOPE_ROOT/core/BACKLOG.md"
printf 'before\n' > "$SCOPE_ROOT/core/subject.sh"
(
  cd "$SCOPE_ROOT" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git switch -qc feature/blocker-scope
) || exit 1
printf 'after\n' >> "$SCOPE_ROOT/core/subject.sh"
printf 'snapshot\n' > "$SCOPE_ROOT/.deliver/snapshot.txt"
SCOPE_TREE=$(CLAUDE_PROJECT_DIR="$SCOPE_ROOT" "$SCOPE_ROOT/core/scripts/tree-digest.sh")
SCOPE_SERIES=$(review_series_ensure "$SCOPE_ROOT" feature/blocker-scope 3 2>/dev/null) || SCOPE_SERIES=""
SCOPE_KEY="nd/$SCOPE_SERIES"
SCOPE_ATTEMPT=$(review_attempt_start "$SCOPE_ROOT" "$SCOPE_SERIES" codex scope-reviewer scope-session \
  "$SCOPE_TREE" feature/blocker-scope "$SCOPE_KEY" "$SCOPE_ROOT/.deliver/snapshot.txt" - 2>/dev/null) || SCOPE_ATTEMPT=""
printf '%s\n' '[BLOCKING] Fix this task defect' '- **[SCOPE]** Follow-up harness work' 'VERDICT: findings' > "$FIX/blocker-scope.md"
review_attempt_complete "$SCOPE_ROOT" "$SCOPE_ATTEMPT" completed "$FIX/blocker-scope.md" >/dev/null 2>&1
if review_scope_apply "$SCOPE_ROOT" "$SCOPE_ATTEMPT" route-scope \
   && grep -qF -- '- **[SCOPE]** Follow-up harness work' "$SCOPE_ROOT/core/BACKLOG.md" \
   && [ "$(grep -c '^## Open$' "$SCOPE_ROOT/core/BACKLOG.md")" = 1 ] \
   && [ "$(jq -r '.source' "$SCOPE_ATTEMPT/scope-transition.json")" = required-by-policy ]; then
  ok "blocker plus decorated scope routes scope before the one required fresh review"
else bad "blocker plus decorated scope routes scope before the one required fresh review"; fi
SCOPE_RESULT=$(CLAUDE_PROJECT_DIR="$SCOPE_ROOT" "$SCOPE_ROOT/core/scripts/tree-digest.sh")
if review_attempt_authorizes "$SCOPE_ROOT" "$SCOPE_ATTEMPT" "$SCOPE_RESULT" >/dev/null 2>&1; then
  bad "routing scope cannot bypass the blocker"
else ok "routing scope cannot bypass the blocker"; fi
if review_attempt_start "$SCOPE_ROOT" "$SCOPE_SERIES" codex route-only-reviewer scope-session \
   "$SCOPE_RESULT" feature/blocker-scope "$SCOPE_KEY" "$SCOPE_ROOT/.deliver/snapshot.txt" - >/dev/null 2>&1; then
  bad "the scope-routing delta alone cannot stand in for the blocker fix"
else
  printf 'blocker fixed\n' >> "$SCOPE_ROOT/core/subject.sh"
  SCOPE_FIXED=$(CLAUDE_PROJECT_DIR="$SCOPE_ROOT" "$SCOPE_ROOT/core/scripts/tree-digest.sh")
  if review_attempt_start "$SCOPE_ROOT" "$SCOPE_SERIES" codex blocker-fixed-reviewer scope-session \
     "$SCOPE_FIXED" feature/blocker-scope "$SCOPE_KEY" "$SCOPE_ROOT/.deliver/snapshot.txt" - >/dev/null 2>&1; then
    ok "blocker plus scope admits review only after routing and a separate blocker fix"
  else bad "blocker plus scope admits review only after routing and a separate blocker fix"; fi
fi

(
  cd "$SCOPE_ROOT" || exit 1
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm routed
  mkdir -p docs/design
  printf '%s\n' '---' 'type: design' 'status: approved' 'last-verified: 2026-09-08' '---' '# Scope fixture' > docs/design/0999-scope.md
  printf 'product\n' > product.txt
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm design
  git switch -qc feature/human-scope
) || exit 1
printf 'changed\n' >> "$SCOPE_ROOT/product.txt"
HUMAN_TREE=$(CLAUDE_PROJECT_DIR="$SCOPE_ROOT" "$SCOPE_ROOT/core/scripts/tree-digest.sh")
HUMAN_SERIES=$(review_series_ensure "$SCOPE_ROOT" feature/human-scope 3 invariant-reviewer 0999-t1 2>/dev/null) || HUMAN_SERIES=""
HUMAN_ATTEMPT=$(review_attempt_start "$SCOPE_ROOT" "$HUMAN_SERIES" codex human-scope-reviewer scope-session \
  "$HUMAN_TREE" feature/human-scope 0999-t1 "$SCOPE_ROOT/.deliver/snapshot.txt" - 2>/dev/null) || HUMAN_ATTEMPT=""
printf '%s\n' '[SCOPE] Deliberately not part of this task' 'VERDICT: findings' > "$FIX/scope-only.md"
review_attempt_complete "$SCOPE_ROOT" "$HUMAN_ATTEMPT" completed "$FIX/scope-only.md" >/dev/null 2>&1
review_resolution_record "$SCOPE_ROOT" "$HUMAN_ATTEMPT" dismiss-scope codex:user-message "$HUMAN_TREE" >/dev/null 2>&1
review_scope_apply "$SCOPE_ROOT" "$HUMAN_ATTEMPT" dismiss-scope >/dev/null 2>&1
HUMAN_RESULT=$(CLAUDE_PROJECT_DIR="$SCOPE_ROOT" "$SCOPE_ROOT/core/scripts/tree-digest.sh")
rm -f "$HUMAN_ATTEMPT/scope-transition.json"
if review_resolution_record "$SCOPE_ROOT" "$HUMAN_ATTEMPT" dismiss-scope codex:retry "$HUMAN_TREE" \
   && review_scope_apply "$SCOPE_ROOT" "$HUMAN_ATTEMPT" dismiss-scope \
   && review_attempt_authorizes "$SCOPE_ROOT" "$HUMAN_ATTEMPT" "$HUMAN_RESULT" \
   && grep -qF 'Disposition: `dismiss-scope` (human choice)' "$SCOPE_ROOT/docs/design/0999-scope.md" \
   && [ "$(grep -c '^## Scope decisions$' "$SCOPE_ROOT/docs/design/0999-scope.md")" = 1 ]; then
  ok "scope routing recovers after its tracked copy and before transition publication"
else bad "scope routing recovers after its tracked copy and before transition publication"; fi

(
  cd "$SCOPE_ROOT" || exit 1
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm dismissed
  git switch -qc feature/accepted-concern-scope
) || exit 1
printf 'mixed\n' >> "$SCOPE_ROOT/product.txt"
MIXED_TREE=$(CLAUDE_PROJECT_DIR="$SCOPE_ROOT" "$SCOPE_ROOT/core/scripts/tree-digest.sh")
MIXED_SERIES=$(review_series_ensure "$SCOPE_ROOT" feature/accepted-concern-scope 3 invariant-reviewer 0999-t2 2>/dev/null) || MIXED_SERIES=""
MIXED_ATTEMPT=$(review_attempt_start "$SCOPE_ROOT" "$MIXED_SERIES" codex mixed-reviewer scope-session \
  "$MIXED_TREE" feature/accepted-concern-scope 0999-t2 "$SCOPE_ROOT/.deliver/snapshot.txt" - 2>/dev/null) || MIXED_ATTEMPT=""
printf '%s\n' '[CONCERN] Human may accept this claim risk' '[SCOPE] Follow-up remains outside the task' 'VERDICT: findings' > "$FIX/mixed.md"
review_attempt_complete "$SCOPE_ROOT" "$MIXED_ATTEMPT" completed "$FIX/mixed.md" >/dev/null 2>&1
review_resolution_record "$SCOPE_ROOT" "$MIXED_ATTEMPT" accept-concerns+route-scope codex:user-message "$MIXED_TREE" >/dev/null 2>&1
review_scope_apply "$SCOPE_ROOT" "$MIXED_ATTEMPT" route-scope >/dev/null 2>&1
MIXED_RESULT=$(CLAUDE_PROJECT_DIR="$SCOPE_ROOT" "$SCOPE_ROOT/core/scripts/tree-digest.sh")
if review_attempt_authorizes "$SCOPE_ROOT" "$MIXED_ATTEMPT" "$MIXED_RESULT" \
   && grep -qF '[SCOPE] Follow-up remains outside the task' "$SCOPE_ROOT/docs/design/0999-scope.md"; then
  ok "accepted concerns plus routed scope authorize through one human gate without re-review"
else bad "accepted concerns plus routed scope authorize through one human gate without re-review"; fi
MIXED_ID=$(review_attempt_pr_resolution_id "$SCOPE_ROOT" "$MIXED_ATTEMPT" 2>/dev/null) || MIXED_ID=""
MIXED_SECTION=$(review_pr_resolutions_render "$SCOPE_ROOT" feature/accepted-concern-scope "$MIXED_SERIES" "${MIXED_ATTEMPT##*/}" 2>/dev/null) || MIXED_SECTION=""
printf '%s\n' "$MIXED_SECTION" > "$FIX/mixed-section.md"
if grep -qF '[CONCERN] Human may accept this claim risk' "$FIX/mixed-section.md" \
   && grep -qF '[SCOPE] Follow-up remains outside the task' "$FIX/mixed-section.md" \
   && grep -qF 'Review-Choice: accept-concerns+route-scope' "$FIX/mixed-section.md" \
   && review_pr_resolution_section_validate "$FIX/mixed-section.md" "$MIXED_ID"; then
  ok "a mixed human resolution retains both finding classes and the combined choice"
else bad "a mixed human resolution retains both finding classes and the combined choice"; fi

(
  cd "$SCOPE_ROOT" || exit 1
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm mixed
  perl -pi -e 's/^status: approved$/status: draft/' docs/design/0999-scope.md
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm draft
  git switch -qc feature/draft-scope
) || exit 1
printf 'draft change\n' >> "$SCOPE_ROOT/product.txt"
printf '\nDraft review delta.\n' >> "$SCOPE_ROOT/docs/design/0999-scope.md"
DRAFT_TREE=$(CLAUDE_PROJECT_DIR="$SCOPE_ROOT" "$SCOPE_ROOT/core/scripts/tree-digest.sh")
DRAFT_SERIES=$(review_series_ensure "$SCOPE_ROOT" feature/draft-scope 3 invariant-reviewer nd/draft-design-real 2>/dev/null) || DRAFT_SERIES=""
DRAFT_ATTEMPT=$(review_attempt_start "$SCOPE_ROOT" "$DRAFT_SERIES" codex draft-scope-reviewer scope-session \
  "$DRAFT_TREE" feature/draft-scope nd/draft-design-real "$SCOPE_ROOT/.deliver/snapshot.txt" - 2>/dev/null) || DRAFT_ATTEMPT=""
printf '%s\n' '[SCOPE] Keep this follow-up with the mutable draft' 'VERDICT: findings' > "$FIX/draft-scope.md"
review_attempt_complete "$SCOPE_ROOT" "$DRAFT_ATTEMPT" completed "$FIX/draft-scope.md" >/dev/null 2>&1
review_resolution_record "$SCOPE_ROOT" "$DRAFT_ATTEMPT" route-scope human:choice "$DRAFT_TREE" >/dev/null 2>&1
if review_scope_apply "$SCOPE_ROOT" "$DRAFT_ATTEMPT" route-scope \
   && grep -qF '[SCOPE] Keep this follow-up with the mutable draft' "$SCOPE_ROOT/docs/design/0999-scope.md" \
   && [ "$(jq -r '.designPath' "$(review_series_dir "$SCOPE_ROOT" "$DRAFT_SERIES")/series.json" 2>/dev/null)" = docs/design/0999-scope.md ]; then
  ok "a real non-delivery design review binds and routes into its mutable draft"
else bad "a real non-delivery design review binds and routes into its mutable draft"; fi
rm -rf "$SCOPE_ROOT"

MIXED_HARNESS=$(mktemp -d)
mkdir -p "$MIXED_HARNESS/core/scripts" "$MIXED_HARNESS/.github/workflows" \
  "$MIXED_HARNESS/docs/reference" "$MIXED_HARNESS/.deliver"
cp "$ROOT/core/scripts/tree-digest.sh" "$MIXED_HARNESS/core/scripts/tree-digest.sh"
printf '.deliver/\n' > "$MIXED_HARNESS/.gitignore"
printf '# Harness backlog\n' > "$MIXED_HARNESS/core/BACKLOG.md"
printf 'old workflow\n' > "$MIXED_HARNESS/.github/workflows/pr.yml"
printf 'old testing contract\n' > "$MIXED_HARNESS/docs/reference/testing.md"
printf 'snapshot\n' > "$MIXED_HARNESS/.deliver/snapshot.txt"
(
  cd "$MIXED_HARNESS" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git switch -qc feature/mixed-harness
) || exit 1
printf 'new workflow\n' > "$MIXED_HARNESS/.github/workflows/pr.yml"
printf 'new testing contract\n' > "$MIXED_HARNESS/docs/reference/testing.md"
MIXED_TREE=$(CLAUDE_PROJECT_DIR="$MIXED_HARNESS" "$MIXED_HARNESS/core/scripts/tree-digest.sh")
MIXED_SERIES=$(review_series_ensure "$MIXED_HARNESS" feature/mixed-harness 3 invariant-reviewer mixed-harness 2>/dev/null) || MIXED_SERIES=""
MIXED_SERIES_JSON="$(review_series_dir "$MIXED_HARNESS" "$MIXED_SERIES")/series.json"
jq '.subjectKind="product" | del(.subjectClassifierVersion)' "$MIXED_SERIES_JSON" \
  > "$MIXED_SERIES_JSON.legacy" && mv "$MIXED_SERIES_JSON.legacy" "$MIXED_SERIES_JSON"
MIXED_REUSED=$(review_series_ensure "$MIXED_HARNESS" feature/mixed-harness 3 invariant-reviewer mixed-harness 2>/dev/null) || MIXED_REUSED=""
MIXED_ATTEMPT=$(review_attempt_start "$MIXED_HARNESS" "$MIXED_SERIES" codex mixed-reviewer mixed-session \
  "$MIXED_TREE" feature/mixed-harness mixed-harness "$MIXED_HARNESS/.deliver/snapshot.txt" - 2>/dev/null) || MIXED_ATTEMPT=""
printf '%s\n' '[SCOPE] Retain the mixed harness follow-up' 'VERDICT: findings' > "$FIX/mixed-harness.md"
review_attempt_complete "$MIXED_HARNESS" "$MIXED_ATTEMPT" completed "$FIX/mixed-harness.md" >/dev/null 2>&1
review_resolution_record "$MIXED_HARNESS" "$MIXED_ATTEMPT" route-scope human:choice "$MIXED_TREE" >/dev/null 2>&1
if review_scope_apply "$MIXED_HARNESS" "$MIXED_ATTEMPT" route-scope \
   && [ "$MIXED_REUSED" = "$MIXED_SERIES" ] \
   && jq -e '.from=="product" and .to=="harness"' \
      "$(review_series_dir "$MIXED_HARNESS" "$MIXED_SERIES")/subject-correction.json" >/dev/null 2>&1 \
   && grep -qF '[SCOPE] Retain the mixed harness follow-up' "$MIXED_HARNESS/core/BACKLOG.md"; then
  ok "mixed harness/testing changes correct an open legacy series without resetting its window"
else bad "mixed harness/testing changes correct an open legacy series without resetting its window"; fi
rm -rf "$MIXED_HARNESS"

DECLARED_HARNESS=$(mktemp -d)
mkdir -p "$DECLARED_HARNESS/core/scripts" "$DECLARED_HARNESS/docs/decisions" \
  "$DECLARED_HARNESS/.deliver"
cp "$ROOT/core/scripts/tree-digest.sh" "$DECLARED_HARNESS/core/scripts/tree-digest.sh"
printf '.deliver/\n' > "$DECLARED_HARNESS/.gitignore"
printf '# Harness backlog\n' > "$DECLARED_HARNESS/core/BACKLOG.md"
printf '# Decisions\n' > "$DECLARED_HARNESS/docs/decisions/README.md"
(
  cd "$DECLARED_HARNESS" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git switch -qc feature/layered-verification
) || exit 1
printf '%s\n' '---' 'type: decision' 'status: proposed' 'subject: harness' \
  'date: 2026-09-09' '---' '# Layered local verification' \
  > "$DECLARED_HARNESS/docs/decisions/0052-layered-local-verification.md"
printf 'snapshot\n' > "$DECLARED_HARNESS/.deliver/snapshot.txt"
DECLARED_TREE=$(CLAUDE_PROJECT_DIR="$DECLARED_HARNESS" \
  "$DECLARED_HARNESS/core/scripts/tree-digest.sh")
DECLARED_SERIES=$(review_series_ensure "$DECLARED_HARNESS" feature/layered-verification 3 \
  invariant-reviewer harness-adr 2>/dev/null) || DECLARED_SERIES=""
DECLARED_ATTEMPT=$(review_attempt_start "$DECLARED_HARNESS" "$DECLARED_SERIES" codex \
  harness-adr-reviewer harness-adr-session "$DECLARED_TREE" feature/layered-verification \
  harness-adr "$DECLARED_HARNESS/.deliver/snapshot.txt" - 2>/dev/null) || DECLARED_ATTEMPT=""
printf '%s\n' '[SCOPE] Retain the declared harness follow-up' 'VERDICT: findings' \
  > "$FIX/declared-harness.md"
review_attempt_complete "$DECLARED_HARNESS" "$DECLARED_ATTEMPT" completed \
  "$FIX/declared-harness.md" >/dev/null 2>&1
review_resolution_record "$DECLARED_HARNESS" "$DECLARED_ATTEMPT" route-scope human:choice \
  "$DECLARED_TREE" >/dev/null 2>&1
if [ "$(jq -r '.subjectKind' "$(review_series_dir "$DECLARED_HARNESS" "$DECLARED_SERIES")/series.json" 2>/dev/null)" = harness ] \
   && review_scope_apply "$DECLARED_HARNESS" "$DECLARED_ATTEMPT" route-scope \
   && grep -qF '[SCOPE] Retain the declared harness follow-up' \
      "$DECLARED_HARNESS/core/BACKLOG.md"; then
  ok "an explicitly declared harness ADR snapshots harness routing and keeps SCOPE in its backlog"
else bad "an explicitly declared harness ADR snapshots harness routing and keeps SCOPE in its backlog"; fi
rm -rf "$DECLARED_HARNESS"

FROZEN=$(mktemp -d)
mkdir -p "$FROZEN/core/scripts" "$FROZEN/docs/design" "$FROZEN/.deliver"
cp "$ROOT/core/scripts/tree-digest.sh" "$FROZEN/core/scripts/tree-digest.sh"
cp "$ROOT/core/lib.sh" "$FROZEN/core/lib.sh"
cp "$ROOT/core/review-workflow.sh" "$FROZEN/core/review-workflow.sh"
cp "$ROOT/core/review-receipt.sh" "$FROZEN/core/review-receipt.sh"
cp "$ROOT/core/round-ledger.sh" "$FROZEN/core/round-ledger.sh"
cp "$ROOT/core/task-ledger.sh" "$FROZEN/core/task-ledger.sh"
cp "$ROOT/core/accepted-rounds.sh" "$FROZEN/core/accepted-rounds.sh"
printf '.deliver/\n' > "$FROZEN/.gitignore"
printf '# Harness backlog\n' > "$FROZEN/core/BACKLOG.md"
printf '%s\n' '---' 'type: design' 'status: frozen' 'last-verified: 2026-09-08' '---' \
  '# Frozen product design' '## 7. Tasks' '- [ ] **1.** Product task.' '- [ ] **2.** Product task.' \
  '- [ ] **3.** Product task.' \
  > "$FROZEN/docs/design/0998-frozen.md"
printf 'product\n' > "$FROZEN/product.txt"
(
  cd "$FROZEN" || exit 1
  git init -q -b main .
  git remote add origin git@github.com:acme/example.git
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git switch -qc feature/frozen-scope
) || exit 1
printf 'changed\n' >> "$FROZEN/product.txt"
printf 'snapshot\n' > "$FROZEN/.deliver/snapshot.txt"
FROZEN_TREE=$(CLAUDE_PROJECT_DIR="$FROZEN" "$FROZEN/core/scripts/tree-digest.sh")
FROZEN_SERIES=$(review_series_ensure "$FROZEN" feature/frozen-scope 4 invariant-reviewer 0998-t1 2>/dev/null)
FROZEN_ATTEMPT=$(review_attempt_start "$FROZEN" "$FROZEN_SERIES" codex frozen-scope-reviewer scope-session \
  "$FROZEN_TREE" feature/frozen-scope 0998-t1 "$FROZEN/.deliver/snapshot.txt" - 2>/dev/null)
printf '%s\n' '[SCOPE] Track this product gap externally' 'VERDICT: findings' > "$FIX/frozen-scope.md"
review_attempt_complete "$FROZEN" "$FROZEN_ATTEMPT" completed "$FIX/frozen-scope.md" >/dev/null 2>&1
review_resolution_record "$FROZEN" "$FROZEN_ATTEMPT" route-scope human:choice "$FROZEN_TREE" >/dev/null 2>&1
review_scope_apply "$FROZEN" "$FROZEN_ATTEMPT" route-scope >/dev/null 2>&1 || true
FROZEN_PENDING_DASH=$(CLAUDE_PROJECT_DIR="$FROZEN" node "$ROOT/core/scripts/review-dashboard.mjs" --stdout 2>/dev/null) || FROZEN_PENDING_DASH=""
if printf '%s' "$FROZEN_PENDING_DASH" | jq -e --arg series "$FROZEN_SERIES" '
  ([.tasks[].rounds[] | select(.seriesId==$series and .accepted=="unresolved" and
    .humanResolution=="route-scope" and .resolutionSeconds==null)] | length) == 1 and
  .summary.humanResolutions == 0
' >/dev/null 2>&1; then
  ok "dashboard keeps an issue-routed scope choice pending until its destination exists"
else bad "dashboard keeps an issue-routed scope choice pending until its destination exists"; fi
if [ "$(jq -r '.status' "$FROZEN_ATTEMPT/scope-transition.json" 2>/dev/null)" = human-route-required ] \
   && ! review_scope_issue_record "$FROZEN" "$FROZEN_ATTEMPT" https://github.com/other/repo/issues/1 human:issue >/dev/null 2>&1 \
   && review_scope_issue_record "$FROZEN" "$FROZEN_ATTEMPT" https://github.com/acme/example/issues/17 human:issue \
   && review_attempt_authorizes "$FROZEN" "$FROZEN_ATTEMPT" "$FROZEN_TREE"; then
  ok "frozen product scope requires and records a human-authorized issue destination"
else bad "frozen product scope requires and records a human-authorized issue destination"; fi
mkdir -p "$FROZEN/core"
cp "$ROOT/core/review-workflow.sh" "$FROZEN/core/review-workflow.sh"
cp "$ROOT/core/review-receipt.sh" "$FROZEN/core/review-receipt.sh"
cp "$ROOT/core/round-ledger.sh" "$FROZEN/core/round-ledger.sh"
FROZEN_ISSUE_ID=$(jq -r '.prResolutionId // empty' "$FROZEN_ATTEMPT/scope-destination.json" 2>/dev/null)
git -C "$FROZEN" add -A
FROZEN_PREPARATION=$(CLAUDE_PROJECT_DIR="$FROZEN" "$ROOT/core/scripts/review-finish.sh") || FROZEN_PREPARATION=""
FROZEN_PREPARATION_ID=$(printf '%s\n' "$FROZEN_PREPARATION" | sed -n 's/^Review-Preparation: //p')
printf 'retain issue route\n' > "$FIX/issue-commit-missing.txt"
printf 'retain issue route\n\nReview-Preparation: %s\nReview-Resolution: %s\n' \
  "$FROZEN_PREPARATION_ID" "$FROZEN_ISSUE_ID" > "$FIX/issue-commit-valid.txt"
(
  cd "$FROZEN" || exit 1
  "$ROOT/integrations/git/commit-msg" "$FIX/issue-commit-missing.txt"
) >/dev/null 2>&1
FROZEN_MISSING_TRAILER_RC=$?
(
  cd "$FROZEN" || exit 1
  "$ROOT/integrations/git/commit-msg" "$FIX/issue-commit-valid.txt"
) >/dev/null 2>&1
FROZEN_VALID_TRAILER_RC=$?
FROZEN_ISSUE_BASE=$(git -C "$FROZEN" rev-parse HEAD)
(
  cd "$FROZEN" || exit 1
  git -c user.email=t@t -c user.name=t commit -qm 'retain routed scope' \
    -m "Review-Preparation: $FROZEN_PREPARATION_ID" -m "Review-Resolution: $FROZEN_ISSUE_ID"
) || exit 1
FROZEN_ISSUE_HANDOFF=$(CLAUDE_PROJECT_DIR="$FROZEN" "$ROOT/core/scripts/review-pr-summary.sh") || FROZEN_ISSUE_HANDOFF=""
printf '%s\n' "$FROZEN_ISSUE_HANDOFF" > "$FIX/issue-handoff.md"
(
  cd "$FROZEN" || exit 1
  git config core.hooksPath "$ROOT/integrations/git"
  git -c user.email=t@t -c user.name=t commit --amend -qm 'retain routed scope (amended)'
) >/dev/null 2>&1
FROZEN_AMEND_PRESERVED=$?
git -C "$FROZEN" config --unset core.hooksPath || exit 1
FROZEN_ISSUE_HEAD=$(git -C "$FROZEN" rev-parse HEAD)
FROZEN_ISSUE_HANDOFF=$(CLAUDE_PROJECT_DIR="$FROZEN" "$ROOT/core/scripts/review-pr-summary.sh") || FROZEN_ISSUE_HANDOFF=""
printf '%s\n' "$FROZEN_ISSUE_HANDOFF" > "$FIX/issue-handoff.md"
jq -n --arg body "$FROZEN_ISSUE_HANDOFF" --arg branch feature/frozen-scope --arg head "$FROZEN_ISSUE_HEAD" \
  '{pull_request:{body:$body,head:{ref:$branch,sha:$head}}}' > "$FIX/issue-event.json"
jq -n --arg branch feature/frozen-scope --arg head "$FROZEN_ISSUE_HEAD" \
  '{pull_request:{body:"",head:{ref:$branch,sha:$head}}}' > "$FIX/missing-handoff-event.json"
CLAUDE_PROJECT_DIR="$FROZEN" "$ROOT/core/scripts/review-pr-summary.sh" \
  --validate-event "$FIX/missing-handoff-event.json" "$FROZEN_ISSUE_BASE" >/dev/null 2>&1
FROZEN_MISSING_HANDOFF_RC=$?
printf '%s\nReview-Resolution: %064d\n' "$FROZEN_ISSUE_HANDOFF" 0 > "$FIX/mismatched-id-handoff.md"
jq -n --rawfile body "$FIX/mismatched-id-handoff.md" --arg branch feature/frozen-scope --arg head "$FROZEN_ISSUE_HEAD" \
  '{pull_request:{body:$body,head:{ref:$branch,sha:$head}}}' > "$FIX/mismatched-id-event.json"
CLAUDE_PROJECT_DIR="$FROZEN" "$ROOT/core/scripts/review-pr-summary.sh" \
  --validate-event "$FIX/mismatched-id-event.json" "$FROZEN_ISSUE_BASE" >/dev/null 2>&1
FROZEN_MISMATCHED_ID_RC=$?
FROZEN_ISSUE_NEXT=$(review_series_ensure "$FROZEN" feature/frozen-scope 4 invariant-reviewer 0998-t1 2>/dev/null) || FROZEN_ISSUE_NEXT=""
if grep -qF 'Review-Destination: https://github.com/acme/example/issues/17' "$FIX/issue-handoff.md" \
   && printf '%s' "$FROZEN_PREPARATION_ID" | grep -Eq '^[0-9a-f]{64}$' \
   && review_pr_handoff_validate "$FIX/issue-handoff.md" feature/frozen-scope "" "$FROZEN_ISSUE_HEAD" \
   && CLAUDE_PROJECT_DIR="$FROZEN" "$ROOT/core/scripts/review-pr-summary.sh" \
      --validate-event "$FIX/issue-event.json" "$FROZEN_ISSUE_BASE" \
   && [ "$(jq -r '.reason' "$(review_series_dir "$FROZEN" "$FROZEN_SERIES")/closed.json" 2>/dev/null)" = resolved ] \
   && [ "$FROZEN_MISSING_TRAILER_RC" -ne 0 ] && [ "$FROZEN_VALID_TRAILER_RC" = 0 ] \
   && [ "$FROZEN_AMEND_PRESERVED" = 0 ] \
   && [ "$(git -C "$FROZEN" log -1 --format=%B | grep -cFx "Review-Preparation: $FROZEN_PREPARATION_ID")" = 1 ] \
   && [ "$(git -C "$FROZEN" log -1 --format=%B | grep -cFx "Review-Resolution: $FROZEN_ISSUE_ID")" = 1 ] \
   && [ "$FROZEN_MISSING_HANDOFF_RC" -ne 0 ] \
   && [ "$FROZEN_MISMATCHED_ID_RC" -ne 0 ] \
   && [ -n "$FROZEN_ISSUE_NEXT" ] && [ "$FROZEN_ISSUE_NEXT" != "$FROZEN_SERIES" ]; then
  ok "an ad-hoc handoff is mandatory, exact-HEAD-bound, and survives a message-only amend"
else bad "a non-delivery handoff is mandatory, incarnation-bound, and survives commit amend" \
  "handoff=${FROZEN_ISSUE_HANDOFF:-empty}; old=$FROZEN_SERIES; new=${FROZEN_ISSUE_NEXT:-empty}"; fi

printf 'unreviewed follow-up\n' >> "$FROZEN/product.txt"
mkdir -p "$FIX/no-hooks"
(
  cd "$FROZEN" || exit 1
  git add -A
  git -c core.hooksPath="$FIX/no-hooks" -c user.email=t@t -c user.name=t commit -qm 'unreviewed follow-up'
) || exit 1
FROZEN_UNREVIEWED_HEAD=$(git -C "$FROZEN" rev-parse HEAD)
jq -n --arg body "$FROZEN_ISSUE_HANDOFF" --arg branch feature/frozen-scope --arg head "$FROZEN_UNREVIEWED_HEAD" \
  '{pull_request:{body:$body,head:{ref:$branch,sha:$head}}}' > "$FIX/unreviewed-head-event.json"
if ! CLAUDE_PROJECT_DIR="$FROZEN" "$ROOT/core/scripts/review-pr-summary.sh" >/dev/null 2>&1 \
   && ! CLAUDE_PROJECT_DIR="$FROZEN" "$ROOT/core/scripts/review-pr-summary.sh" \
      --validate-event "$FIX/unreviewed-head-event.json" "$FROZEN_ISSUE_BASE" >/dev/null 2>&1; then
  ok "a later unreviewed commit cannot reuse an earlier handoff"
else bad "a later unreviewed commit cannot reuse an earlier handoff"; fi

(
  cd "$FROZEN" || exit 1
  git add -A
  git -c user.email=t@t -c user.name=t commit --allow-empty -qm scope-one
  git switch -qc feature/frozen-blocker-scope
) || exit 1
printf 'second change\n' >> "$FROZEN/product.txt"
BLOCK_SCOPE_TREE=$(CLAUDE_PROJECT_DIR="$FROZEN" "$FROZEN/core/scripts/tree-digest.sh")
BLOCK_SCOPE_SERIES=$(review_series_ensure "$FROZEN" feature/frozen-blocker-scope 4 invariant-reviewer 0998-t2 2>/dev/null)
BLOCK_SCOPE_ATTEMPT=$(review_attempt_start "$FROZEN" "$BLOCK_SCOPE_SERIES" codex frozen-blocker-reviewer scope-session \
  "$BLOCK_SCOPE_TREE" feature/frozen-blocker-scope 0998-t2 "$FROZEN/.deliver/snapshot.txt" - 2>/dev/null)
printf '%s\n' '[BLOCKING] Fix the product defect' '[CONCERN] Fix this claim in the same batch' \
  '[SCOPE] Track the adjacent product gap' 'VERDICT: findings' > "$FIX/frozen-all.md"
review_attempt_complete "$FROZEN" "$BLOCK_SCOPE_ATTEMPT" completed "$FIX/frozen-all.md" >/dev/null 2>&1
review_scope_apply "$FROZEN" "$BLOCK_SCOPE_ATTEMPT" route-scope >/dev/null 2>&1 || true
BLOCK_SCOPE_RECORDED=0
if BLOCK_SCOPE_RECORD_OUTPUT=$(review_scope_issue_record "$FROZEN" "$BLOCK_SCOPE_ATTEMPT" \
   https://github.com/acme/example/issues/18 human:issue 2>&1); then
  BLOCK_SCOPE_RECORDED=1
else
  bad "blocker plus concern plus scope records its required issue destination" "$BLOCK_SCOPE_RECORD_OUTPUT"
fi
if [ "$BLOCK_SCOPE_RECORDED" = 1 ] \
   && review_attempt_start "$FROZEN" "$BLOCK_SCOPE_SERIES" codex premature-reviewer scope-session \
   "$BLOCK_SCOPE_TREE" feature/frozen-blocker-scope 0998-t2 "$FROZEN/.deliver/snapshot.txt" - >/dev/null 2>&1; then
  bad "blocker plus concern plus scope cannot re-review before the correction batch"
else
  printf 'fixed blocker and concern\n' >> "$FROZEN/product.txt"
  BLOCK_SCOPE_FIXED=$(CLAUDE_PROJECT_DIR="$FROZEN" "$FROZEN/core/scripts/tree-digest.sh")
  if review_attempt_start "$FROZEN" "$BLOCK_SCOPE_SERIES" codex corrected-reviewer scope-session \
     "$BLOCK_SCOPE_FIXED" feature/frozen-blocker-scope 0998-t2 "$FROZEN/.deliver/snapshot.txt" - >/dev/null 2>&1; then
    ok "blocker plus concern plus scope routes once and admits one review after the shared fix batch"
  else bad "blocker plus concern plus scope routes once and admits one review after the shared fix batch"; fi
fi
(
  cd "$FROZEN" || exit 1
  git add -A
  git -c user.email=t@t -c user.name=t commit --allow-empty -qm scope-two
  git switch -qc feature/frozen-concern-scope
) || exit 1
printf 'third change\n' >> "$FROZEN/product.txt"
CONCERN_SCOPE_TREE=$(CLAUDE_PROJECT_DIR="$FROZEN" "$FROZEN/core/scripts/tree-digest.sh")
CONCERN_SCOPE_SERIES=$(review_series_ensure "$FROZEN" feature/frozen-concern-scope 4 invariant-reviewer 0998-t3 2>/dev/null)
CONCERN_SCOPE_ATTEMPT=$(review_attempt_start "$FROZEN" "$CONCERN_SCOPE_SERIES" codex concern-scope-reviewer scope-session \
  "$CONCERN_SCOPE_TREE" feature/frozen-concern-scope 0998-t3 "$FROZEN/.deliver/snapshot.txt" - 2>/dev/null)
printf '%s\n' '[CONCERN] Correct this claim' '[SCOPE] Track this separate product gap' 'VERDICT: findings' \
  > "$FIX/frozen-concern-scope.md"
review_attempt_complete "$FROZEN" "$CONCERN_SCOPE_ATTEMPT" completed "$FIX/frozen-concern-scope.md" >/dev/null 2>&1
review_resolution_record "$FROZEN" "$CONCERN_SCOPE_ATTEMPT" fix-concerns+route-scope human:choice "$CONCERN_SCOPE_TREE" >/dev/null 2>&1
review_scope_apply "$FROZEN" "$CONCERN_SCOPE_ATTEMPT" route-scope >/dev/null 2>&1 || true
review_scope_issue_record "$FROZEN" "$CONCERN_SCOPE_ATTEMPT" https://github.com/acme/example/issues/19 human:issue >/dev/null 2>&1
if review_attempt_start "$FROZEN" "$CONCERN_SCOPE_SERIES" codex premature-concern-reviewer scope-session \
   "$CONCERN_SCOPE_TREE" feature/frozen-concern-scope 0998-t3 "$FROZEN/.deliver/snapshot.txt" - >/dev/null 2>&1; then
  bad "concern plus scope cannot re-review before the chosen concern fix"
else
  printf 'fixed concern\n' >> "$FROZEN/product.txt"
  CONCERN_SCOPE_FIXED=$(CLAUDE_PROJECT_DIR="$FROZEN" "$FROZEN/core/scripts/tree-digest.sh")
  if review_attempt_start "$FROZEN" "$CONCERN_SCOPE_SERIES" codex fixed-concern-reviewer scope-session \
     "$CONCERN_SCOPE_FIXED" feature/frozen-concern-scope 0998-t3 "$FROZEN/.deliver/snapshot.txt" - >/dev/null 2>&1; then
    ok "concern plus scope routes once and reviews only after the human-chosen concern fix"
  else bad "concern plus scope routes once and reviews only after the human-chosen concern fix"; fi
fi

(
  cd "$FROZEN" || exit 1
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm scope-three
  git switch -qc feature/frozen-harness
) || exit 1
printf 'harness fix\n' > "$FROZEN/core/harness.sh"
printf '\nFrozen recovery delta.\n' >> "$FROZEN/docs/design/0998-frozen.md"
FROZEN_HARNESS_TREE=$(CLAUDE_PROJECT_DIR="$FROZEN" "$FROZEN/core/scripts/tree-digest.sh")
FROZEN_HARNESS_SERIES=$(review_series_ensure "$FROZEN" feature/frozen-harness 3 invariant-reviewer 0998-t4 2>/dev/null) || FROZEN_HARNESS_SERIES=""
FROZEN_HARNESS_ATTEMPT=$(review_attempt_start "$FROZEN" "$FROZEN_HARNESS_SERIES" codex frozen-harness-reviewer scope-session \
  "$FROZEN_HARNESS_TREE" feature/frozen-harness 0998-t4 "$FROZEN/.deliver/snapshot.txt" - 2>/dev/null) || FROZEN_HARNESS_ATTEMPT=""
printf '%s\n' '[SCOPE] Retain this adjacent harness repair' 'VERDICT: findings' > "$FIX/frozen-harness.md"
review_attempt_complete "$FROZEN" "$FROZEN_HARNESS_ATTEMPT" completed "$FIX/frozen-harness.md" >/dev/null 2>&1
review_resolution_record "$FROZEN" "$FROZEN_HARNESS_ATTEMPT" route-scope human:choice "$FROZEN_HARNESS_TREE" >/dev/null 2>&1
if review_scope_apply "$FROZEN" "$FROZEN_HARNESS_ATTEMPT" route-scope \
   && grep -qF '[SCOPE] Retain this adjacent harness repair' "$FROZEN/core/BACKLOG.md" \
   && [ "$(jq -r '.subjectKind' "$(review_series_dir "$FROZEN" "$FROZEN_HARNESS_SERIES")/series.json" 2>/dev/null)" = harness ]; then
  ok "frozen recovery excludes its lifecycle doc and routes a harness subject to the backlog"
else bad "frozen recovery excludes its lifecycle doc and routes a harness subject to the backlog"; fi

(
  cd "$FROZEN" || exit 1
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm frozen-harness
  git switch -qc feature/frozen-dismiss
) || exit 1
printf 'dismissed product scope\n' >> "$FROZEN/product.txt"
FROZEN_DISMISS_TREE=$(CLAUDE_PROJECT_DIR="$FROZEN" "$FROZEN/core/scripts/tree-digest.sh")
FROZEN_DISMISS_SERIES=$(review_series_ensure "$FROZEN" feature/frozen-dismiss 3 invariant-reviewer 0998-t5 2>/dev/null) || FROZEN_DISMISS_SERIES=""
FROZEN_DISMISS_ATTEMPT=$(review_attempt_start "$FROZEN" "$FROZEN_DISMISS_SERIES" codex frozen-dismiss-reviewer scope-session \
  "$FROZEN_DISMISS_TREE" feature/frozen-dismiss 0998-t5 "$FROZEN/.deliver/snapshot.txt" - 2>/dev/null) || FROZEN_DISMISS_ATTEMPT=""
printf '%s\n' '[SCOPE] Human rejects this product follow-up' 'Anchor: ADR-0051' \
  'Where: product.txt' 'Why: it is outside the task' 'Resolve: retain the dismissal in the PR' \
  'VERDICT: findings' > "$FIX/frozen-dismiss.md"
review_attempt_complete "$FROZEN" "$FROZEN_DISMISS_ATTEMPT" completed "$FIX/frozen-dismiss.md" >/dev/null 2>&1
review_resolution_record "$FROZEN" "$FROZEN_DISMISS_ATTEMPT" dismiss-scope human:choice "$FROZEN_DISMISS_TREE" >/dev/null 2>&1
review_scope_apply "$FROZEN" "$FROZEN_DISMISS_ATTEMPT" dismiss-scope >/dev/null 2>&1
FROZEN_RESOLUTION_ID=$(jq -r '.prResolutionId // empty' "$FROZEN_DISMISS_ATTEMPT/scope-transition.json" 2>/dev/null)
FROZEN_PR_SECTION=$(review_pr_resolutions_render "$FROZEN" feature/frozen-dismiss 2>/dev/null) || FROZEN_PR_SECTION=""
printf '%s\n' "$FROZEN_PR_SECTION" > "$FIX/pr-body.md"
if [ "$(jq -r '.status' "$FROZEN_DISMISS_ATTEMPT/scope-transition.json" 2>/dev/null)" = pr-required ] \
   && printf '%s' "$FROZEN_RESOLUTION_ID" | grep -Eq '^[0-9a-f]{64}$' \
   && review_attempt_authorizes "$FROZEN" "$FROZEN_DISMISS_ATTEMPT" "$FROZEN_DISMISS_TREE" \
   && grep -qF '[SCOPE] Human rejects this product follow-up' "$FIX/pr-body.md" \
   && grep -qF "Review-Resolution: $FROZEN_RESOLUTION_ID" "$FIX/pr-body.md" \
   && review_pr_resolution_section_validate "$FIX/pr-body.md" "$FROZEN_RESOLUTION_ID"; then
  ok "frozen product dismissal authorizes completion only with a generated PR resolution"
else bad "frozen product dismissal authorizes completion only with a generated PR resolution"; fi
FROZEN_DASH=$(CLAUDE_PROJECT_DIR="$FROZEN" node "$ROOT/core/scripts/review-dashboard.mjs" --stdout 2>/dev/null) || FROZEN_DASH=""
if printf '%s' "$FROZEN_DASH" | jq -e --arg series "$FROZEN_DISMISS_SERIES" --arg id "$FROZEN_RESOLUTION_ID" '
  [.tasks[].rounds[] | select(.seriesId==$series and .accepted=="human-resolved" and .prResolutionId==$id)] | length == 1
' >/dev/null 2>&1; then
  ok "dashboard counts a valid PR-required scope disposition as human-resolved"
else bad "dashboard counts a valid PR-required scope disposition as human-resolved"; fi
sed 's/Human rejects this product follow-up/Human rewrote this product follow-up/' \
  "$FIX/pr-body.md" > "$FIX/pr-body-tampered.md"
if ! review_pr_resolution_section_validate "$FIX/pr-body-tampered.md" "$FROZEN_RESOLUTION_ID"; then
  ok "PR resolution validation rejects altered retained finding text"
else bad "PR resolution validation rejects altered retained finding text"; fi

FROZEN_AFTER="$FIX/frozen-after.md"
sed 's/Product task\./Product task completed./' "$FROZEN/docs/design/0998-frozen.md" > "$FROZEN_AFTER"
CONSUME_OUTPUT="Review-Rounds: 1
Review-Resolution: $FROZEN_RESOLUTION_ID"
if review_consumption_intent_start "$FROZEN" "$FROZEN_DISMISS_ATTEMPT" complete:0998:5 \
     "$FROZEN/docs/design/0998-frozen.md" "$FROZEN_AFTER" "$CONSUME_OUTPUT" \
   && review_consumption_intent_start "$FROZEN" "$FROZEN_DISMISS_ATTEMPT" complete:0998:5 \
     "$FROZEN/docs/design/0998-frozen.md" "$FROZEN_AFTER" "$CONSUME_OUTPUT"; then
  mv "$FROZEN_AFTER" "$FROZEN/docs/design/0998-frozen.md"
  RECOVERED_OUTPUT=$(review_consumption_recover "$FROZEN" "$FROZEN_DISMISS_ATTEMPT" complete:0998:5 \
    "$FROZEN/docs/design/0998-frozen.md" 2>/dev/null) || RECOVERED_OUTPUT=""
else
  RECOVERED_OUTPUT=""
fi
if [ "$RECOVERED_OUTPUT" = "$CONSUME_OUTPUT" ] \
   && [ "$(jq -r '.reason' "$(review_series_dir "$FROZEN" "$FROZEN_DISMISS_SERIES")/closed.json" 2>/dev/null)" = resolved ] \
   && [ "$(review_consumption_required_resolution_ids "$FROZEN" complete:0998:5 \
       "$FROZEN/docs/design/0998-frozen.md" 2>/dev/null)" = "$FROZEN_RESOLUTION_ID" ]; then
  ok "a prepublished consumption intent recovers after the tracked mutation and before series close"
else bad "a prepublished consumption intent recovers after the tracked mutation and before series close"; fi
(
  cd "$FROZEN" || exit 1
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm "task 5: retain dismissal" \
    -m "Review-Rounds: 1" -m "Review-Resolution: $FROZEN_RESOLUTION_ID"
) || exit 1
FROZEN_BASE=$(git -C "$FROZEN" rev-parse HEAD^)
jq -n --arg body "$FROZEN_PR_SECTION" --arg branch deliver/0998-code \
  --arg head "$(git -C "$FROZEN" rev-parse HEAD)" \
  '{pull_request:{body:$body,head:{ref:$branch,sha:$head}}}' > "$FIX/pr-event.json"
mkdir -p "$FROZEN/core"
cp "$ROOT/core/review-workflow.sh" "$FROZEN/core/review-workflow.sh"
if CLAUDE_PROJECT_DIR="$FROZEN" "$ROOT/core/scripts/review-pr-summary.sh" \
     --validate-event "$FIX/pr-event.json" "$FROZEN_BASE"; then
  ok "delivery CI validates every committed PR-only resolution against the generated PR body"
else bad "delivery CI validates every committed PR-only resolution against the generated PR body"; fi
rm -rf "$FROZEN"

CRASH_BIN="$FIX/crash-bin"
mkdir -p "$CRASH_BIN"
printf '%s\n' '#!/bin/sh' \
  'last=""' \
  'for arg do last="$arg"; done' \
  'if [ "$last" = "$REVIEW_FAIL_TARGET" ] && [ ! -e "$REVIEW_FAIL_SENTINEL" ]; then' \
  '  : > "$REVIEW_FAIL_SENTINEL"' \
  '  if [ "$REVIEW_FAIL_MODE" = after ]; then /bin/mv "$@" || exit $?; fi' \
  '  exit 91' \
  'fi' \
  'exec /bin/mv "$@"' > "$CRASH_BIN/mv"
chmod +x "$CRASH_BIN/mv"

consumer_crash_fixture() { # consumer_crash_fixture <consumer> <mode>
  local consumer="$1" mode="$2" repo branch key target args expected series attempt tree
  local first first_rc second second_rc third third_rc before_hash after_hash intents closes state_ok=0 first_open=0
  repo=$(mktemp -d)
  mkdir -p "$repo/core/scripts" "$repo/docs/design" "$repo/.deliver"
  cp "$ROOT/core/lib.sh" "$repo/core/lib.sh"
  cp "$ROOT/core/scripts/tree-digest.sh" "$repo/core/scripts/tree-digest.sh"
  printf '.deliver/\n' > "$repo/.gitignore"
  branch="feature/crash-$consumer-$mode"
  expected=""
  case "$consumer" in
    complete)
      printf '%s\n' '---' 'type: design' 'status: approved' 'last-verified: 2026-09-08' '---' \
        '## 7. Tasks' '### Code track' '- [ ] **1.** First task.' '- [ ] **2.** Later task.' \
        > "$repo/docs/design/0997-consumer-complete.md"
      key=0997-t1; target="$repo/docs/design/0997-consumer-complete.md"; args='0997 1'
      expected='Review-Rounds: 1'
      ;;
    freeze)
      printf '%s\n' '---' 'type: design' 'status: approved' 'last-verified: 2026-09-08' '---' \
        '## 7. Tasks' '### Code track' '- [x] **1.** Finished task.' \
        > "$repo/docs/design/0996-consumer-freeze.md"
      printf '%s\n' '---' 'type: plan' 'status: living' 'last-verified: 2026-09-08' '---' \
        '### M8 — Consumer recovery' '' '| Slug | Initiative | Depends | Design |' \
        '|---|---|---|---|' '| `consumer-freeze` | Freeze recovery | — | [0996](./design/0996-consumer-freeze.md) |' \
        '' '**Done when:** recovery is durable.' > "$repo/docs/roadmap.md"
      key=0996-finalize; target="$repo/docs/design/0996-consumer-freeze.md"; args=0996
      ;;
    claim)
      cp "$ROOT/core/review-workflow.sh" "$repo/core/review-workflow.sh"
      cp "$ROOT/core/review-receipt.sh" "$repo/core/review-receipt.sh"
      cp "$ROOT/core/round-ledger.sh" "$repo/core/round-ledger.sh"
      cp "$ROOT/core/task-ledger.sh" "$repo/core/task-ledger.sh"
      cp "$ROOT/core/accepted-rounds.sh" "$repo/core/accepted-rounds.sh"
      printf '%s\n' '---' 'type: design' 'status: draft' 'last-verified: 2026-09-08' '---' \
        '# Claim fixture' > "$repo/docs/design/0995-consumer-claim.md"
      printf '%s\n' '---' 'type: plan' 'status: living' 'last-verified: 2026-09-08' '---' \
        '### M8 — Consumer recovery' '' '| Slug | Initiative | Depends | Design |' \
        '|---|---|---|---|' '| `consumer-claim` | Claim recovery | — | — |' \
        '' '**Done when:** recovery is durable.' > "$repo/docs/roadmap.md"
      key=nd/consumer-claim; target="$repo/docs/roadmap.md"; args='consumer-claim 0995'
      ;;
    *) rm -rf "$repo"; return 1 ;;
  esac
  (
    cd "$repo" || exit 1
    git init -q -b main .
    git add -A
    git -c user.email=t@t -c user.name=t commit -qm init
    git switch -qc "$branch"
  ) || { rm -rf "$repo"; return 1; }
  printf 'snapshot\n' > "$repo/.deliver/snapshot.txt"
  tree=$(CLAUDE_PROJECT_DIR="$repo" "$repo/core/scripts/tree-digest.sh") || { rm -rf "$repo"; return 1; }
  series=$(review_series_ensure "$repo" "$branch" 3 invariant-reviewer "$key" 2>/dev/null) || {
    rm -rf "$repo"; return 1;
  }
  attempt=$(review_attempt_start "$repo" "$series" codex "$consumer-$mode-reviewer" session \
    "$tree" "$branch" "$key" "$repo/.deliver/snapshot.txt" - 2>/dev/null) || {
    rm -rf "$repo"; return 1;
  }
  printf 'VERDICT: clean — transition approved.\n' > "$repo/.deliver/clean.md"
  review_attempt_complete "$repo" "$attempt" completed "$repo/.deliver/clean.md" >/dev/null 2>&1 || {
    rm -rf "$repo"; return 1;
  }
  before_hash=$(review_workflow_file_hash "$target") || { rm -rf "$repo"; return 1; }
  # The arguments are fixed fixture words; intentional splitting mirrors direct CLI use.
  first=$(CLAUDE_PROJECT_DIR="$repo" REVIEW_FAIL_TARGET="$target" REVIEW_FAIL_MODE="$mode" \
    REVIEW_FAIL_SENTINEL="$repo/.deliver/fail.once" PATH="$CRASH_BIN:$PATH" \
    "$ROOT/core/scripts/$consumer.sh" $args 2>"$repo/.deliver/first.err")
  first_rc=$?
  [ ! -e "$(review_series_dir "$repo" "$series")/closed.json" ] && first_open=1
  if [ "$mode" = before ]; then
    [ "$(review_workflow_file_hash "$target" 2>/dev/null)" = "$before_hash" ] && state_ok=1
  else
    cmp -s "$target" "$attempt/consumption-intent/after" && state_ok=1
  fi
  second=$(CLAUDE_PROJECT_DIR="$repo" "$ROOT/core/scripts/$consumer.sh" $args 2>"$repo/.deliver/second.err")
  second_rc=$?
  after_hash=$(review_workflow_file_hash "$target" 2>/dev/null || true)
  third=$(CLAUDE_PROJECT_DIR="$repo" "$ROOT/core/scripts/$consumer.sh" $args 2>"$repo/.deliver/third.err")
  third_rc=$?
  intents=$(find "$(review_series_dir "$repo" "$series")" -name intent.json -path '*/consumption-intent/*' -type f | wc -l | tr -d ' ')
  closes=$(find "$(review_series_dir "$repo" "$series")" -name closed.json -type f | wc -l | tr -d ' ')
  if [ "$first_rc" -ne 0 ] && [ -z "$first" ] && [ "$state_ok" = 1 ] \
     && [ -f "$attempt/consumption-intent/intent.json" ] && [ "$first_open" = 1 ] \
     && [ "$second_rc" = 0 ] && [ "$second" = "$expected" ] \
     && cmp -s "$target" "$attempt/consumption-intent/after" \
     && [ "$third_rc" = 0 ] && [ "$third" = "$expected" ] \
     && [ "$(review_workflow_file_hash "$target" 2>/dev/null)" = "$after_hash" ] \
     && [ "$intents" = 1 ] && [ "$closes" = 1 ]; then
    ok "$consumer recovers exactly once when replacement fails $mode the target mutation"
  else
    bad "$consumer recovers exactly once when replacement fails $mode the target mutation" \
      "rc=$first_rc/$second_rc/$third_rc output=$first|$second|$third state=$state_ok intents=$intents closes=$closes err=$(tr '\n' ' ' < "$repo/.deliver/first.err")"
  fi
  rm -rf "$repo"
}

for consumer in complete freeze claim; do
  consumer_crash_fixture "$consumer" before
  consumer_crash_fixture "$consumer" after
done

HANDOFF_ROOT=$(mktemp -d)
mkdir -p "$HANDOFF_ROOT/core/scripts"
cp "$ROOT/core/scripts/tree-digest.sh" "$HANDOFF_ROOT/core/scripts/tree-digest.sh"
cp "$ROOT/core/lib.sh" "$HANDOFF_ROOT/core/lib.sh"
cp "$ROOT/core/review-workflow.sh" "$HANDOFF_ROOT/core/review-workflow.sh"
cp "$ROOT/core/review-receipt.sh" "$HANDOFF_ROOT/core/review-receipt.sh"
cp "$ROOT/core/round-ledger.sh" "$HANDOFF_ROOT/core/round-ledger.sh"
cp "$ROOT/core/task-ledger.sh" "$HANDOFF_ROOT/core/task-ledger.sh"
cp "$ROOT/core/accepted-rounds.sh" "$HANDOFF_ROOT/core/accepted-rounds.sh"
printf '.deliver/\n' > "$HANDOFF_ROOT/.gitignore"
printf 'handoff\n' > "$HANDOFF_ROOT/subject.txt"
(
  cd "$HANDOFF_ROOT" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git switch -qc feature/take-over
) || exit 1
# At a real one-attempt ceiling, no window writer may skip semantic disposition.
for WINDOW_OUTCOME in concern scope concern+scope blocking blocking+scope ambiguous; do
  git -C "$HANDOFF_ROOT" switch -qc "feature/window-$WINDOW_OUTCOME" || exit 1
  WINDOW_KEY="nd/window-$WINDOW_OUTCOME"
  WINDOW_TREE=$(CLAUDE_PROJECT_DIR="$HANDOFF_ROOT" "$HANDOFF_ROOT/core/scripts/tree-digest.sh")
  WINDOW_SERIES=$(review_series_ensure "$HANDOFF_ROOT" "feature/window-$WINDOW_OUTCOME" 1 invariant-reviewer "$WINDOW_KEY") || exit 1
  printf 'readiness\n' > "$FIX/window-snapshot.txt"
  WINDOW_ATTEMPT=$(review_attempt_start "$HANDOFF_ROOT" "$WINDOW_SERIES" codex "window-$WINDOW_OUTCOME" session \
    "$WINDOW_TREE" "feature/window-$WINDOW_OUTCOME" "$WINDOW_KEY" "$FIX/window-snapshot.txt" -) || exit 1
  case "$WINDOW_OUTCOME" in
    concern) printf '[CONCERN] Narrow the claim\n' ;;
    scope) printf '[SCOPE] Route the future work\n' ;;
    concern+scope) printf '[CONCERN] Narrow the claim\n[SCOPE] Route the future work\n' ;;
    blocking) printf '[BLOCKING] Correct the unsafe behavior\n' ;;
    blocking+scope) printf '[BLOCKING] Correct the unsafe behavior\n[SCOPE] Route the future work\n' ;;
    ambiguous) printf 'Review ended without a verdict.\n' ;;
  esac > "$FIX/window-result.md"
  review_attempt_complete "$HANDOFF_ROOT" "$WINDOW_ATTEMPT" completed "$FIX/window-result.md" || exit 1
  WINDOW_DENIED=0
  round_grant_add "$HANDOFF_ROOT" "$WINDOW_KEY" "$WINDOW_TREE" 1 1 "$ROUND_GRANT_LABEL" >/dev/null 2>&1 || WINDOW_DENIED=$((WINDOW_DENIED+1))
  round_grant_add_v2 "$HANDOFF_ROOT" "$WINDOW_KEY" "$WINDOW_TREE" 1 1 codex:session:window >/dev/null 2>&1 || WINDOW_DENIED=$((WINDOW_DENIED+1))
  review_series_handoff_record "$HANDOFF_ROOT" "$WINDOW_KEY" take-over human:test "$WINDOW_TREE" >/dev/null 2>&1 || WINDOW_DENIED=$((WINDOW_DENIED+1))
  review_series_handoff_record "$HANDOFF_ROOT" "$WINDOW_KEY" escalate-pr human:test "$WINDOW_TREE" >/dev/null 2>&1 || WINDOW_DENIED=$((WINDOW_DENIED+1))
  if [ "$WINDOW_DENIED" = 4 ] && [ "$(round_window "$HANDOFF_ROOT" "$WINDOW_KEY")" = 1 ] &&
     [ ! -e "$(review_series_dir "$HANDOFF_ROOT" "$WINDOW_SERIES")/closed.json" ]; then
    ok "all window writers preserve unresolved $WINDOW_OUTCOME at the ceiling"
  else bad "all window writers preserve unresolved $WINDOW_OUTCOME at the ceiling"; fi
  if [ "$WINDOW_OUTCOME" = ambiguous ]; then
    if review_resolution_record "$HANDOFF_ROOT" "$WINDOW_ATTEMPT" review-again human:test "$WINDOW_TREE" &&
       round_grant_add "$HANDOFF_ROOT" "$WINDOW_KEY" "$WINDOW_TREE" 1 1 "$ROUND_GRANT_LABEL"; then
      ok "a saved review-again decision permits window renewal for the unchanged tree"
    else bad "a saved review-again decision permits window renewal for the unchanged tree"; fi
  fi
done
git -C "$HANDOFF_ROOT" switch -q feature/take-over || exit 1
HANDOFF_TREE=$(CLAUDE_PROJECT_DIR="$HANDOFF_ROOT" "$HANDOFF_ROOT/core/scripts/tree-digest.sh")
TAKE_SERIES=$(review_series_ensure "$HANDOFF_ROOT" feature/take-over 3 invariant-reviewer nd/take-over 2>/dev/null) || TAKE_SERIES=""
if review_series_handoff_record "$HANDOFF_ROOT" nd/take-over take-over human:test "$HANDOFF_TREE" \
   && review_series_handoff_record "$HANDOFF_ROOT" nd/take-over take-over human:test "$HANDOFF_TREE" \
   && [ "$(jq -r '.authorizesCompletion' "$(review_series_dir "$HANDOFF_ROOT" "$TAKE_SERIES")/handoff.json")" = false ] \
   && [ "$(jq -r '.reason' "$(review_series_dir "$HANDOFF_ROOT" "$TAKE_SERIES")/closed.json")" = take-over ]; then
  ok "takeover is idempotent and closes the series without authorizing completion"
else bad "takeover is idempotent and closes the series without authorizing completion"; fi
(
  cd "$HANDOFF_ROOT" || exit 1
  git switch -qc feature/escalate-pr
) || exit 1
ESCALATE_TREE=$(CLAUDE_PROJECT_DIR="$HANDOFF_ROOT" "$HANDOFF_ROOT/core/scripts/tree-digest.sh")
ESCALATE_SERIES=$(review_series_ensure "$HANDOFF_ROOT" feature/escalate-pr 3 invariant-reviewer nd/escalate-pr 2>/dev/null) || ESCALATE_SERIES=""
if review_series_handoff_record "$HANDOFF_ROOT" nd/escalate-pr escalate-pr human:test "$ESCALATE_TREE" \
   && [ "$(jq -r '.authorizesCompletion' "$(review_series_dir "$HANDOFF_ROOT" "$ESCALATE_SERIES")/handoff.json")" = false ] \
   && [ "$(jq -r '.reason' "$(review_series_dir "$HANDOFF_ROOT" "$ESCALATE_SERIES")/closed.json")" = escalated ]; then
  ok "PR escalation closes the series as a non-authorizing handoff"
else bad "PR escalation closes the series as a non-authorizing handoff"; fi
(
  cd "$HANDOFF_ROOT" || exit 1
  git switch -qc feature/grant-window
) || exit 1
GRANT_TREE=$(CLAUDE_PROJECT_DIR="$HANDOFF_ROOT" "$HANDOFF_ROOT/core/scripts/tree-digest.sh")
GRANT_SERIES=$(review_series_ensure "$HANDOFF_ROOT" feature/grant-window 4 invariant-reviewer nd/grant-window 2>/dev/null) || GRANT_SERIES=""
if round_grant_add "$HANDOFF_ROOT" nd/grant-window "$GRANT_TREE" 4 4 "$ROUND_GRANT_LABEL" \
   && [ "$(round_window "$HANDOFF_ROOT" nd/grant-window 2>/dev/null)" = 8 ]; then
  ok "a renewal adds the series' snapshotted review window"
else bad "a renewal adds the series' snapshotted review window"; fi

(
  cd "$HANDOFF_ROOT" || exit 1
  git switch -qc propose/clean-finish
) || exit 1
cp "$ROOT/core/review-workflow.sh" "$HANDOFF_ROOT/core/review-workflow.sh"
cp "$ROOT/core/review-receipt.sh" "$HANDOFF_ROOT/core/review-receipt.sh"
cp "$ROOT/core/round-ledger.sh" "$HANDOFF_ROOT/core/round-ledger.sh"
printf 'snapshot\n' > "$HANDOFF_ROOT/snapshot.txt"
CLEAN_BLOCK_TREE=$(CLAUDE_PROJECT_DIR="$HANDOFF_ROOT" "$HANDOFF_ROOT/core/scripts/tree-digest.sh")
CLEAN_FINISH_SERIES=$(review_series_ensure "$HANDOFF_ROOT" propose/clean-finish 3 invariant-reviewer nd/clean-finish 2>/dev/null) || CLEAN_FINISH_SERIES=""
CLEAN_BLOCK_ATTEMPT=$(review_attempt_start "$HANDOFF_ROOT" "$CLEAN_FINISH_SERIES" codex clean-block-reviewer session \
  "$CLEAN_BLOCK_TREE" propose/clean-finish nd/clean-finish "$HANDOFF_ROOT/snapshot.txt" - 2>/dev/null) || CLEAN_BLOCK_ATTEMPT=""
printf '%s\n' '[BLOCKING] The first proposal claim is unsafe.' 'VERDICT: findings' > "$FIX/clean-block.md"
review_attempt_complete "$HANDOFF_ROOT" "$CLEAN_BLOCK_ATTEMPT" completed "$FIX/clean-block.md" >/dev/null 2>&1
printf 'blocker corrected\n' >> "$HANDOFF_ROOT/subject.txt"
CLEAN_FINISH_TREE=$(CLAUDE_PROJECT_DIR="$HANDOFF_ROOT" "$HANDOFF_ROOT/core/scripts/tree-digest.sh")
git -C "$HANDOFF_ROOT" add -A
CLEAN_FINISH_STAGED_TREE=$(CLAUDE_PROJECT_DIR="$HANDOFF_ROOT" "$HANDOFF_ROOT/core/scripts/tree-digest.sh")
git -C "$HANDOFF_ROOT" reset -q
if [ "$CLEAN_FINISH_TREE" = "$CLEAN_FINISH_STAGED_TREE" ]; then
  ok "staging identical bytes does not invalidate their review identity"
else bad "staging identical bytes does not invalidate their review identity"; fi
CLEAN_FINISH_ATTEMPT=$(review_attempt_start "$HANDOFF_ROOT" "$CLEAN_FINISH_SERIES" codex clean-finish-reviewer session \
  "$CLEAN_FINISH_TREE" propose/clean-finish nd/clean-finish "$HANDOFF_ROOT/snapshot.txt" - 2>/dev/null) || CLEAN_FINISH_ATTEMPT=""
printf 'VERDICT: clean — no findings.\n' > "$FIX/clean-finish.md"
review_attempt_complete "$HANDOFF_ROOT" "$CLEAN_FINISH_ATTEMPT" completed "$FIX/clean-finish.md" >/dev/null 2>&1
CLEAN_FINISH_PREP_ONE=$(git -C "$HANDOFF_ROOT" add -A && CLAUDE_PROJECT_DIR="$HANDOFF_ROOT" "$ROOT/core/scripts/review-finish.sh") || CLEAN_FINISH_PREP_ONE=""
CLEAN_FINISH_PREP_TWO=$(CLAUDE_PROJECT_DIR="$HANDOFF_ROOT" "$ROOT/core/scripts/review-finish.sh") || CLEAN_FINISH_PREP_TWO=""
CLEAN_FINISH_PREP_ID=$(printf '%s\n' "$CLEAN_FINISH_PREP_ONE" | sed -n 's/^Review-Preparation: //p')
(
  cd "$HANDOFF_ROOT" || exit 1
  git -c user.email=t@t -c user.name=t commit -qm 'route approved proposal' \
    -m "Review-Preparation: $CLEAN_FINISH_PREP_ID"
) || exit 1
CLEAN_FINISH_HEAD=$(git -C "$HANDOFF_ROOT" rev-parse HEAD)
CLEAN_HANDOFF_ONE=$(CLAUDE_PROJECT_DIR="$HANDOFF_ROOT" "$ROOT/core/scripts/review-pr-summary.sh") || CLEAN_HANDOFF_ONE=""
CLEAN_HANDOFF_TWO=$(CLAUDE_PROJECT_DIR="$HANDOFF_ROOT" "$ROOT/core/scripts/review-pr-summary.sh") || CLEAN_HANDOFF_TWO=""
printf '%s\n' "$CLEAN_HANDOFF_ONE" > "$FIX/clean-handoff.md"
CLEAN_BLOCK_ID=${CLEAN_BLOCK_ATTEMPT##*/}
CLEAN_FINAL_ID=${CLEAN_FINISH_ATTEMPT##*/}
awk -v start="<!-- review-attempt:$CLEAN_BLOCK_ID:start -->" \
    -v end="<!-- review-attempt:$CLEAN_BLOCK_ID:end -->" '
  $0==start {drop=1; next} $0==end {drop=0; next} !drop {print}
' "$FIX/clean-handoff.md" > "$FIX/clean-handoff-missing-attempt.md"
CLEAN_FINISH_NEXT=$(review_series_ensure "$HANDOFF_ROOT" propose/clean-finish 3 invariant-reviewer nd/clean-finish 2>/dev/null) || CLEAN_FINISH_NEXT=""
if [ "$CLEAN_FINISH_PREP_ONE" = "$CLEAN_FINISH_PREP_TWO" ] \
   && [ "$CLEAN_HANDOFF_ONE" = "$CLEAN_HANDOFF_TWO" ] \
   && review_pr_handoff_validate "$FIX/clean-handoff.md" propose/clean-finish "" "$CLEAN_FINISH_HEAD" \
   && grep -qFx '<!-- review-history:start -->' "$FIX/clean-handoff.md" \
   && grep -qFx "<!-- review-attempt:$CLEAN_BLOCK_ID:start -->" "$FIX/clean-handoff.md" \
   && grep -qFx "<!-- review-attempt:$CLEAN_FINAL_ID:start -->" "$FIX/clean-handoff.md" \
   && grep -qF '> [BLOCKING] The first proposal claim is unsafe.' "$FIX/clean-handoff.md" \
   && grep -qF 'Semantic outcome: blocking' "$FIX/clean-handoff.md" \
   && grep -qF 'Disposition: corrected-before-next-review' "$FIX/clean-handoff.md" \
   && grep -qE '^Elapsed seconds: [0-9]+$' "$FIX/clean-handoff.md" \
   && grep -qE '^Review-History-SHA256: [0-9a-f]{64}$' "$FIX/clean-handoff.md" \
   && ! review_pr_handoff_validate "$FIX/clean-handoff-missing-attempt.md" propose/clean-finish "" "$CLEAN_FINISH_HEAD" \
   && grep -qF 'No human review resolution was required.' "$FIX/clean-handoff.md" \
   && [ "$(jq -r '.reason' "$(review_series_dir "$HANDOFF_ROOT" "$CLEAN_FINISH_SERIES")/closed.json" 2>/dev/null)" = clean ] \
   && [ -n "$CLEAN_FINISH_NEXT" ] && [ "$CLEAN_FINISH_NEXT" != "$CLEAN_FINISH_SERIES" ]; then
  ok "a reviewed proposal prepares once, seals its exact HEAD, and starts a new later series"
else bad "a clean non-delivery PR handoff is idempotent, closes, and starts a new later series" \
  "attempt=${CLEAN_FINISH_ATTEMPT:-empty}; prep=${CLEAN_FINISH_PREP_ONE:-empty}; first=${CLEAN_HANDOFF_ONE:-empty}; second=${CLEAN_HANDOFF_TWO:-empty}; old=$CLEAN_FINISH_SERIES; new=${CLEAN_FINISH_NEXT:-empty}; current=$(CLAUDE_PROJECT_DIR="$HANDOFF_ROOT" "$HANDOFF_ROOT/core/scripts/tree-digest.sh" 2>/dev/null)"; fi
(
  cd "$HANDOFF_ROOT" || exit 1
  git switch -q main
  git branch -D propose/clean-finish >/dev/null
  git switch -qc propose/clean-finish "$CLEAN_FINISH_HEAD"
) || exit 1
RECREATED_SERIES=$(review_series_ensure "$HANDOFF_ROOT" propose/clean-finish 3 invariant-reviewer nd/recreated 2>/dev/null) || RECREATED_SERIES=""
if [ -n "$RECREATED_SERIES" ] && [ "$RECREATED_SERIES" != "$CLEAN_FINISH_SERIES" ] \
   && [ "$RECREATED_SERIES" != "$CLEAN_FINISH_NEXT" ] \
   && ! review_non_delivery_handoff_seal "$HANDOFF_ROOT" propose/clean-finish >/dev/null 2>&1; then
  ok "deleting and recreating a branch cannot replay its old review handoff"
else bad "deleting and recreating a branch cannot replay its old review handoff"; fi
rm -rf "$HANDOFF_ROOT"

DESIGN_HANDOFF_ROOT=$(mktemp -d)
mkdir -p "$DESIGN_HANDOFF_ROOT/core/scripts" "$DESIGN_HANDOFF_ROOT/docs/design"
for file in lib.sh review-workflow.sh review-receipt.sh round-ledger.sh task-ledger.sh accepted-rounds.sh; do
  cp "$ROOT/core/$file" "$DESIGN_HANDOFF_ROOT/core/$file"
done
for file in tree-digest.sh roadmap.sh claim.sh; do
  cp "$ROOT/core/scripts/$file" "$DESIGN_HANDOFF_ROOT/core/scripts/$file"
done
printf '.deliver/\n' > "$DESIGN_HANDOFF_ROOT/.gitignore"
printf '%s\n' '---' 'type: plan' 'status: living' 'last-verified: 2026-09-09' '---' \
  '### M1 — Test' '' '| Slug | Initiative | Depends | Design |' '|---|---|---|---|' \
  '| `sample` | Sample initiative | — | — |' '' '**Done when:** tested.' \
  > "$DESIGN_HANDOFF_ROOT/docs/roadmap.md"
(
  cd "$DESIGN_HANDOFF_ROOT" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git switch -qc design/sample
) || exit 1
printf '%s\n' '---' 'type: design' 'status: approved' 'last-verified: 2026-09-09' '---' \
  '# Sample design' '## 7. Tasks' '### Code track' '- [ ] **1.** Sample task.' \
  > "$DESIGN_HANDOFF_ROOT/docs/design/0997-sample.md"
mkdir -p "$DESIGN_HANDOFF_ROOT/.deliver"
printf 'snapshot\n' > "$DESIGN_HANDOFF_ROOT/.deliver/snapshot.txt"
DESIGN_REVIEW_TREE=$(CLAUDE_PROJECT_DIR="$DESIGN_HANDOFF_ROOT" "$DESIGN_HANDOFF_ROOT/core/scripts/tree-digest.sh")
DESIGN_SERIES=$(review_series_ensure "$DESIGN_HANDOFF_ROOT" design/sample 3 invariant-reviewer nd/design-sample 2>/dev/null) || DESIGN_SERIES=""
DESIGN_ATTEMPT=$(review_attempt_start "$DESIGN_HANDOFF_ROOT" "$DESIGN_SERIES" codex design-reviewer design-session \
  "$DESIGN_REVIEW_TREE" design/sample nd/design-sample "$DESIGN_HANDOFF_ROOT/.deliver/snapshot.txt" - 2>/dev/null) || DESIGN_ATTEMPT=""
printf 'VERDICT: clean — no findings.\n' > "$FIX/design-clean.md"
review_attempt_complete "$DESIGN_HANDOFF_ROOT" "$DESIGN_ATTEMPT" completed "$FIX/design-clean.md" >/dev/null 2>&1
CLAUDE_PROJECT_DIR="$DESIGN_HANDOFF_ROOT" "$DESIGN_HANDOFF_ROOT/core/scripts/claim.sh" sample 0997 >/dev/null 2>&1
DESIGN_CLAIM_RC=$?
git -C "$DESIGN_HANDOFF_ROOT" add -A
DESIGN_PREP=$(CLAUDE_PROJECT_DIR="$DESIGN_HANDOFF_ROOT" "$ROOT/core/scripts/review-finish.sh") || DESIGN_PREP=""
DESIGN_PREP_ID=$(printf '%s\n' "$DESIGN_PREP" | sed -n 's/^Review-Preparation: //p')
(
  cd "$DESIGN_HANDOFF_ROOT" || exit 1
  git -c user.email=t@t -c user.name=t commit -qm 'design: sample' -m "Review-Preparation: $DESIGN_PREP_ID"
) || exit 1
DESIGN_HEAD=$(git -C "$DESIGN_HANDOFF_ROOT" rev-parse HEAD)
DESIGN_HANDOFF=$(CLAUDE_PROJECT_DIR="$DESIGN_HANDOFF_ROOT" "$ROOT/core/scripts/review-pr-summary.sh") || DESIGN_HANDOFF=""
printf '%s\n' "$DESIGN_HANDOFF" > "$FIX/design-handoff.md"
if [ "$DESIGN_CLAIM_RC" = 0 ] \
   && grep -qF '| `sample` | Sample initiative | — | [0997](./design/0997-sample.md) |' "$DESIGN_HANDOFF_ROOT/docs/roadmap.md" \
   && review_pr_handoff_validate "$FIX/design-handoff.md" design/sample "" "$DESIGN_HEAD" \
   && [ "$(sed -n 's/^Review-Tree: //p' "$FIX/design-handoff.md")" != "$(sed -n 's/^Review-Result-Tree: //p' "$FIX/design-handoff.md")" ]; then
  ok "the real design claim is consumed before its commit is sealed to the exact PR head"
else bad "the real design claim is consumed before its commit is sealed to the exact PR head"; fi
rm -rf "$DESIGN_HANDOFF_ROOT"

ADR_HANDOFF_ROOT=$(mktemp -d)
mkdir -p "$ADR_HANDOFF_ROOT/core/scripts" "$ADR_HANDOFF_ROOT/docs/decisions"
for file in lib.sh review-workflow.sh review-receipt.sh round-ledger.sh task-ledger.sh accepted-rounds.sh; do
  cp "$ROOT/core/$file" "$ADR_HANDOFF_ROOT/core/$file"
done
cp "$ROOT/core/scripts/tree-digest.sh" "$ADR_HANDOFF_ROOT/core/scripts/tree-digest.sh"
printf '.deliver/\n' > "$ADR_HANDOFF_ROOT/.gitignore"
printf '# Decisions\n' > "$ADR_HANDOFF_ROOT/docs/decisions/README.md"
(
  cd "$ADR_HANDOFF_ROOT" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git switch -qc design/adr-only
) || exit 1
printf '%s\n' '---' 'type: decision' 'status: proposed' '---' '# ADR only' '' '## Decision' '' 'Pending human decision.' \
  > "$ADR_HANDOFF_ROOT/docs/decisions/0999-adr-only.md"
printf '%s\n' '' '| 0999 | ADR only | proposed |' >> "$ADR_HANDOFF_ROOT/docs/decisions/README.md"
mkdir -p "$ADR_HANDOFF_ROOT/.deliver"
printf 'snapshot\n' > "$ADR_HANDOFF_ROOT/.deliver/snapshot.txt"
ADR_TREE=$(CLAUDE_PROJECT_DIR="$ADR_HANDOFF_ROOT" "$ADR_HANDOFF_ROOT/core/scripts/tree-digest.sh")
ADR_SERIES=$(review_series_ensure "$ADR_HANDOFF_ROOT" design/adr-only 3 invariant-reviewer nd/adr-only 2>/dev/null) || ADR_SERIES=""
ADR_ATTEMPT=$(review_attempt_start "$ADR_HANDOFF_ROOT" "$ADR_SERIES" codex adr-reviewer adr-session \
  "$ADR_TREE" design/adr-only nd/adr-only "$ADR_HANDOFF_ROOT/.deliver/snapshot.txt" - 2>/dev/null) || ADR_ATTEMPT=""
printf 'VERDICT: clean — ADR-only fixture.\n' > "$FIX/adr-clean.md"
review_attempt_complete "$ADR_HANDOFF_ROOT" "$ADR_ATTEMPT" completed "$FIX/adr-clean.md" >/dev/null 2>&1
git -C "$ADR_HANDOFF_ROOT" add -A
ADR_PREP=$(CLAUDE_PROJECT_DIR="$ADR_HANDOFF_ROOT" "$ROOT/core/scripts/review-finish.sh") || ADR_PREP=""
ADR_PREP_ID=$(printf '%s\n' "$ADR_PREP" | sed -n 's/^Review-Preparation: //p')
(
  cd "$ADR_HANDOFF_ROOT" || exit 1
  git -c user.email=t@t -c user.name=t commit -qm 'docs: propose ADR-only decision' -m "Review-Preparation: $ADR_PREP_ID"
) || exit 1
ADR_HEAD=$(git -C "$ADR_HANDOFF_ROOT" rev-parse HEAD)
ADR_HANDOFF=$(CLAUDE_PROJECT_DIR="$ADR_HANDOFF_ROOT" "$ROOT/core/scripts/review-pr-summary.sh") || ADR_HANDOFF=""
printf '%s\n' "$ADR_HANDOFF" > "$FIX/adr-handoff.md"
jq -cn --arg body "$ADR_HANDOFF" --arg head "$ADR_HEAD" \
  '{pull_request:{body:$body,head:{ref:"design/adr-only",sha:$head}}}' > "$FIX/adr-event.json"
CLAUDE_PROJECT_DIR="$ADR_HANDOFF_ROOT" "$ROOT/core/scripts/review-pr-summary.sh" \
  --validate-event "$FIX/adr-event.json" main >/dev/null 2>&1
ADR_VALIDATE_RC=$?
printf 'later unreviewed change\n' >> "$ADR_HANDOFF_ROOT/docs/decisions/0999-adr-only.md"
git -C "$ADR_HANDOFF_ROOT" add -A
git -C "$ADR_HANDOFF_ROOT" -c user.email=t@t -c user.name=t commit -qm 'docs: later change'
ADR_LATER_HEAD=$(git -C "$ADR_HANDOFF_ROOT" rev-parse HEAD)
jq -cn --arg body "$ADR_HANDOFF" --arg head "$ADR_LATER_HEAD" \
  '{pull_request:{body:$body,head:{ref:"design/adr-only",sha:$head}}}' > "$FIX/adr-later-event.json"
CLAUDE_PROJECT_DIR="$ADR_HANDOFF_ROOT" "$ROOT/core/scripts/review-pr-summary.sh" \
  --validate-event "$FIX/adr-later-event.json" main >/dev/null 2>&1
ADR_LATER_RC=$?
ADR_STEP_FOUR=$(sed -n '/^4\. \*\*Stop if a decision/,/^5\. \*\*Write the doc/p' "$ROOT/workflows/design/SKILL.md")
if [ "$ADR_VALIDATE_RC" = 0 ] && [ "$ADR_LATER_RC" -ne 0 ] \
   && printf '%s' "$ADR_STEP_FOUR" | grep -qF 'invariant-reviewer' \
   && printf '%s' "$ADR_STEP_FOUR" | grep -qF 'review-finish.sh' \
   && printf '%s' "$ADR_STEP_FOUR" | grep -qF 'review-pr-summary.sh'; then
  ok "the ADR-only design exit reviews, prepares, seals, and invalidates a later commit"
else bad "the ADR-only design exit reviews, prepares, seals, and invalidates a later commit"; fi
rm -rf "$ADR_HANDOFF_ROOT"


echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
