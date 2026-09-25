#!/usr/bin/env bash
# Codex-native payload fixtures for the thin adapter into core/hooks/.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd) || exit 1
. "$ROOT/core/test-fixture.sh" || exit 1
cd "$ROOT" || exit 1
ADAPTER="$ROOT/adapters/codex/translate-edit.mjs"
pass=0 fail=0

payload() { # payload <event> <patch>
  jq -cn --arg event "$1" --arg command "$2" --arg root "$ROOT" '{
    session_id: "codex-test",
    turn_id: "turn-test",
    cwd: $root,
    hook_event_name: $event,
    tool_name: "apply_patch",
    tool_use_id: "tool-test",
    tool_input: {command: $command}
  }'
}

run() { # run <want-exit> <label> <hook> <event> <patch>
  local want="$1" label="$2" hook="$3" event="$4" patch="$5" got
  payload "$event" "$patch" \
    | CLAUDE_PROJECT_DIR="$ROOT" CODEX_HOOK=1 node "$ADAPTER" "$hook" >/dev/null 2>&1
  got=$?
  if [ "$got" = "$want" ]; then
    pass=$((pass+1)); printf '  ok    %s\n' "$label"
  else
    fail=$((fail+1)); printf '  FAIL  %s (want exit %s, got %s)\n' "$label" "$want" "$got"
  fi
}

# Product policies are tested in an independent consumer fixture, never in OH docs.
HARNESS_ROOT="$ROOT"
PRODUCT_FIXTURE=$(mktemp -d)
copy_harness "$ROOT" "$PRODUCT_FIXTURE" core || exit 1
mkdir -p "$PRODUCT_FIXTURE/docs/decisions" "$PRODUCT_FIXTURE/docs/reference"
printf '%s\n' '---' 'type: reference' 'status: living' 'last-verified: 2026-09-25' '---' '# My Geoffrey — Testing Strategy' > "$PRODUCT_FIXTURE/docs/reference/testing.md"
printf '%s\n' '---' 'type: decision' 'status: accepted' 'last-verified: 2026-09-25' '---' 'TypeScript' > "$PRODUCT_FIXTURE/docs/decisions/0001-typescript-monorepo-over-python.md"
printf '# Decision index\n' > "$PRODUCT_FIXTURE/docs/decisions/README.md"
git -C "$PRODUCT_FIXTURE" init -qb main
git -C "$PRODUCT_FIXTURE" add .
git -C "$PRODUCT_FIXTURE" -c user.name=Fixture -c user.email=fixture@example.invalid commit -qm fixture
git -C "$PRODUCT_FIXTURE" update-ref refs/remotes/origin/main HEAD
ROOT="$PRODUCT_FIXTURE"
echo "Codex apply_patch translation"

run 0 "an empty file add exposes its complete empty content" protect-receipts.sh PreToolUse \
"*** Begin Patch
*** Add File: empty-fixture.txt
*** End Patch"
run 0 "deletion-only replacement remains valid" protect-receipts.sh PreToolUse \
"*** Begin Patch
*** Update File: subject.txt
@@
-old text
*** End Patch"
run 2 "an empty new doc still requires frontmatter" doc-frontmatter.sh PreToolUse \
"*** Begin Patch
*** Add File: docs/reference/empty-fixture.md
*** End Patch"
run 0 "a deleted doc has no remaining frontmatter to validate" doc-frontmatter.sh PreToolUse \
"*** Begin Patch
*** Delete File: docs/reference/deleted-fixture.md
*** End Patch"
run 0 "a moved doc validates its destination without rejecting the deleted source" doc-frontmatter.sh PreToolUse \
"*** Begin Patch
*** Update File: docs/reference/testing.md
*** Move to: docs/reference/moved-fixture.md
@@
 # My Geoffrey — Testing Strategy
*** End Patch"

run 2 "an accepted ADR body edit is blocked" adr-immutability.sh PreToolUse \
"*** Begin Patch
*** Update File: docs/decisions/0001-typescript-monorepo-over-python.md
@@
-TypeScript
+JavaScript
*** End Patch"

run 0 "the accepted ADR supersede flip remains allowed" adr-immutability.sh PreToolUse \
"*** Begin Patch
*** Update File: docs/decisions/0001-typescript-monorepo-over-python.md
@@
-status: accepted
+status: superseded
+superseded-by: 0099
*** End Patch"

run 2 "one protected file blocks a multi-file patch" adr-immutability.sh PreToolUse \
"*** Begin Patch
*** Update File: README.md
@@
-old
+new
*** Update File: docs/decisions/0001-typescript-monorepo-over-python.md
@@
-TypeScript
+JavaScript
*** End Patch"

run 0 "an ordinary source edit is allowed" adr-immutability.sh PreToolUse \
"*** Begin Patch
*** Update File: packages/domain/src/money.ts
@@
+
*** End Patch"

run 2 "a new doc without frontmatter is blocked" doc-frontmatter.sh PreToolUse \
"*** Begin Patch
*** Add File: docs/reference/codex-fixture.md
+# Fixture
*** End Patch"

run 0 "a valid new doc is allowed" doc-frontmatter.sh PreToolUse \
"*** Begin Patch
*** Add File: docs/reference/codex-fixture.md
+---
+type: reference
+status: draft
+last-verified: 2026-08-12
+---
+
+# Fixture
*** End Patch"

run 2 "a receipt write is blocked" protect-receipts.sh PreToolUse \
"*** Begin Patch
*** Add File: .deliver/reviews/forged.md
+agent: invariant-reviewer
*** End Patch"

run 2 "the human-owned local delivery policy rejects model apply_patch" protect-local-policy.sh PreToolUse \
"*** Begin Patch
*** Add File: core/delivery-policy.local.json
+{\"continuation_window_tasks\":2,\"review_window_rounds\":5}
*** End Patch"

run 0 "local-policy protection allows unrelated model edits" protect-local-policy.sh PreToolUse \
"*** Begin Patch
*** Update File: packages/domain/src/money.ts
@@
+
*** End Patch"

run 2 "moving an accepted ADR is blocked" adr-immutability.sh PreToolUse \
"*** Begin Patch
*** Update File: docs/decisions/0001-typescript-monorepo-over-python.md
*** Move to: docs/decisions/0099-moved.md
*** End Patch"

run 0 "a new ADR missing from the log is advisory after the edit" adr-log-index.sh PostToolUse \
"*** Begin Patch
*** Add File: docs/decisions/0099-codex-fixture.md
+---
+type: decision
+status: proposed
+date: 2026-08-12
+---
*** End Patch"

ADVISORY=$(payload PostToolUse "*** Begin Patch
*** Add File: docs/decisions/0098-first-fixture.md
+first
*** Add File: docs/decisions/0099-second-fixture.md
+second
*** End Patch" | CLAUDE_PROJECT_DIR="$ROOT" node "$ADAPTER" adr-log-index.sh 2>/dev/null)
if [ "$?" = 0 ] && printf '%s' "$ADVISORY" | jq -se '
  length==1 and .[0].hookSpecificOutput.hookEventName=="PostToolUse" and
  (.[0].hookSpecificOutput.additionalContext | contains("0098-first-fixture.md") and contains("0099-second-fixture.md"))' >/dev/null; then
  pass=$((pass+1)); printf '  ok    multiple ADR advisories form one complete host response\n'
else
  fail=$((fail+1)); printf '  FAIL  multiple ADR advisories form one complete host response\n'
fi

run 2 "a path outside the repository fails closed" adr-immutability.sh PreToolUse \
"*** Begin Patch
*** Add File: ../outside.md
+x
*** End Patch"

BAD='{"hook_event_name":"PreToolUse","tool_name":"apply_patch","tool_input":{"command":"not a patch"}}'
printf '%s' "$BAD" | CLAUDE_PROJECT_DIR="$ROOT" node "$ADAPTER" adr-immutability.sh >/dev/null 2>&1
got=$?
if [ "$got" = 2 ]; then
  pass=$((pass+1)); printf '  ok    %s\n' "an unrecognised patch envelope fails closed"
else
  fail=$((fail+1)); printf '  FAIL  %s (want exit 2, got %s)\n' "an unrecognised patch envelope fails closed" "$got"
fi

ROOT="$HARNESS_ROOT"
rm -rf "$PRODUCT_FIXTURE"
# This suite retains legacy adapter behavior. Current user-plugin discovery is covered
# by the native installation/prompt tests and native-host conformance.

codex_assert() {
  if eval "$2"; then pass=$((pass+1)); printf '  ok    %s\n' "$1"
  else fail=$((fail+1)); printf '  FAIL  %s\n' "$1"; fi
}
codex_prompt() {
  local turn
  turn="turn-$(printf '%s' "$1" | cksum | cut -d' ' -f1)"
  jq -cn --arg prompt "$1" --arg turn "$turn" \
    '{hook_event_name:"UserPromptSubmit",session_id:"codex-session",turn_id:$turn,prompt:$prompt}'
}

echo "Codex UserPromptSubmit dispatch"
UP=$(mktemp -d)
mkdir -p "$UP/adapters/codex" "$UP/core/hooks"
: > "$UP/core/hooks/lib.sh"
cp "$ROOT/adapters/codex/run.sh" "$ROOT/adapters/codex/user-prompt-submit.sh" "$UP/adapters/codex/"
for UP_TARGET in \
  adapters/codex/round-grant.sh \
  adapters/codex/task-grant.sh \
  core/hooks/review-choice.sh \
  core/hooks/review-detached-context.sh; do
  printf '%s\n' '#!/usr/bin/env bash' 'basename "$0"' > "$UP/$UP_TARGET"
  chmod +x "$UP/$UP_TARGET"
done
prompt_target() {
  jq -cn --arg prompt "$1" --arg turn "turn-$2" \
    '{hook_event_name:"UserPromptSubmit",session_id:"dispatch-test",turn_id:$turn,prompt:$prompt}' \
    | CLAUDE_PROJECT_DIR="$UP" /bin/bash "$UP/adapters/codex/user-prompt-submit.sh"
}
codex_assert "an exact concern choice reaches the semantic recorder" \
  '[ "$(prompt_target "fix concerns" concern)" = review-choice.sh ]'
codex_assert "an exact window choice reaches the round recorder" \
  '[ "$(prompt_target "grant next review window" window)" = round-grant.sh ]'
codex_assert "an exact task choice reaches the task recorder" \
  '[ "$(prompt_target continue task)" = task-grant.sh ]'
codex_assert "an exact detached choice reaches the context recorder" \
  '[ "$(prompt_target "resume detached review d-1234567890-1234567890abcdef12345678" detached)" = review-detached-context.sh ]'
codex_assert "scope and detached stop choices cannot reach the task recorder" \
  '[ "$(prompt_target "stop scope routing" stop-scope)" = review-choice.sh ] &&
   [ "$(prompt_target "stop detached review" stop-detached)" = review-detached-context.sh ]'
codex_assert "ordinary prose reaches no workflow recorder" \
  '[ -z "$(prompt_target "please fix concerns" prose)" ]'
UP_LEGACY=$(jq -cn '{hook_event_name:"UserPromptSubmit",session_id:"dispatch-test",turn_id:"turn-legacy",prompt:"fix concerns"}')
UP_LEGACY_FIRST=$(printf '%s' "$UP_LEGACY" \
  | CLAUDE_PROJECT_DIR="$UP" /bin/bash "$UP/adapters/codex/run.sh" round-grant.sh)
UP_LEGACY_SECOND=$(printf '%s' "$UP_LEGACY" \
  | CLAUDE_PROJECT_DIR="$UP" /bin/bash "$UP/adapters/codex/run.sh" review-choice.sh)
codex_assert "a cached matcher-split session records one direct choice through its first handler" \
  '[ "$UP_LEGACY_FIRST:$UP_LEGACY_SECOND" = review-choice.sh: ]'


echo "Codex semantic attempt adapter"
CX=$(mktemp -d)
copy_harness "$ROOT" "$CX" core adapters .codex || exit 1
printf 'subject\n' > "$CX/subject.txt"
printf '.deliver/\n' > "$CX/.gitignore"
# One exhausted window proves host dispatch; core transitions live in the shared suite.
printf '{"continuation_window_tasks":1,"review_window_rounds":1}\n' > "$CX/core/delivery-policy.json"
(
  cd "$CX" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git switch -qc feature/codex-attempt
)
cx_payload() {
  jq -cn --arg id "$1" --arg event "$2" --arg message "${3:-}" '{
    hook_event_name:$event,agent_type:"invariant-reviewer",agent_id:$id,
    session_id:"codex-session",last_assistant_message:$message
  }'
}
CX_ID=11111111-1111-4111-8111-111111111111
CX_START=$(cx_payload "$CX_ID" SubagentStart | CLAUDE_PROJECT_DIR="$CX" CODEX_HOOK=1 \
  "$CX/core/hooks/review-start.sh" 2>/dev/null)
CX_ADMISSION=$(printf '%s' "$CX_START" | jq -r '.hookSpecificOutput.additionalContext' \
  | sed -n 's/^HARNESS REVIEW ADMISSION: //p')
codex_assert "a real Codex start allocates one valid immutable attempt" \
  '[ -n "$CX_ADMISSION" ] && CLAUDE_PROJECT_DIR="$CX" "$CX/core/scripts/review-admission-check.sh" "$CX_ADMISSION" >/dev/null && [ "$(find "$CX/.deliver/reviews/series" -name start.json | wc -l | tr -d "[:space:]")" = 1 ]'
CX_RAW='[CONCERN] The claim is too broad
## Evidence
## Evidence
VERDICT: findings — declared counts are ignored'
cx_payload "$CX_ID" SubagentStop "$CX_RAW" | CLAUDE_PROJECT_DIR="$CX" CODEX_HOOK=1 \
  "$CX/core/hooks/review-receipt.sh" >/dev/null 2>&1
CX_STOP_RC=$?
codex_assert "duplicated Evidence is retained as one concern without a correction turn" \
  '[ "$CX_STOP_RC" = 0 ] && [ "$(find "$CX/.deliver/reviews/series" -name completion.json -exec jq -r .outcome {} \;)" = concern ] && [ "$(find "$CX/.deliver/reviews/series" -name completion.json -exec jq -r .formatAnomalous {} \;)" = true ]'
CX_REUSE_CHECK=$(CLAUDE_PROJECT_DIR="$CX" "$CX/core/scripts/review-admission-check.sh" \
  "$CX_ADMISSION" 2>&1)
CX_REUSE_CHECK_RC=$?
codex_assert "the real reused-reviewer admission check names same-session recovery" \
  '[ "$CX_REUSE_CHECK_RC" = 2 ] && [ "$CX_REUSE_CHECK" = "$(cat "$CX/core/review-missing-fresh-refusal.txt")" ]'
CX_PRETOOL=$(jq -cn '{hook_event_name:"PreToolUse",tool_name:"Agent",session_id:"codex-session",
  tool_input:{subagent_type:"invariant-reviewer"}}')
printf '%s' "$CX_PRETOOL" | CLAUDE_PROJECT_DIR="$CX" \
  "$CX/adapters/codex/run.sh" round-refuse.sh >"$CX/.deliver/pretool.out" 2>&1
CX_PRETOOL_RC=$?
codex_assert "the Codex ceiling presents unresolved concerns before window choices" \
  '[ "$CX_PRETOOL_RC" = 2 ] && grep -q "Review: concern" "$CX/.deliver/pretool.out" &&
   grep -qFx "Human gate. Send one exact unformatted plain-text line:" "$CX/.deliver/pretool.out" &&
   grep -qFx "fix concerns" "$CX/.deliver/pretool.out" && grep -qFx "accept concerns" "$CX/.deliver/pretool.out" &&
   ! grep -qFx "grant next review window" "$CX/.deliver/pretool.out"'
codex_prompt 'fix concerns' | CLAUDE_PROJECT_DIR="$CX" CODEX_HOOK=1 \
  "$CX/adapters/codex/user-prompt-submit.sh" >/dev/null 2>&1
printf 'claim corrected\n' >> "$CX/subject.txt"
printf '%s' "$CX_PRETOOL" | CLAUDE_PROJECT_DIR="$CX" \
  "$CX/adapters/codex/run.sh" round-refuse.sh >"$CX/.deliver/fixed-pretool.out" 2>&1
codex_assert "after fixing concerns the Codex ceiling offers the review window" \
  '[ "$?" = 2 ] && grep -qFx "grant next review window" "$CX/.deliver/fixed-pretool.out" &&
   grep -qFx "stop and take it over" "$CX/.deliver/fixed-pretool.out" &&
   grep -qFx "stop and escalate to the pr" "$CX/.deliver/fixed-pretool.out"'
for CX_NEAR in 'Grant next review window'; do
  codex_prompt "$CX_NEAR" | CLAUDE_PROJECT_DIR="$CX" CODEX_HOOK=1 \
    "$CX/adapters/codex/run.sh" round-grant.sh >"$CX/.deliver/near-checkpoint.out" 2>&1
  codex_assert "the Codex near-match '$CX_NEAR' emits copy-safe checkpoint commands" \
    '[ "$(grep -cFx "grant next review window" "$CX/.deliver/near-checkpoint.out")" = 1 ] &&
     grep -qFx "stop and take it over" "$CX/.deliver/near-checkpoint.out" &&
     grep -qFx "stop and escalate to the pr" "$CX/.deliver/near-checkpoint.out" &&
     ! grep -qF "  grant next review window" "$CX/.deliver/near-checkpoint.out"'
done
# Renew through the host adapter before testing reuse: an exhausted window refuses earlier.
codex_prompt 'grant next review window' | CLAUDE_PROJECT_DIR="$CX" CODEX_HOOK=1 \
  "$CX/adapters/codex/run.sh" round-grant.sh >/dev/null 2>&1
cx_payload "$CX_ID" SubagentStart | CLAUDE_PROJECT_DIR="$CX" CODEX_HOOK=1 \
  "$CX/core/hooks/review-start.sh" >"$CX/.deliver/reused.out" 2>"$CX/.deliver/reused.err"
CX_REUSED_RC=$?
codex_assert "a reused Codex reviewer gets the fresh-reviewer diagnosis" \
  '[ "$CX_REUSED_RC" = 2 ] && grep -q "missing fresh-reviewer admission" "$CX/.deliver/reused.err"'
rm -rf "$CX"

PF=$(mktemp -d)
copy_harness "$ROOT" "$PF" core adapters .codex || exit 1
printf 'fallback\n' > "$PF/subject.txt"
printf '.deliver/\n' > "$PF/.gitignore"
(
  cd "$PF" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git switch -qc feature/codex-fallback
)
PF_ID=77777777-7777-4777-8777-777777777777
cx_payload "$PF_ID" SubagentStart | CLAUDE_PROJECT_DIR="$PF" CODEX_HOOK=1 \
  "$PF/core/hooks/review-start.sh" >/dev/null 2>&1
PF_NEXT_ID=88888888-8888-4888-8888-888888888888
PF_PRETOOL=$(jq -cn '{hook_event_name:"PreToolUse",tool_name:"Agent",session_id:"codex-session",
  tool_input:{subagent_type:"invariant-reviewer"}}')
printf '%s' "$PF_PRETOOL" | CLAUDE_PROJECT_DIR="$PF" CODEX_HOOK=1 \
  "$PF/core/hooks/review-pending-output.sh" >/dev/null 2>&1
PF_REVIEW_BLOCKED_RC=$?
cx_payload "$PF_NEXT_ID" SubagentStart | CLAUDE_PROJECT_DIR="$PF" CODEX_HOOK=1 \
  "$PF/core/hooks/review-start.sh" >/dev/null 2>&1
PF_START_BLOCKED_RC=$?
printf '%s' '{"hook_event_name":"PreToolUse","tool_name":"apply_patch"}' \
  | CLAUDE_PROJECT_DIR="$PF" CODEX_HOOK=1 "$PF/core/hooks/review-pending-output.sh" >/dev/null 2>&1
PF_BLOCKED_RC=$?
PF_RAW='The review stopped before a conclusion.'
printf '%s' "$PF_RAW" | CLAUDE_PROJECT_DIR="$PF" "$PF/core/scripts/review-retain.sh" >/dev/null 2>&1
PF_RETAIN_RC=$?
PF_CHOICE=$(jq -cn '{hook_event_name:"UserPromptSubmit",session_id:"codex-session",turn_id:"review-again-turn",prompt:"review again"}')
printf '%s' "$PF_CHOICE" | CLAUDE_PROJECT_DIR="$PF" CODEX_HOOK=1 \
  "$PF/adapters/codex/run.sh" review-choice.sh >/dev/null 2>&1
PF_CHOICE_RC=$?
cx_payload "$PF_NEXT_ID" SubagentStart | CLAUDE_PROJECT_DIR="$PF" CODEX_HOOK=1 \
  "$PF/core/hooks/review-start.sh" >/dev/null 2>&1
PF_START_RELEASED_RC=$?
printf '%s' '{"hook_event_name":"PreToolUse","tool_name":"apply_patch"}' \
  | CLAUDE_PROJECT_DIR="$PF" CODEX_HOOK=1 "$PF/core/hooks/review-pending-output.sh" >/dev/null 2>&1
PF_EDIT_BLOCKED_BY_NEXT_RC=$?
cx_payload "$PF_ID" SubagentStop "$PF_RAW" | CLAUDE_PROJECT_DIR="$PF" CODEX_HOOK=1 \
  "$PF/core/hooks/review-receipt.sh" >/dev/null 2>&1
PF_LATE_STOP_RC=$?
cx_payload "$PF_ID" SubagentStop '[CONCERN] Different late bytes' | CLAUDE_PROJECT_DIR="$PF" CODEX_HOOK=1 \
  "$PF/core/hooks/review-receipt.sh" >/dev/null 2>&1
PF_CONFLICT_STOP_RC=$?
PF_ATTEMPT=$(find "$PF/.deliver/reviews/series" -name start.json -exec dirname {} \; | sort | head -1)
PF_DIAGNOSTIC=$(find "$PF/.deliver/reviews/unattributed" -name '*.json' -type f -print -quit 2>/dev/null)
codex_assert "a missing Codex stop has an exact idempotent parent-side retention path" \
  '[ "$PF_REVIEW_BLOCKED_RC" = 2 ] && [ "$PF_START_BLOCKED_RC" = 2 ] &&
   [ "$PF_BLOCKED_RC" = 2 ] && [ "$PF_RETAIN_RC" = 0 ] && [ "$PF_CHOICE_RC" = 0 ] &&
   [ "$PF_START_RELEASED_RC" = 0 ] && [ "$PF_EDIT_BLOCKED_BY_NEXT_RC" = 2 ] &&
   [ "$PF_LATE_STOP_RC" = 0 ] && [ "$PF_CONFLICT_STOP_RC" -ne 0 ] &&
   [ "$(cat "$PF_ATTEMPT/raw.md")" = "$PF_RAW" ] &&
   [ "$(jq -r .outcome "$PF_ATTEMPT/completion.json")" = ambiguous ] &&
   [ "$(jq -r .attemptId "$PF_DIAGNOSTIC")" = a-000001 ] &&
   grep -qF "[CONCERN] Different late bytes" "${PF_DIAGNOSTIC%.json}.raw.md"'
rm -rf "$PF"

PI=$(mktemp -d)
copy_harness "$ROOT" "$PI" core adapters .codex || exit 1
printf 'interrupted fallback\n' > "$PI/subject.txt"
printf '.deliver/\n' > "$PI/.gitignore"
(
  cd "$PI" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git switch -qc feature/codex-interrupted
)
PI_ID=99999999-9999-4999-8999-999999999999
cx_payload "$PI_ID" SubagentStart | CLAUDE_PROJECT_DIR="$PI" CODEX_HOOK=1 \
  "$PI/core/hooks/review-start.sh" >/dev/null 2>&1
PI_NEXT=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa
PI_PRETOOL=$(jq -cn '{hook_event_name:"PreToolUse",tool_name:"Agent",session_id:"codex-session",
  tool_input:{subagent_type:"invariant-reviewer"}}')
printf '%s' "$PI_PRETOOL" | CLAUDE_PROJECT_DIR="$PI" CODEX_HOOK=1 \
  "$PI/core/hooks/review-pending-output.sh" >/dev/null 2>&1
PI_PENDING_RC=$?
PI_RECOVERY=$(CLAUDE_PROJECT_DIR="$PI" "$PI/core/scripts/review-retain.sh" --interrupted 2>&1)
PI_RECOVERY_RC=$?
cx_payload "$PI_NEXT" SubagentStart | CLAUDE_PROJECT_DIR="$PI" CODEX_HOOK=1 \
  "$PI/core/hooks/review-start.sh" >/dev/null 2>&1
PI_BEFORE_CHOICE_RC=$?
codex_prompt 'review again' | CLAUDE_PROJECT_DIR="$PI" CODEX_HOOK=1 \
  "$PI/adapters/codex/run.sh" review-choice.sh >/dev/null 2>&1
PI_CHOICE_RC=$?
cx_payload "$PI_NEXT" SubagentStart | CLAUDE_PROJECT_DIR="$PI" CODEX_HOOK=1 \
  "$PI/core/hooks/review-start.sh" >/dev/null 2>&1
PI_AFTER_CHOICE_RC=$?
PI_FIRST_ATTEMPT=$(find "$PI/.deliver/reviews/series" -name start.json -exec dirname {} \; | sort | head -1)
codex_assert "a killed no-output Codex reviewer reaches the human recovery gate without wedging the series" \
  '[ "$PI_PENDING_RC" = 2 ] && [ "$PI_RECOVERY_RC" = 0 ] &&
   [ "$(jq -r .status "$PI_FIRST_ATTEMPT/completion.json")" = empty ] &&
   [ "$(jq -r .outcome "$PI_FIRST_ATTEMPT/completion.json")" = ambiguous ] &&
   [ "$(printf "%s\n" "$PI_RECOVERY" | grep -cFx "review again")" = 1 ] &&
   printf "%s\n" "$PI_RECOVERY" | grep -qFx "take over" &&
   ! printf "%s\n" "$PI_RECOVERY" | grep -qF "Review again" &&
   [ "$PI_BEFORE_CHOICE_RC" = 2 ] && [ "$PI_CHOICE_RC" = 0 ] &&
   [ "$PI_AFTER_CHOICE_RC" = 0 ]'
cx_payload "$PI_NEXT" SubagentStop '' | CLAUDE_PROJECT_DIR="$PI" CODEX_HOOK=1 \
  "$PI/core/hooks/review-receipt.sh" >/dev/null 2>&1
PI_THIRD=bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb
cx_payload "$PI_THIRD" SubagentStart | CLAUDE_PROJECT_DIR="$PI" CODEX_HOOK=1 \
  "$PI/core/hooks/review-start.sh" >/dev/null 2>&1
PI_AUTO_RC=$?
PI_SECOND_ATTEMPT="${PI_FIRST_ATTEMPT%/*}/a-000002"
codex_assert "an ended zero-byte reviewer permits a new counted attempt in the same window" \
  '[ "$PI_AUTO_RC" = 0 ] && [ "$(jq -r .noResult "$PI_SECOND_ATTEMPT/completion.json")" = true ] &&
   [ ! -s "$PI_SECOND_ATTEMPT/raw.md" ] && [ "$(find "$PI/.deliver/reviews/series" -name start.json | wc -l | tr -d "[:space:]")" = 3 ]'
cx_payload "$PI_THIRD" SubagentStop '' | jq '.cancelled=true' | CLAUDE_PROJECT_DIR="$PI" CODEX_HOOK=1 \
  "$PI/core/hooks/review-receipt.sh" >/dev/null 2>&1
codex_assert "a user cancellation is not marked as automatic no-result recovery" \
  '[ "$(jq -r .noResult "${PI_FIRST_ATTEMPT%/*}/a-000003/completion.json")" = false ]'
cx_payload cccccccc-cccc-4ccc-8ccc-cccccccccccc SubagentStart | CLAUDE_PROJECT_DIR="$PI" CODEX_HOOK=1 \
  "$PI/core/hooks/review-start.sh" >/dev/null 2>&1
codex_assert "no-result replacements do not refund the exhausted review allowance" '[ "$?" = 2 ]'
rm -rf "$PI"

# core/README.md: a reviewed entry script can recover a confirmed Claude no-report
# termination in an unchanged checkout. The target deliberately has an older, unavailable
# retention entry point; copying/installing the fixed writer there would change its digest.
CH=$(mktemp -d)
copy_harness "$ROOT" "$CH" core adapters .codex || exit 1
printf 'cross-host recovery\n' > "$CH/subject.txt"
printf '.deliver/\n' > "$CH/.gitignore"
printf '#!/usr/bin/env bash\nexit 79\n' > "$CH/core/scripts/review-retain.sh"
(
  cd "$CH" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git switch -qc feature/cross-host-recovery
)
CH_START=$(jq -cn '{tool_name:"Agent",session_id:"ended-claude-session",
  tool_input:{subagent_type:"invariant-reviewer"}}')
printf '%s' "$CH_START" | CLAUDE_PROJECT_DIR="$CH" CODEX_HOOK= \
  "$CH/core/hooks/review-start.sh" >/dev/null 2>&1
CH_START_RC=$?
CH_ATTEMPT=$(find "$CH/.deliver/reviews/series" -name start.json -exec dirname {} \;)
CH_TREE=$(CLAUDE_PROJECT_DIR="$CH" "$CH/core/scripts/tree-digest.sh")
CH_RETAIN="$ROOT/core/scripts/review-retain.sh"
printf '[BLOCKING] Parent prose must not become a Claude report.\n' \
  | CLAUDE_PROJECT_DIR="$CH" "$CH_RETAIN" >/dev/null 2>&1
CH_REPORT_RC=$?
CLAUDE_PROJECT_DIR="$CH" "$CH_RETAIN" --interrupted >/dev/null 2>&1
CH_INTERRUPTED_RC=$?
codex_assert "Claude recovery does not widen report-writing or uncertain-interruption modes" \
  '[ "$CH_START_RC" = 0 ] && [ "$CH_REPORT_RC" = 2 ] && [ "$CH_INTERRUPTED_RC" = 2 ] &&
   [ ! -e "$CH_ATTEMPT/raw.md" ] && [ ! -e "$CH_ATTEMPT/completion.json" ]'
printf 'changed\n' >> "$CH/subject.txt"
CLAUDE_PROJECT_DIR="$CH" "$CH_RETAIN" --no-result >/dev/null 2>&1
CH_CHANGED_RC=$?
printf 'cross-host recovery\n' > "$CH/subject.txt"
git -C "$CH" switch -qc feature/other-context
CLAUDE_PROJECT_DIR="$CH" "$CH_RETAIN" --no-result >/dev/null 2>&1
CH_BRANCH_RC=$?
git -C "$CH" switch -q feature/cross-host-recovery
codex_assert "cross-checkout no-result recovery requires the original tree and branch" \
  '[ "$CH_CHANGED_RC" = 2 ] && [ "$CH_BRANCH_RC" = 2 ] && [ ! -e "$CH_ATTEMPT/completion.json" ]'
printf '[BLOCKING] Existing reviewer output.\n' > "$CH_ATTEMPT/raw.md"
CLAUDE_PROJECT_DIR="$CH" "$CH_RETAIN" --no-result >/dev/null 2>&1
CH_NONEMPTY_RC=$?
codex_assert "cross-host no-result recovery never erases a partially retained report" \
  '[ "$CH_NONEMPTY_RC" -ne 0 ] && [ ! -e "$CH_ATTEMPT/completion.json" ] &&
   grep -qFx "[BLOCKING] Existing reviewer output." "$CH_ATTEMPT/raw.md"'
rm "$CH_ATTEMPT/raw.md"
# These deliberately invalid fixture states cannot be produced by ordinary admission.
CH_SECOND="${CH_ATTEMPT%/*}/a-000002"
cp -R "$CH_ATTEMPT" "$CH_SECOND"
jq '.id="a-000002" | .ordinal=2 | .host="codex" | .owner="dual-host-reviewer"' \
  "$CH_SECOND/start.json" > "$CH_SECOND/start.tmp"
mv "$CH_SECOND/start.tmp" "$CH_SECOND/start.json"
CLAUDE_PROJECT_DIR="$CH" "$CH_RETAIN" --no-result >/dev/null 2>&1
CH_DUAL_RC=$?
codex_assert "no-result recovery refuses to choose between pending Claude and Codex attempts" \
  '[ "$CH_DUAL_RC" = 2 ] && [ ! -e "$CH_ATTEMPT/completion.json" ] &&
   [ ! -e "$CH_SECOND/completion.json" ]'
rm -rf "$CH_SECOND"
cp "$CH_ATTEMPT/snapshot.txt" "$CH/.deliver/snapshot.saved"
printf 'corrupt\n' >> "$CH_ATTEMPT/snapshot.txt"
CLAUDE_PROJECT_DIR="$CH" "$CH_RETAIN" --no-result >/dev/null 2>&1
CH_CORRUPT_RC=$?
codex_assert "no-result recovery rejects corrupt Claude admission evidence" \
  '[ "$CH_CORRUPT_RC" = 2 ] && [ ! -e "$CH_ATTEMPT/completion.json" ]'
mv "$CH/.deliver/snapshot.saved" "$CH_ATTEMPT/snapshot.txt"
CLAUDE_PROJECT_DIR="$CH" "$CH_RETAIN" --no-result >/dev/null 2>&1
CH_RECOVER_RC=$?
CH_AFTER_TREE=$(CLAUDE_PROJECT_DIR="$CH" "$CH/core/scripts/tree-digest.sh")
CLAUDE_PROJECT_DIR="$CH" "$CH/core/scripts/review-retain.sh" --no-result >/dev/null 2>&1
CH_OLD_WRITER_RC=$?
cx_payload cccccccc-aaaa-4aaa-8aaa-cccccccccccc SubagentStart | CLAUDE_PROJECT_DIR="$CH" CODEX_HOOK=1 \
  "$CH/core/hooks/review-start.sh" >/dev/null 2>&1
CH_RESUME_RC=$?
codex_assert "an external fixed writer preserves the target and admits one counted cross-host replacement" \
  '[ "$CH_RECOVER_RC" = 0 ] && [ "$CH_TREE" = "$CH_AFTER_TREE" ] &&
   [ "$CH_OLD_WRITER_RC" = 79 ] && [ "$CH_RESUME_RC" = 0 ] &&
   [ "$(jq -r .noResult "$CH_ATTEMPT/completion.json")" = true ] &&
   [ "$(jq -r .outcome "$CH_ATTEMPT/completion.json")" = ambiguous ] &&
   [ ! -s "$CH_ATTEMPT/raw.md" ] &&
   [ "$(jq -r .host "$CH_SECOND/start.json")" = codex ] &&
   [ "$(find "$CH/.deliver/reviews/series" -name series.json | wc -l | tr -d "[:space:]")" = 1 ] &&
   [ "$(find "$CH/.deliver/reviews/series" -name start.json | wc -l | tr -d "[:space:]")" = 2 ]'
rm -rf "$CH"

DH=$(mktemp -d)
copy_harness "$ROOT" "$DH" core adapters .codex || exit 1
printf 'detached\n' > "$DH/subject.txt"
printf '.deliver/\n' > "$DH/.gitignore"
(
  cd "$DH" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git checkout -q --detach HEAD
)
DH_SESSION=44444444-4444-4444-8444-444444444444
DH_AGENT=55555555-5555-4555-8555-555555555555
DH_START=$(jq -cn --arg session "$DH_SESSION" --arg agent "$DH_AGENT" \
  '{hook_event_name:"SubagentStart",agent_type:"invariant-reviewer",agent_id:$agent,session_id:$session}' \
  | CODEX_SESSION_ID="$DH_SESSION" CLAUDE_PROJECT_DIR="$DH" "$DH/adapters/codex/run.sh" review-start.sh 2>/dev/null)
DH_ADMISSION=$(printf '%s' "$DH_START" | jq -r '.hookSpecificOutput.additionalContext' | sed -n 's/^HARNESS REVIEW ADMISSION: //p')
DH_CONTEXT=$(find "$DH/.deliver/reviews/detached-contexts" -name 'd-*.json' -exec jq -r .id {} \;)
codex_assert "a real detached Codex start creates and validates an explicit context" \
  '[ -n "$DH_CONTEXT" ] && CLAUDE_PROJECT_DIR="$DH" "$DH/core/scripts/review-admission-check.sh" "$DH_ADMISSION" >/dev/null'
DH_CONTEXT_FILE="$DH/.deliver/reviews/detached-contexts/$DH_CONTEXT.json"
cp "$DH_CONTEXT_FILE" "$DH/.deliver/original-context.json"
jq '.repository="wrong-repository"' "$DH_CONTEXT_FILE" > "$DH/.deliver/invalid-context.json"
cp "$DH/.deliver/invalid-context.json" "$DH_CONTEXT_FILE"
DH_INVALID=$(CLAUDE_PROJECT_DIR="$DH" "$DH/core/scripts/review-admission-check.sh" "$DH_ADMISSION" 2>&1)
DH_INVALID_RC=$?
codex_assert "invalid detached admission names the context and recovery" \
  '[ "$DH_INVALID_RC" = 2 ] && printf "%s" "$DH_INVALID" | grep -qF "$DH_CONTEXT" && printf "%s" "$DH_INVALID" | grep -qF "same series/window"'
cp "$DH/.deliver/original-context.json" "$DH_CONTEXT_FILE"
jq -cn --arg session "$DH_SESSION" --arg agent "$DH_AGENT" \
  '{hook_event_name:"SubagentStop",agent_type:"invariant-reviewer",agent_id:$agent,session_id:$session,last_assistant_message:"VERDICT: clean — detached fixture"}' \
  | CODEX_SESSION_ID="$DH_SESSION" CLAUDE_PROJECT_DIR="$DH" "$DH/adapters/codex/run.sh" review-receipt.sh >/dev/null 2>&1
codex_assert "the detached Codex stop retains its output against the same context" \
  '[ "$(find "$DH/.deliver/reviews/series" -name completion.json -exec jq -r .outcome {} \;)" = clean ]'
DH_NEW_SESSION=66666666-6666-4666-8666-666666666666
DH_PRETOOL=$(jq -cn --arg session "$DH_NEW_SESSION" \
  '{hook_event_name:"PreToolUse",tool_name:"Agent",session_id:$session,tool_input:{subagent_type:"invariant-reviewer"}}')
printf '%s' "$DH_PRETOOL" | CODEX_SESSION_ID="$DH_NEW_SESSION" CLAUDE_PROJECT_DIR="$DH" \
  "$DH/adapters/codex/run.sh" round-refuse.sh >"$DH/detached-gate.out" 2>&1
DH_UNBOUND_RC=$?
jq -cn --arg session "$DH_NEW_SESSION" --arg prompt "resume detached review $DH_CONTEXT" \
  '{hook_event_name:"UserPromptSubmit",session_id:$session,turn_id:"resume-turn",prompt:$prompt}' \
  | CODEX_SESSION_ID="$DH_NEW_SESSION" CLAUDE_PROJECT_DIR="$DH" \
    "$DH/adapters/codex/run.sh" review-detached-context.sh >/dev/null 2>&1
printf '%s' "$DH_PRETOOL" | CODEX_SESSION_ID="$DH_NEW_SESSION" CLAUDE_PROJECT_DIR="$DH" \
  "$DH/adapters/codex/run.sh" round-refuse.sh >/dev/null 2>&1
DH_RESUMED_RC=$?
codex_assert "a later Codex session must present the exact detached context ID before reuse" \
  '[ "$DH_UNBOUND_RC" = 2 ] && [ "$DH_RESUMED_RC" = 0 ] &&
   [ "$(grep -cFx "resume detached review $DH_CONTEXT" "$DH/detached-gate.out")" = 1 ] &&
   grep -qFx "stop detached review" "$DH/detached-gate.out"'
rm -rf "$DH"

DX=$(mktemp -d)
copy_harness "$ROOT" "$DX" core adapters .codex || exit 1
mkdir -p "$DX/docs/design"
cat > "$DX/docs/design/0998-codex-delivery.md" <<'EOF'
---
type: design
status: approved
last-verified: 2026-09-08
---
# Codex delivery start fixture
## 7. Tasks
### Code track
- [ ] **1.** Bind one delivery review.
EOF
printf '.deliver/\n' > "$DX/.gitignore"
(
  cd "$DX" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git update-ref refs/remotes/origin/main HEAD
  CLAUDE_PROJECT_DIR="$DX" "$DX/core/scripts/start.sh" 0998 >/dev/null 2>&1
  printf 'implementation\n' > subject.txt
)
mkdir -p "$DX/.deliver"
cat > "$DX/.deliver/manifest.md" <<'EOF'
## Requirements covered
- The delivery start is bound.
## Rules checked
- ADR-0051 attempt admission.
## Affected surfaces
- Codex SubagentStart siblings.
## Claims and proof
- The retained attempt carries request.md.
## Adversarial self-review
- The validation-only sibling cannot be the publisher.
## Defect-family closure
- The delivery callback path is exercised.
## Prior finding dispositions
- none — first review
## Verification
- The attempt start validates.
## Limits
- Synthetic host payload only.
EOF
CLAUDE_PROJECT_DIR="$DX" "$DX/core/scripts/review-ready.sh" stage 0998 1 "$DX/.deliver/manifest.md" >/dev/null 2>&1
DX_ID=33333333-3333-4333-8333-333333333333
DX_START=$(cx_payload "$DX_ID" SubagentStart | CLAUDE_PROJECT_DIR="$DX" CODEX_HOOK=1 \
  "$DX/core/hooks/review-start.sh" 2>/dev/null)
DX_ADMISSION=$(printf '%s' "$DX_START" | jq -r '.hookSpecificOutput.additionalContext' \
  | sed -n 's/^HARNESS REVIEW ADMISSION: //p')
codex_assert "the real Codex delivery start publishes and retains its readiness input" \
  '[ -n "$DX_ADMISSION" ] && CLAUDE_PROJECT_DIR="$DX" "$DX/core/scripts/review-admission-check.sh" "$DX_ADMISSION" >/dev/null && [ -f "$DX/${DX_ADMISSION%/start.json}/request.md" ]'

# ADR-0053 / core/README.md: a no-result delivery retry must accept updated prior-
# attempt dispositions on the same tree without rewriting the original review input.
DX_FIRST_REQUEST="$DX/${DX_ADMISSION%/start.json}/request.md"
DX_FIRST_HASH=$(shasum -a 256 "$DX_FIRST_REQUEST")
DX_TREE=$(CLAUDE_PROJECT_DIR="$DX" "$DX/core/scripts/tree-digest.sh")
CLAUDE_PROJECT_DIR="$DX" "$DX/core/scripts/review-retain.sh" --no-result >/dev/null 2>&1
DX_RETAIN_RC=$?
CLAUDE_PROJECT_DIR="$DX" "$DX/core/scripts/complete.sh" 0998 1 >/dev/null 2>&1
DX_INCOMPLETE_RC=$?
sed 's/none — first review/none — no prior findings/' "$DX/.deliver/manifest.md" > "$DX/.deliver/next-manifest.md"
CLAUDE_PROJECT_DIR="$DX" "$DX/core/scripts/review-ready.sh" stage 0998 1 "$DX/.deliver/next-manifest.md" >/dev/null 2>&1
DX_RESTAGE_RC=$?
DX_NEXT_START=$(cx_payload 44444444-4444-4444-8444-444444444444 SubagentStart \
  | CLAUDE_PROJECT_DIR="$DX" CODEX_HOOK=1 "$DX/core/hooks/review-start.sh" 2>/dev/null)
DX_NEXT_RC=$?
DX_NEXT_ADMISSION=$(printf '%s' "$DX_NEXT_START" | jq -r '.hookSpecificOutput.additionalContext' \
  | sed -n 's/^HARNESS REVIEW ADMISSION: //p')
codex_assert "a no-result delivery retry binds new dispositions on the unchanged tree and keeps both rounds" \
  '[ "$DX_RETAIN_RC" = 0 ] && [ "$DX_INCOMPLETE_RC" = 5 ] && [ "$DX_RESTAGE_RC" = 0 ] &&
   [ "$DX_NEXT_RC" = 0 ] && [ -n "$DX_NEXT_ADMISSION" ] &&
   CLAUDE_PROJECT_DIR="$DX" "$DX/core/scripts/review-admission-check.sh" "$DX_NEXT_ADMISSION" >/dev/null &&
   [ "$DX_TREE" = "$(CLAUDE_PROJECT_DIR="$DX" "$DX/core/scripts/tree-digest.sh")" ] &&
   [ "$DX_FIRST_HASH" = "$(shasum -a 256 "$DX_FIRST_REQUEST")" ] &&
   grep -qF "none — no prior findings" "$DX/${DX_NEXT_ADMISSION%/start.json}/request.md" &&
   [ "$(jq -r .ordinal "$DX/$DX_NEXT_ADMISSION")" = 2 ] &&
   [ "$(CLAUDE_PROJECT_DIR="$DX" "$DX/core/scripts/round-status.sh" | sed -n "s/^rounds-used: //p")" = 2 ]'
rm -rf "$DX"

echo "Codex user-prompt task-boundary adapter"
CT=$(mktemp -d)
copy_harness "$ROOT" "$CT" core || exit 1
mkdir -p "$CT/docs/design" "$CT/adapters/codex"
cp "$ROOT/adapters/codex/task-grant.sh" "$CT/adapters/codex/task-grant.sh"
cp "$ROOT/adapters/codex/task-grant-from-session.sh" "$CT/adapters/codex/task-grant-from-session.sh"
cp "$ROOT/adapters/codex/desktop-grant-lib.sh" "$CT/adapters/codex/desktop-grant-lib.sh"
cp "$ROOT/adapters/codex/desktop-choice.mjs" "$CT/adapters/codex/desktop-choice.mjs"
cp "$ROOT/adapters/codex/user-prompt-submit.sh" "$CT/adapters/codex/user-prompt-submit.sh"
cat > "$CT/docs/design/0943-tasks.md" <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-21
---
## 7. Tasks
### Code track
- [ ] **1.** Boundary task.
- [ ] **2.** Next task.
EOF
(
  cd "$CT" || exit 1
  git init -q -b main . && printf '.deliver/\n' > .gitignore
  git add -A && git -c user.email=t@t -c user.name=t commit -qm init
  git update-ref refs/remotes/origin/main HEAD
  git checkout -q -b deliver/0943
  perl -pi -e 's/^- \[ \] \*\*1\./- [x] **1./' docs/design/0943-tasks.md
  perl -0pi -e 's/(- \[ \] \*\*2\.\*\* Next task\.)/$1\n### Infra track\n- [ ] **3.** Routed SCOPE follow-up./' \
    docs/design/0943-tasks.md
  git add -A && git -c user.email=t@t -c user.name=t commit -qm "task 1: boundary" -m "Review-Rounds: 1"
)
CTINC=$(git -C "$CT" log --reverse --format=%H origin/main..HEAD | head -1)
CTLED="$CT/.deliver/reviews/task-state/0943/$CTINC"
ct_reset() { rm -rf "$CT/.deliver/reviews/task-state" "$CT/.deliver/hook-events"; }
ct_run() {
  codex_prompt "$1" | CLAUDE_PROJECT_DIR="$CT" /bin/bash "$ROOT/adapters/codex/run.sh" task-grant.sh >"${2:-/dev/null}" 2>&1
}

ct_reset; ct_run continue
codex_assert "the exact bare continue prompt records continue" \
  'grep -q "^choice: continue$" "$CTLED/000001.choice"'
# ADR-0047 atomic no-replace publication: competing human choices cannot both authorize.
ct_reset
ct_run continue "$CT/.deliver/race-one.out" & CODEX_TASK_ONE=$!
ct_run pr "$CT/.deliver/race-two.out" & CODEX_TASK_TWO=$!
wait "$CODEX_TASK_ONE"; wait "$CODEX_TASK_TWO"
codex_assert "racing task choices authorize exactly one valid record and reject the loser" \
  '[ "$(find "$CTLED" -type f -name "*.choice" | wc -l | tr -d "[:space:]")" = 1 ] &&
   [ "$(grep -h "recorded human choice" "$CT/.deliver/race-one.out" "$CT/.deliver/race-two.out" | wc -l | tr -d "[:space:]")" = 1 ] &&
   [ "$(grep -h "nothing was recorded" "$CT/.deliver/race-one.out" "$CT/.deliver/race-two.out" | wc -l | tr -d "[:space:]")" = 1 ] &&
   CLAUDE_PROJECT_DIR="$CT" "$CT/core/scripts/task-status.sh" 0943 --history >/dev/null'
rm "$CT/.deliver/race-one.out" "$CT/.deliver/race-two.out"
ct_reset; ct_run pr
codex_assert "the exact bare pr prompt records pr" \
  'grep -q "^choice: pr$" "$CTLED/000001.choice"'
ct_reset; ct_run stop
codex_assert "the exact bare stop prompt records stop" \
  'grep -q "^choice: stop$" "$CTLED/000001.choice"'
for prompt in Continue ' continue' 'please continue'; do
  ct_reset; ct_run "$prompt"
  codex_assert "nonexact task prompt '$prompt' records nothing" '[ ! -d "$CTLED" ]'
done

echo "Codex Desktop transcript-backed task-choice adapter"
TDH=$(mktemp -d)
mkdir -p "$TDH/sessions/2026/09/04"
TD_SESSION=12121212-1212-4212-8212-121212121212
TD_MESSAGE=34343434-3434-4434-8434-343434343434
TD_CLIENT=56565656-5656-4656-8656-565656565656
td_transcript() {
  local choice="$1" transition="${2:-}"
  cat > "$TDH/sessions/2026/09/04/direct.jsonl" <<EOF
{"timestamp":"2026-09-04T12:00:00Z","ordinal":1,"type":"session_meta","payload":{"id":"$TD_SESSION","cwd":"$CT","originator":"codex_work_desktop","source":"vscode"}}
{"timestamp":"2026-09-04T12:01:00Z","ordinal":2,"type":"event_msg","payload":{"type":"item_completed","turn_id":"task-turn","item":{"type":"UserMessage","id":"$TD_MESSAGE","client_id":"$TD_CLIENT","content":[{"type":"text","text":"$choice\\n","text_elements":[]}]}}}
$transition
{"timestamp":"2026-09-04T12:01:01Z","ordinal":4,"type":"response_item","payload":{"type":"custom_tool_call","name":"exec","input":"const r = await tools.exec_command({cmd:\"adapters/codex/task-grant-from-session.sh\",workdir:\"$CT\"});","internal_chat_message_metadata_passthrough":{"turn_id":"task-turn"}}}
EOF
}
td_run() {
  CODEX_HOME="$TDH" CODEX_SESSION_ID="$TD_SESSION" CLAUDE_PROJECT_DIR="$CT" \
    "$CT/adapters/codex/task-grant-from-session.sh" >/dev/null 2>&1
}
for TD_CHOICE in continue pr stop; do
  ct_reset
  td_transcript "$TD_CHOICE"
  td_run
  TD_RC=$?
  codex_assert "the direct Desktop '$TD_CHOICE' choice records at the checkpoint" \
    '[ "$TD_RC" = 0 ] && grep -q "^choice: $TD_CHOICE$" "$CTLED/000001.choice"'
done
ct_reset
td_transcript continue
TD_REAL_INPUT=$'const r = await tools.exec_command({\n  yield_time_ms: 1000,\n  workdir: "'$CT$'",\n  cmd: "adapters/codex/task-grant-from-session.sh"\n});\ntext(r.output);'
jq -c --arg input "$TD_REAL_INPUT" 'if .ordinal == 4 then .payload.input = $input else . end' \
  "$TDH/sessions/2026/09/04/direct.jsonl" > "$TDH/real.jsonl"
mv "$TDH/real.jsonl" "$TDH/sessions/2026/09/04/direct.jsonl"
td_run
codex_assert "the Desktop adapter parses the real multiline, reordered invocation" \
  '[ "$?" = 0 ] && grep -q "^choice: continue$" "$CTLED/000001.choice"'

# A formatting-only failure may leave the original host choice followed by one retry of the
# same no-argument adapter. The unchanged checkpoint consumes it once; the published choice
# makes every further retry inert.
ct_reset
td_transcript continue
TD_RETRY_INPUT=$'const second = await tools.exec_command({\n  workdir: "'$CT$'",\n  cmd: "adapters/codex/task-grant-from-session.sh"\n});'
jq -c --arg input "$TD_REAL_INPUT" 'if .ordinal == 4 then .ordinal = 3 | .payload.input = $input else . end' \
  "$TDH/sessions/2026/09/04/direct.jsonl" > "$TDH/retry-first.jsonl"
jq -c 'if .ordinal == 3 then .payload.call_id = "call-format-failure" else . end' \
  "$TDH/retry-first.jsonl" > "$TDH/retry-call-id.jsonl"
jq -cn --arg root "$CT" '{timestamp:"2026-09-04T12:01:01Z",ordinal:4,type:"event_msg",payload:{type:"item_completed",turn_id:"task-turn",item:{type:"CommandExecution",id:"exec-format-failure",source:"unified_exec_startup",command:["/bin/zsh","-lc","adapters/codex/task-grant-from-session.sh"],cwd:("file://"+$root),status:"failed",exit_code:2}}}' \
  >> "$TDH/retry-call-id.jsonl"
jq -cn '{timestamp:"2026-09-04T12:01:01Z",ordinal:5,type:"response_item",payload:{type:"custom_tool_call_output",call_id:"call-format-failure",output:"task-window: no exact direct Desktop choice matches this branch and turn.\nProcess exited with code 2."}}' \
  >> "$TDH/retry-call-id.jsonl"
jq -cn --arg input "$TD_RETRY_INPUT" '{timestamp:"2026-09-04T12:01:02Z",ordinal:6,type:"response_item",payload:{type:"custom_tool_call",name:"exec",input:$input,internal_chat_message_metadata_passthrough:{turn_id:"task-turn"}}}' \
  >> "$TDH/retry-call-id.jsonl"
mv "$TDH/retry-call-id.jsonl" "$TDH/sessions/2026/09/04/direct.jsonl"
td_run
TD_RECOVERY_FIRST=$?
td_run
TD_RECOVERY_SECOND=$?
codex_assert "a formatting-only adapter failure recovers the unchanged choice exactly once" \
  '[ "$TD_RECOVERY_FIRST" = 0 ] && [ "$TD_RECOVERY_SECOND" = 2 ] && [ "$(find "$CTLED" -name "*.choice" | wc -l | tr -d "[:space:]")" = 1 ] && [ "$(find "$CT/.deliver/reviews/task-choice-recoveries" -name "*.json" | wc -l | tr -d "[:space:]")" = 1 ]'
cp "$TDH/sessions/2026/09/04/direct.jsonl" "$TDH/recovery-original.jsonl"
for TD_MUTATION in command extra; do
  ct_reset
  if [ "$TD_MUTATION" = command ]; then
    jq -c 'if .ordinal == 4 then .payload.item.command[2] = "git status" else . end' \
      "$TDH/recovery-original.jsonl" > "$TDH/sessions/2026/09/04/direct.jsonl"
  else
    jq -c '., (if .ordinal == 4 then .payload.item.type = "FileChange" else empty end)' \
      "$TDH/recovery-original.jsonl" > "$TDH/sessions/2026/09/04/direct.jsonl"
  fi
  td_run
  codex_assert "Desktop recovery rejects an unrelated $TD_MUTATION transition" \
    '[ "$?" = 2 ] && [ ! -d "$CTLED" ]'
done
cp "$TDH/recovery-original.jsonl" "$TDH/sessions/2026/09/04/direct.jsonl"

ct_reset
printf '%s\n' '{"continuation_window_tasks":2,"review_window_rounds":4}' \
  > "$CT/core/delivery-policy.local.json"
td_run
codex_assert "Desktop recovery refuses when the original local-policy snapshot cannot be proven" \
  '[ "$?" = 2 ] && [ ! -d "$CTLED" ]'
rm -f "$CT/core/delivery-policy.local.json"

ct_reset
td_transcript continue
jq -c --arg input "$TD_REAL_INPUT" 'if .ordinal == 4 then .ordinal = 3 | .payload.input = $input | .payload.call_id = "call-no-failure" else . end' \
  "$TDH/sessions/2026/09/04/direct.jsonl" > "$TDH/no-failure.jsonl"
jq -cn --arg input "$TD_RETRY_INPUT" '{timestamp:"2026-09-04T12:01:02Z",ordinal:5,type:"response_item",payload:{type:"custom_tool_call",name:"exec",input:$input,internal_chat_message_metadata_passthrough:{turn_id:"task-turn"}}}' \
  >> "$TDH/no-failure.jsonl"
mv "$TDH/no-failure.jsonl" "$TDH/sessions/2026/09/04/direct.jsonl"
td_run
codex_assert "two Desktop adapter calls without the exact formatting failure are not recovery evidence" \
  '[ "$?" = 2 ] && [ ! -d "$CTLED" ]'

ct_reset
td_transcript 'continue '
td_run
codex_assert "Desktop task-choice framing rejects surrounding whitespace" \
  '[ "$?" = 2 ] && [ ! -d "$CTLED" ]'
ct_reset
td_transcript continue '{"timestamp":"2026-09-04T12:01:00Z","ordinal":3,"type":"response_item","payload":{"type":"custom_tool_call","name":"diagnostic","input":"status","internal_chat_message_metadata_passthrough":{"turn_id":"task-turn"}}}'
td_run
codex_assert "an intervening Desktop tool transition makes the task choice stale" \
  '[ "$?" = 2 ] && [ ! -d "$CTLED" ]'
ct_reset
td_transcript continue
CODEX_HOME="$TDH" CODEX_SESSION_ID=78787878-7878-4787-8787-787878787878 \
  CLAUDE_PROJECT_DIR="$CT" "$CT/adapters/codex/task-grant-from-session.sh" >/dev/null 2>&1
codex_assert "another Desktop session cannot consume the direct task choice" \
  '[ "$?" = 2 ] && [ ! -d "$CTLED" ]'
CODEX_HOME="$TDH" CODEX_SESSION_ID="$TD_SESSION" CLAUDE_PROJECT_DIR="$CT" \
  "$CT/adapters/codex/task-grant-from-session.sh" continue >/dev/null 2>&1
codex_assert "the Desktop task adapter refuses a model-supplied choice argument" \
  '[ "$?" = 2 ] && [ ! -d "$CTLED" ]'
# Every offered review command reaches the same direct-message parser. Core disposition
# semantics are tested in review-workflow.test.sh; here the regression is host transport.
DD_ADAPTER=adapters/codex/review-choice-from-session.sh
dd_transcript() {
  local answer="$1" repo="$2" message="desktop-$(printf '%s' "$1" | cksum | cut -d' ' -f1)"
  jq -cn --arg root "$repo" --arg session "$TD_SESSION" \
    --arg source "${3:-vscode}" --arg originator "${4:-codex_work_desktop}" \
    '{type:"session_meta",payload:{id:$session,cwd:$root,originator:$originator,source:$source}}' > "$TDH/sessions/2026/09/04/direct.jsonl"
  jq -cn --arg answer "$answer" --arg message "$message" --arg client "$TD_CLIENT" \
    '{type:"event_msg",payload:{type:"item_completed",turn_id:"review-turn",item:{type:"UserMessage",id:$message,client_id:$client,content:($answer+"\n")}}}' >> "$TDH/sessions/2026/09/04/direct.jsonl"
  jq -cn --arg input "const r = await tools.exec_command({cmd:\"$DD_ADAPTER\",workdir:\"$repo\"}); text(r.output);" \
    '{type:"response_item",payload:{type:"custom_tool_call",name:"exec",input:$input,internal_chat_message_metadata_passthrough:{turn_id:"review-turn"}}}' >> "$TDH/sessions/2026/09/04/direct.jsonl"
}
for DD_ANSWER in 'fix concerns' 'accept concerns' 'route scope' 'dismiss scope' \
  'fix concerns and route scope' 'fix concerns and dismiss scope' \
  'accept concerns and route scope' 'accept concerns and dismiss scope' \
  'review again' 'take over' 'grant next review window' 'stop and take it over' \
  'stop and escalate to the pr' 'route scope to https://github.com/acme/repo/issues/42' \
  'resume detached review d-1788890000-aaaaaaaaaaaaaaaaaaaaaaaa' 'stop scope routing' 'stop detached review'; do
  dd_transcript "$DD_ANSWER" "$CT"
  DD_RESULT=$(CODEX_HOME="$TDH" CODEX_SESSION_ID="$TD_SESSION" node "$ROOT/adapters/codex/desktop-choice.mjs" "$CT" review "$DD_ADAPTER")
  codex_assert "Desktop transports the exact '$DD_ANSWER' command" '[ "${DD_RESULT%%$'"'\t'"'*}" = "$DD_ANSWER" ]'
done
for DD_META in 'exec Codex Desktop' 'exec codex_cli_rs' 'cli Codex Desktop'; do
  DD_SOURCE=${DD_META%% *}
  DD_ORIGINATOR=${DD_META#* }
  dd_transcript 'grant next review window' "$CT" "$DD_SOURCE" "$DD_ORIGINATOR"
  DD_RESULT=$(CODEX_HOME="$TDH" CODEX_SESSION_ID="$TD_SESSION" node "$ROOT/adapters/codex/desktop-choice.mjs" "$CT" review "$DD_ADAPTER")
  DD_RC=$?
  if [ "$DD_META" = 'exec Codex Desktop' ]; then
    codex_assert "Desktop exec sessions transport a direct window grant" \
      '[ "$DD_RC" = 0 ] && [ "${DD_RESULT%%$'"'\t'"'*}" = "grant next review window" ]'
  else
    codex_assert "Desktop choice rejects unsupported host metadata: $DD_META" '[ "$DD_RC" != 0 ]'
  fi
done
dd_transcript 'accept concerns' "$CT"
jq -c 'if .type=="response_item" then .payload.input += " await tools.exec_command({cmd:\"touch changed\"});" else . end' \
  "$TDH/sessions/2026/09/04/direct.jsonl" > "$TDH/unsafe.jsonl"
mv "$TDH/unsafe.jsonl" "$TDH/sessions/2026/09/04/direct.jsonl"
CODEX_HOME="$TDH" CODEX_SESSION_ID="$TD_SESSION" node "$ROOT/adapters/codex/desktop-choice.mjs" "$CT" review "$DD_ADAPTER" >/dev/null 2>&1
codex_assert "a second command in the same Desktop call invalidates the approval binding" '[ "$?" != 0 ]'

# Real Desktop -> dispatcher -> canonical recorders, including both terminal window choices.
for DD_ACTION in 'accept concerns' 'grant next review window' 'stop and take it over' 'stop and escalate to the pr'; do
  DR=$(mktemp -d)
  copy_harness "$ROOT" "$DR" core adapters .codex || exit 1
  printf '.deliver/\n' > "$DR/.gitignore"
  printf '{"continuation_window_tasks":1,"review_window_rounds":1}\n' > "$DR/core/delivery-policy.json"
  (cd "$DR" && git init -q -b main . && git add -A && git -c user.email=t@t -c user.name=t commit -qm init && git switch -qc feature/desktop)
  cx_payload desktop-reviewer SubagentStart | CLAUDE_PROJECT_DIR="$DR" CODEX_HOOK=1 "$DR/core/hooks/review-start.sh" >/dev/null 2>&1
  cx_payload desktop-reviewer SubagentStop '[CONCERN] Narrow this claim' | CLAUDE_PROJECT_DIR="$DR" CODEX_HOOK=1 "$DR/core/hooks/review-receipt.sh" >/dev/null 2>&1
  if [ "$DD_ACTION" = 'accept concerns' ]; then
    DD_ATTEMPT=$(find "$DR/.deliver/reviews/series" -name start.json -exec dirname {} \;)
    mkdir "$DD_ATTEMPT/pr-resolution.json"
  else
    # Spending the window must not bypass the prior concern disposition.
    dd_transcript "$DD_ACTION" "$DR"
    CODEX_HOME="$TDH" CODEX_SESSION_ID="$TD_SESSION" CLAUDE_PROJECT_DIR="$DR" "$DR/$DD_ADAPTER" >/dev/null 2>&1
    codex_assert "Desktop '$DD_ACTION' cannot bypass an unresolved concern" \
      '[ "$?" != 0 ] && [ -z "$(find "$DR/.deliver/reviews" \( -name handoff.json -o -name closed.json -o -name "*.grant" \))" ]'
    dd_transcript 'fix concerns' "$DR"
    CODEX_HOME="$TDH" CODEX_SESSION_ID="$TD_SESSION" CLAUDE_PROJECT_DIR="$DR" "$DR/$DD_ADAPTER" >/dev/null 2>&1
    printf 'concern corrected\n' > "$DR/correction.txt"
  fi
  dd_transcript "$DD_ACTION" "$DR" exec 'Codex Desktop'
  DD_OUTPUT=$(CODEX_HOME="$TDH" CODEX_SESSION_ID="$TD_SESSION" CLAUDE_PROJECT_DIR="$DR" "$DR/$DD_ADAPTER" 2>&1)
  DD_RC=$?
  if [ "$DD_ACTION" = 'accept concerns' ]; then
    codex_assert "a failed PR-resolution publication preserves the already saved choice" \
      '[ "$DD_RC" = 2 ] && [ "$(jq -r .choice "$DD_ATTEMPT/resolution.json")" = accept-concerns ]'
    rmdir "$DD_ATTEMPT/pr-resolution.json"
    CLAUDE_PROJECT_DIR="$DR" "$DR/core/scripts/review-route-scope.sh" >/dev/null 2>&1
    DD_RC=$?
  fi
  case "$DD_ACTION" in
    'accept concerns') DD_RECORD=$(find "$DR/.deliver/reviews/series" -name resolution.json); DD_VALUE=$(jq -r .choice "$DD_RECORD" 2>/dev/null); DD_EXPECTED=accept-concerns ;;
    'grant next review window') DD_RECORD=$(find "$DR/.deliver/reviews" -name '*.grant'); DD_VALUE=$(sed -n 's/^window-after: //p' "$DD_RECORD" 2>/dev/null); DD_EXPECTED=2 ;;
    *) DD_RECORD=$(find "$DR/.deliver/reviews/series" -name handoff.json); DD_VALUE=$(jq -r .authorizesCompletion "$DD_RECORD" 2>/dev/null); DD_EXPECTED=false ;;
  esac
  codex_assert "Desktop records '$DD_ACTION' through the canonical writer" '[ "$DD_RC" = 0 ] && [ "$DD_VALUE" = "$DD_EXPECTED" ]'
  DD_BEFORE=$(find "$DR/.deliver/reviews" -type f | wc -l)
  CODEX_HOME="$TDH" CODEX_SESSION_ID="$TD_SESSION" CLAUDE_PROJECT_DIR="$DR" "$DR/$DD_ADAPTER" >/dev/null 2>&1
  codex_assert "replaying '$DD_ACTION' cannot publish a second transition" '[ "$DD_BEFORE" = "$(find "$DR/.deliver/reviews" -type f | wc -l)" ]'
  rm -rf "$DR"
done
rm -rf "$TDH" "$CT"

printf '{}' | CLAUDE_PROJECT_DIR="$ROOT" adapters/codex/run.sh not-a-hook >/dev/null 2>&1
got=$?
if [ "$got" = 2 ]; then
  pass=$((pass+1)); printf '  ok    %s\n' "the hook dispatcher fails closed on an unknown target"
else
  fail=$((fail+1)); printf '  FAIL  %s\n' "the hook dispatcher fails closed on an unknown target"
fi

echo
echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
