#!/usr/bin/env bash
# Tests for the guardrail hooks. Run: core/hooks/test.sh
#
# The guardrails are the thing standing between an agent and an invariant violation.
# Untested, they are a comfort rather than a control — so they get a suite, and the CI
# equivalents that land in Phase 0 will run it too.
set -uo pipefail
# Native Claude fixtures must not inherit the driving Codex host identity.
unset CODEX_HOOK CODEX_SESSION_ID
cd "$(dirname "${BASH_SOURCE[0]}")/../.." || exit 1
. "$PWD/core/test-fixture.sh" || exit 1
export CLAUDE_PROJECT_DIR="$PWD"
H="core/hooks"

pass=0; fail=0

# expect <want-exit> <label> <hook> <json>
expect() {
  local want="$1" label="$2" hook="$3" json="$4" got
  printf '%s' "$json" | "$H/$hook" >/dev/null 2>&1
  got=$?
  if [ "$got" = "$want" ]; then
    pass=$((pass+1)); printf '  ok    %s\n' "$label"
  else
    fail=$((fail+1)); printf '  FAIL  %s (want exit %s, got %s)\n' "$label" "$want" "$got"
  fi
}

echo "Claude project discovery contract"
# core/README.md's asset table is the human-readable inventory; this is its exact
# machine-checkable event/matcher/script projection. Exact-set equality means a hook cannot
# disappear, move to a different lifecycle event, or arrive undocumented while the suite stays
# green. This is deliberately in the shared suite, beside the hooks whose Claude wiring it owns.
CLAUDE_WIRING_EXPECTED=$(LC_ALL=C sort <<'EOF'
PreToolUse	Edit|Write	adr-immutability.sh
PreToolUse	Edit|Write	protect-local-policy.sh
PostToolUse	Bash	adr-write-detector.sh
PreToolUse	Write	doc-frontmatter.sh
PostToolUse	Write	adr-log-index.sh
SubagentStop	invariant-reviewer	review-receipt.sh
PreToolUse	Agent|SendMessage	review-dispatch.sh
PostToolUse	Agent	round-track.sh
PostToolUse	AskUserQuestion	round-grant.sh
PostToolUse	AskUserQuestion	review-choice.sh
PostToolUse	AskUserQuestion	review-detached-context.sh
PostToolUse	AskUserQuestion	task-grant.sh
PreToolUse	Edit|Write	protect-receipts.sh
PostToolUse	Bash	main-branch-detector.sh
SessionStart		enable-githooks.sh
EOF
)

claude_wiring_manifest() { # claude_wiring_manifest <settings.json>
  jq -er '
    .hooks
    | to_entries[] as $event
    | $event.value[]
    | (.matcher // "") as $matcher
    | .hooks[]
    | select(.type == "command")
    | .command as $command
    | if ($command | test("^\\$CLAUDE_PROJECT_DIR/core/hooks/[^/]+\\.sh$"))
      then [$event.key, $matcher, ($command | split("/") | last)] | @tsv
      else error("undocumented Claude hook command: \($command)")
      end
  ' "$1" | LC_ALL=C sort
}

claude_wiring_matches() { # claude_wiring_matches <settings.json>
  local actual
  actual=$(claude_wiring_manifest "$1") || return 1
  [ "$actual" = "$CLAUDE_WIRING_EXPECTED" ]
}

if claude_wiring_matches adapters/claude/settings.template.json; then
  pass=$((pass+1)); printf '  ok    %s\n' "settings.json matches the documented Claude hook wiring exactly"
else
  fail=$((fail+1)); printf '  FAIL  %s\n' "settings.json matches the documented Claude hook wiring exactly"
fi

# The three reviewer checks must remain one handler: Claude runs sibling matching commands
# concurrently, which can strand admission from a spawn another sibling refused.
CLAUDE_WIRING_FIXTURES=$(mktemp -d)
jq '(.hooks.PreToolUse[] | select(.matcher == "Agent|SendMessage").hooks) = []' \
  adapters/claude/settings.template.json > "$CLAUDE_WIRING_FIXTURES/no-round-refuse.json"
if ! claude_wiring_matches "$CLAUDE_WIRING_FIXTURES/no-round-refuse.json"; then
  pass=$((pass+1)); printf '  ok    %s\n' "removing Claude's sequential reviewer dispatcher fails the contract"
else
  fail=$((fail+1)); printf '  FAIL  %s\n' "removing Claude's sequential reviewer dispatcher fails the contract"
fi

jq '.hooks.PostToolUse |= map(select(.matcher != "Agent"))' \
  adapters/claude/settings.template.json > "$CLAUDE_WIRING_FIXTURES/no-round-track.json"
if ! claude_wiring_matches "$CLAUDE_WIRING_FIXTURES/no-round-track.json"; then
  pass=$((pass+1)); printf '  ok    %s\n' "removing Claude's reviewer-tracking wiring fails the contract"
else
  fail=$((fail+1)); printf '  FAIL  %s\n' "removing Claude's reviewer-tracking wiring fails the contract"
fi
rm -rf "$CLAUDE_WIRING_FIXTURES"

DISPATCH_FIXTURE=$(mktemp -d)
cp core/hooks/review-dispatch.sh "$DISPATCH_FIXTURE/review-dispatch.sh"
cat > "$DISPATCH_FIXTURE/lib.sh" <<'EOF'
hook_init() { PAYLOAD=$(cat); }
EOF
cat > "$DISPATCH_FIXTURE/review-ready-gate.sh" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null; echo ready >> "$DISPATCH_LOG"; [ ! -e "$DISPATCH_BLOCK" ]
EOF
for h in round-refuse review-admit; do
  cat > "$DISPATCH_FIXTURE/$h.sh" <<EOF
#!/usr/bin/env bash
cat >/dev/null; echo ${h%%-*} >> "\$DISPATCH_LOG"
EOF
done
chmod +x "$DISPATCH_FIXTURE"/*.sh
DISPATCH_LOG="$DISPATCH_FIXTURE/log" DISPATCH_BLOCK="$DISPATCH_FIXTURE/block"
touch "$DISPATCH_BLOCK"
printf '{}' | DISPATCH_LOG="$DISPATCH_LOG" DISPATCH_BLOCK="$DISPATCH_BLOCK" "$DISPATCH_FIXTURE/review-dispatch.sh" >/dev/null 2>&1
got=$?
rm -f "$DISPATCH_BLOCK"
printf '{}' | DISPATCH_LOG="$DISPATCH_LOG" DISPATCH_BLOCK="$DISPATCH_BLOCK" "$DISPATCH_FIXTURE/review-dispatch.sh" >/dev/null 2>&1
if [ "$got" = 2 ] && [ "$(tr '\n' ' ' < "$DISPATCH_LOG")" = "ready ready round review " ]; then
  pass=$((pass+1)); printf '  ok    %s\n' "a blocked Claude spawn leaves no admission and its corrected retry runs in order"
else
  fail=$((fail+1)); printf '  FAIL  %s\n' "a blocked Claude spawn leaves no admission and its corrected retry runs in order"
fi
rm -rf "$DISPATCH_FIXTURE"

ACCEPTED="$PWD/docs/decisions/0001-typescript-monorepo-over-python.md"
REFDOC="$PWD/docs/reference/architecture.md"

echo "adr-immutability.sh"
# Runs against a throwaway repo that owns its refs. The subject under test is now "what does
# the trunk say" (ADR-0036), and against the real repo that answer would depend on whether
# the developer has ever fetched — the suite would then be testing the machine, not the hook.
IMMU=$(mktemp -d)
(
  cd "$IMMU" || exit 1
  git init -q .
  mkdir -p docs/decisions docs/reference
  printf -- '---\ntype: decision\nstatus: accepted\ndate: 2026-08-01\n---\n\n# ADR-0001\n\n## Decision\n\nThe thing.\n' > docs/decisions/0001-accepted.md
  printf -- '---\ntype: reference\nstatus: draft\nlast-verified: 2026-08-01\n---\n\n# Ref\n' > docs/reference/architecture.md
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git update-ref refs/remotes/origin/main HEAD          # the trunk the guardrail reads
)
IACC="$IMMU/docs/decisions/0001-accepted.md"

# immu <want-exit> <label> <json> — the hook, rooted in the sandbox.
immu() {
  local want="$1" label="$2" json="$3" got
  printf '%s' "$json" | CLAUDE_PROJECT_DIR="$IMMU" "$PWD/$H/adr-immutability.sh" >/dev/null 2>&1
  got=$?
  if [ "$got" = "$want" ]; then pass=$((pass+1)); printf '  ok    %s\n' "$label"
  else fail=$((fail+1)); printf '  FAIL  %s (want exit %s, got %s)\n' "$label" "$want" "$got"; fi
}
immu 2 "Write over an ADR accepted on the trunk is blocked" \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$IACC\",\"file_text\":\"x\"}}"
immu 2 "Edit changing its body is blocked" \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$IACC\",\"edits\":[{\"old_text\":\"## Decision\",\"new_text\":\"## Revised decision\"}]}}"
immu 0 "Edit flipping status to superseded is allowed" \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$IACC\",\"edits\":[{\"old_text\":\"status: accepted\",\"new_text\":\"status: superseded\\nsuperseded-by: 0026\"}]}}"
immu 0 "Edit via the flat old_string/new_string shape is understood" \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$IACC\",\"old_string\":\"status: accepted\",\"new_string\":\"status: superseded\"}}"
immu 2 "Edit with no recognisable payload blocks (fails closed)" \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$IACC\"}}"
immu 0 "A new, not-yet-existing ADR is allowed" \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$IMMU/docs/decisions/0026-new.md\",\"file_text\":\"x\"}}"
immu 0 "Files outside decisions/ are ignored" \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$IMMU/docs/reference/architecture.md\",\"file_text\":\"x\"}}"
immu 0 "Bash is not this hook's business (see adr-write-detector.sh)" \
  '{"tool_name":"Bash","tool_input":{"command":"anything at all"}}'

# ADR-0036: the trunk decides, not the file's own frontmatter and not the branch.
printf -- '---\ntype: decision\nstatus: accepted\ndate: 2026-08-09\n---\n\n# ADR-0002\n\nDraft.\n' > "$IMMU/docs/decisions/0002-draft.md"
immu 0 "An ADR that says accepted but is not on the trunk is a draft, and editable" \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$IMMU/docs/decisions/0002-draft.md\",\"old_string\":\"Draft.\",\"new_string\":\"Revised after review.\"}}"
( cd "$IMMU" && git add -A && git -c user.email=t@t -c user.name=t commit -qm draft )
immu 0 "Committing that draft on the branch does not make it immutable" \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$IMMU/docs/decisions/0002-draft.md\",\"old_string\":\"Draft.\",\"new_string\":\"Revised again.\"}}"

# The two-edit hole: downgrade the working copy, then rewrite freely. The trunk still says
# accepted, so the guardrail is not talked out of its job.
printf -- '---\ntype: decision\nstatus: proposed\ndate: 2026-08-01\n---\n\n# ADR-0001\n\n## Decision\n\nThe thing.\n' > "$IACC"
immu 2 "A working copy flipped to proposed is still guarded by the trunk" \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$IACC\",\"edits\":[{\"old_text\":\"The thing.\",\"new_text\":\"Something else.\"}]}}"
( cd "$IMMU" && git checkout -q -- docs/decisions/0001-accepted.md )

( cd "$IMMU" && git update-ref -d refs/remotes/origin/main )
immu 2 "An unresolvable trunk ref blocks rather than assuming a draft" \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$IACC\",\"edits\":[{\"old_text\":\"The thing.\",\"new_text\":\"Something else.\"}]}}"
( cd "$IMMU" && git update-ref refs/remotes/origin/main HEAD )

echo "doc-frontmatter.sh"
expect 2 "A new doc with no frontmatter is blocked" doc-frontmatter.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/docs/reference/new.md\",\"file_text\":\"# Title\\n\"}}"
expect 2 "An empty native document write needs frontmatter" doc-frontmatter.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/docs/reference/new.md\",\"file_text\":\"\"}}"
expect 2 "A native document write missing text needs frontmatter" doc-frontmatter.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/docs/reference/new.md\"}}"
expect 0 "An explicit translated deletion has no document to validate" doc-frontmatter.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/docs/reference/new.md\",\"patch_operation\":\"delete\",\"file_text\":\"\"}}"
expect 0 "Existing document edits use the separate lifecycle verification" doc-frontmatter.sh \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$PWD/docs/reference/new.md\",\"old_string\":\"Old\",\"new_string\":\"New\"}}"
expect 0 "A valid reference doc is allowed" doc-frontmatter.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/docs/reference/new.md\",\"file_text\":\"---\\ntype: reference\\nstatus: draft\\nlast-verified: 2026-08-06\\n---\\n\\n# T\\n\"}}"
expect 2 "A reference doc without last-verified is blocked" doc-frontmatter.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/docs/reference/new.md\",\"file_text\":\"---\\ntype: reference\\nstatus: draft\\n---\\n\"}}"
expect 2 "A decision with a non-decision status is blocked" doc-frontmatter.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/docs/decisions/0026-x.md\",\"file_text\":\"---\\ntype: decision\\nstatus: living\\ndate: 2026-08-06\\n---\\n\"}}"
expect 0 "A valid new decision is allowed" doc-frontmatter.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/docs/decisions/0026-x.md\",\"file_text\":\"---\\ntype: decision\\nstatus: accepted\\ndate: 2026-08-06\\n---\\n\"}}"
expect 0 "A harness decision may declare its review subject" doc-frontmatter.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/docs/decisions/0026-x.md\",\"file_text\":\"---\\ntype: decision\\nstatus: proposed\\nsubject: harness\\ndate: 2026-08-06\\n---\\n\"}}"
expect 2 "A decision rejects an unknown review subject" doc-frontmatter.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/docs/decisions/0026-x.md\",\"file_text\":\"---\\ntype: decision\\nstatus: proposed\\nsubject: product\\ndate: 2026-08-06\\n---\\n\"}}"
expect 2 "A reference-typed doc filed under decisions/ is blocked" doc-frontmatter.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/docs/decisions/0026-x.md\",\"file_text\":\"---\\ntype: reference\\nstatus: draft\\nlast-verified: 2026-08-06\\n---\\n\"}}"
expect 2 "A frozen design doc without 'delivered' is blocked" doc-frontmatter.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/docs/design/0001-x.md\",\"file_text\":\"---\\ntype: design\\nstatus: frozen\\nlast-verified: 2026-08-06\\n---\\n\"}}"
expect 2 "A non-frozen design doc claiming 'delivered' is blocked" doc-frontmatter.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/docs/design/0001-x.md\",\"file_text\":\"---\\ntype: design\\nstatus: approved\\ndelivered: M1\\nlast-verified: 2026-08-06\\n---\\n\"}}"
expect 0 "Directory READMEs are exempt" doc-frontmatter.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/docs/design/README.md\",\"file_text\":\"# Design docs\\n\"}}"
expect 0 "Files outside docs/ are ignored" doc-frontmatter.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/README.md\",\"file_text\":\"# x\\n\"}}"

echo "adr-log-index.sh"
expect 0 "An ADR already in the log passes" adr-log-index.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$ACCEPTED\"}}"
expect 0 "An ADR missing from the log reports back without blocking subsequent work" adr-log-index.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/docs/decisions/0026-not-listed.md\"}}"
expect 0 "Non-ADR writes are ignored" adr-log-index.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$REFDOC\"}}"

echo "adr-write-detector.sh"
# Runs against a throwaway repo, because the subject under test is git working-tree state.
SANDBOX=$(mktemp -d)
(
  cd "$SANDBOX" || exit 1
  git init -q .
  mkdir -p docs/decisions
  printf -- '---\ntype: decision\nstatus: accepted\ndate: 2026-08-01\n---\n\n# ADR-0001\n\n## Decision\n\nThe thing.\n' > docs/decisions/0001-accepted.md
  printf -- '---\ntype: decision\nstatus: proposed\ndate: 2026-08-01\n---\n\n# ADR-0002\n\nDraft.\n' > docs/decisions/0002-proposed.md
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git update-ref refs/remotes/origin/main HEAD          # the trunk the guardrail reads
)
SANDBOX_TRUNK=$(git -C "$SANDBOX" rev-parse refs/remotes/origin/main)
detect() { # detect <want-exit> <label>
  local want="$1" label="$2" got
  ( CLAUDE_PROJECT_DIR="$SANDBOX" printf '{"tool_name":"Bash","tool_input":{"command":"x"}}' \
    | CLAUDE_PROJECT_DIR="$SANDBOX" "$PWD/$H/adr-write-detector.sh" ) >/dev/null 2>&1
  got=$?
  if [ "$got" = "$want" ]; then pass=$((pass+1)); printf '  ok    %s\n' "$label"
  else fail=$((fail+1)); printf '  FAIL  %s (want exit %s, got %s)\n' "$label" "$want" "$got"; fi
}

detect 0 "A clean tree passes"
printf -- '---\ntype: decision\nstatus: accepted\ndate: 2026-08-01\n---\n\n# ADR-0001\n\n## Decision\n\nSomething else entirely.\n' > "$SANDBOX/docs/decisions/0001-accepted.md"
detect 2 "A body change to an accepted ADR is caught, however it was written"
git -C "$SANDBOX" checkout -q -- docs/decisions/0001-accepted.md

printf -- '---\ntype: decision\nstatus: superseded\nsuperseded-by: 0026\ndate: 2026-08-01\n---\n\n# ADR-0001\n\n## Decision\n\nThe thing.\n' > "$SANDBOX/docs/decisions/0001-accepted.md"
detect 0 "The supersede flip passes"
git -C "$SANDBOX" checkout -q -- docs/decisions/0001-accepted.md

printf -- '---\ntype: decision\nstatus: proposed\ndate: 2026-08-01\n---\n\n# ADR-0002\n\nRewritten.\n' > "$SANDBOX/docs/decisions/0002-proposed.md"
detect 0 "A not-yet-accepted ADR may still change"
git -C "$SANDBOX" checkout -q -- docs/decisions/0002-proposed.md

printf -- '---\ntype: decision\nstatus: accepted\ndate: 2026-08-06\n---\n\n# ADR-0026\n' > "$SANDBOX/docs/decisions/0026-brand-new.md"
detect 0 "A brand-new untracked ADR passes"
git -C "$SANDBOX" add -A
git -C "$SANDBOX" -c user.email=t@t -c user.name=t commit -qm new
detect 0 "…and still passes once committed on the branch — the trunk has not seen it (ADR-0036)"

# "Only the status read moves" (ADR-0036), stated as a test that can fail if it stops being
# true. A body rewrite is committed on the branch, then a status-only flip is left
# uncommitted on top. Diffed against HEAD — this guard's scope — the only changed lines are
# `status:`/`superseded-by:`, so it passes. Diffed against the trunk it would also see the
# committed rewrite and exit 2, re-reporting it on every Bash call until the branch merged.
printf -- '---\ntype: decision\nstatus: accepted\ndate: 2026-08-01\n---\n\n# ADR-0001\n\n## Decision\n\nRewritten and committed on the branch.\n' > "$SANDBOX/docs/decisions/0001-accepted.md"
git -C "$SANDBOX" add -A
git -C "$SANDBOX" -c user.email=t@t -c user.name=t commit -qm rewrite
printf -- '---\ntype: decision\nstatus: superseded\nsuperseded-by: 0026\ndate: 2026-08-01\n---\n\n# ADR-0001\n\n## Decision\n\nRewritten and committed on the branch.\n' > "$SANDBOX/docs/decisions/0001-accepted.md"
detect 0 "The diff base stays HEAD: a committed rewrite is CI's, not this guard's"
git -C "$SANDBOX" reset -q --hard HEAD~1

git -C "$SANDBOX" update-ref -d refs/remotes/origin/main
printf -- '---\ntype: decision\nstatus: accepted\ndate: 2026-08-01\n---\n\n# ADR-0001\n\n## Decision\n\nAnything.\n' > "$SANDBOX/docs/decisions/0001-accepted.md"
detect 2 "An unresolvable trunk ref reports rather than waving the change through"
git -C "$SANDBOX" checkout -q -- docs/decisions/0001-accepted.md
git -C "$SANDBOX" update-ref refs/remotes/origin/main "$SANDBOX_TRUNK"

echo "protect-receipts.sh"
expect 2 "A write into .deliver/ is blocked" protect-receipts.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/.deliver/reviews/abc.md\",\"file_text\":\"forged\"}}"
expect 0 "Writes elsewhere are ignored" protect-receipts.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/packages/domain/money.ts\",\"file_text\":\"x\"}}"

echo "protect-local-policy.sh"
expect 2 "A model write to local delivery policy is blocked" protect-local-policy.sh \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$PWD/core/delivery-policy.local.json\",\"file_text\":\"{}\"}}"
expect 2 "A normalized relative path cannot bypass local-policy protection" protect-local-policy.sh \
  '{"tool_name":"Edit","tool_input":{"file_path":"core/../core/delivery-policy.local.json"}}'
expect 0 "Local-policy protection ignores unrelated edits" protect-local-policy.sh \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$PWD/core/delivery-policy.json\"}}"


echo "semantic attempt lifecycle (ADR-0051)"
RV=$(mktemp -d)
copy_harness "$PWD" "$RV" core || exit 1
printf 'subject\n' > "$RV/subject.txt"
printf '{"continuation_window_tasks":1,"review_window_rounds":2}\n' > "$RV/core/delivery-policy.json"
printf '.deliver/\n' > "$RV/.gitignore"
(
  cd "$RV" || exit 1
  git init -q -b main .
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm init
  git switch -qc feature/claude-attempt
)
claude_start_payload() {
  jq -cn --arg session "$1" '{hook_event_name:"PreToolUse",tool_name:"Agent",session_id:$session,
    tool_input:{subagent_type:"invariant-reviewer"}}'
}
claude_stop_payload() {
  jq -cn --arg session "$1" --arg message "$2" '{hook_event_name:"SubagentStop",
    agent_type:"invariant-reviewer",session_id:$session,last_assistant_message:$message}'
}
admission_failure() {
  local label="$1" cause="$2" output rc; shift 2
  output=$(CLAUDE_PROJECT_DIR="$RV" "$RV/core/scripts/review-admission-check.sh" "$@" 2>&1); rc=$?
  if [ "$rc" = 2 ] && printf '%s' "$output" | grep -qF "$cause" &&
     printf '%s' "$output" | grep -qF 'same series/window'; then
    pass=$((pass+1)); printf '  ok    %s\n' "$label"
  else fail=$((fail+1)); printf '  FAIL  %s — %s\n' "$label" "$output"; fi
}
admission_failure "absent review context explains how to obtain admission" 'no valid open review series'
START_ONE=$(claude_start_payload session-one | CLAUDE_PROJECT_DIR="$RV" "$RV/core/hooks/review-start.sh" 2>/dev/null)
ADMISSION_ONE=$(printf '%s' "$START_ONE" | jq -r '.hookSpecificOutput.additionalContext' | sed -n 's/^HARNESS REVIEW ADMISSION: //p')
if [ -n "$ADMISSION_ONE" ] && CLAUDE_PROJECT_DIR="$RV" "$RV/core/scripts/review-admission-check.sh" >/dev/null; then
  pass=$((pass+1)); printf '  ok    %s\n' "Claude locates its active immutable attempt"
else fail=$((fail+1)); printf '  FAIL  %s\n' "Claude locates its active immutable attempt"; fi
RV_ATTEMPT="$RV/${ADMISSION_ONE%/start.json}"
cp "$RV_ATTEMPT/start.json" "$RV/.deliver/original-start.json"
printf 'invalid JSON\n' > "$RV_ATTEMPT/start.json"
admission_failure "corrupt pending evidence names its record and recovery" 'corrupt start'
cp "$RV/.deliver/original-start.json" "$RV_ATTEMPT/start.json"
RV_DUPLICATE="${RV_ATTEMPT%/*}/a-000002"
cp -R "$RV_ATTEMPT" "$RV_DUPLICATE"
jq '.id="a-000002" | .ordinal=2' "$RV/.deliver/original-start.json" > "$RV_DUPLICATE/start.json"
admission_failure "ambiguous pending evidence names both attempts and recovery" 'ambiguous pending attempts'
rm -rf "$RV_DUPLICATE"
git -C "$RV" update-index --assume-unchanged subject.txt
admission_failure "fingerprint failure retains its concrete cause and recovery" 'assume-unchanged' "$ADMISSION_ONE"
git -C "$RV" update-index --no-assume-unchanged subject.txt
jq '.roundKey="nd/stale-context"' "$RV/.deliver/original-start.json" > "$RV_ATTEMPT/start.json"
admission_failure "changed round-key binding explains fresh admission" 'roundKey changed' "$ADMISSION_ONE"
cp "$RV/.deliver/original-start.json" "$RV_ATTEMPT/start.json"
printf 'invalid JSON\n' > "$RV_ATTEMPT/completion.json"
admission_failure "malformed completion is distinct from a completed reviewer" 'malformed completion record' "$ADMISSION_ONE"
rm "$RV_ATTEMPT/completion.json"
claude_start_payload session-one | CLAUDE_PROJECT_DIR="$RV" "$RV/core/hooks/review-start.sh" >/dev/null 2>&1
if [ "$?" = 2 ]; then pass=$((pass+1)); printf '  ok    %s\n' "the same Claude session cannot overlap attempts"
else fail=$((fail+1)); printf '  FAIL  %s\n' "the same Claude session cannot overlap attempts"; fi
claude_start_payload session-two | CLAUDE_PROJECT_DIR="$RV" "$RV/core/hooks/review-start.sh" >/dev/null 2>&1
if [ "$?" = 0 ] && [ "$(find "$RV/.deliver/reviews/series" -name completion.json -exec jq -r .status {} \; | head -1)" = interrupted ]; then
  pass=$((pass+1)); printf '  ok    %s\n' "a new Claude session records the abandoned attempt as interrupted"
else fail=$((fail+1)); printf '  FAIL  %s\n' "a new Claude session records the abandoned attempt as interrupted"; fi
claude_stop_payload session-one 'late old output' | CLAUDE_PROJECT_DIR="$RV" "$RV/core/hooks/review-receipt.sh" >/dev/null 2>&1
if [ "$?" != 0 ] && [ "$(find "$RV/.deliver/reviews/unattributed" -name '*.json' | wc -l | tr -d '[:space:]')" = 1 ]; then
  pass=$((pass+1)); printf '  ok    %s\n' "a delayed old-session stop is retained without stealing the new attempt"
else fail=$((fail+1)); printf '  FAIL  %s\n' "a delayed old-session stop is retained without stealing the new attempt"; fi
CLAUDE_CONCERN='[CONCERN] A claim is too broad
## Evidence
## Evidence
VERDICT: findings — counts ignored'
claude_stop_payload session-two "$CLAUDE_CONCERN" | CLAUDE_PROJECT_DIR="$RV" "$RV/core/hooks/review-receipt.sh" >/dev/null 2>&1
admission_failure "completed Claude reviewer explains its required disposition" 'already completed' "$ADMISSION_ONE"
admission_failure "an open series without an active reviewer explains fresh admission" 'no active Claude attempt'
TREE=$(CLAUDE_PROJECT_DIR="$RV" "$RV/core/scripts/tree-digest.sh")
ANSWER=$(jq -cn '{hook_event_name:"PostToolUse",tool_name:"AskUserQuestion",session_id:"session-two",tool_use_id:"choice-one",
  tool_input:{questions:[{multiSelect:false,options:[{label:"Fix concerns"},{label:"Accept concerns"}]}]},
  tool_response:{answers:{review:"Accept concerns"}}}')
for MENU_CASE in unrelated incomplete; do
  if [ "$MENU_CASE" = unrelated ]; then
    BAD_ANSWER=$(printf '%s' "$ANSWER" | jq '.tool_input.questions[0].options=[{label:"Option A"},{label:"Option B"}] | .tool_response.answers.review="Option A"')
  else
    BAD_ANSWER=$(printf '%s' "$ANSWER" | jq '.tool_input.questions[0].options=[{label:"Accept concerns"}]')
  fi
  IGNORED=$(printf '%s' "$BAD_ANSWER" | CLAUDE_PROJECT_DIR="$RV" "$RV/core/hooks/review-choice.sh" 2>&1)
  if [ "$?" = 0 ] && [ -z "$IGNORED" ] && [ -z "$(find "$RV/.deliver/reviews/series" -name resolution.json)" ]; then
    pass=$((pass+1)); printf '  ok    %s\n' "Claude ignores $MENU_CASE semantic menus without a false gate"
  else fail=$((fail+1)); printf '  FAIL  %s — %s\n' "$MENU_CASE semantic menu" "$IGNORED"; fi
done
MALFORMED=$(printf '%s' "$ANSWER" | jq '.tool_response.answers.review="Option A"' | CLAUDE_PROJECT_DIR="$RV" "$RV/core/hooks/review-choice.sh" 2>&1)
if [ "$?" = 2 ] && printf '%s' "$MALFORMED" | grep -q 'Nothing recorded' && printf '%s' "$MALFORMED" | grep -qFx 'Fix concerns'; then
  pass=$((pass+1)); printf '  ok    %s\n' "a malformed answer to the actual semantic menu explains its recovery"
else fail=$((fail+1)); printf '  FAIL  %s — %s\n' "semantic malformed answer" "$MALFORMED"; fi
WINDOW_ANSWER=$(jq -cn '{tool_name:"AskUserQuestion",session_id:"session-two",tool_use_id:"window-one",
  tool_input:{questions:[{multiSelect:false,options:[{label:"Grant next review window"},{label:"Stop and take it over"},{label:"Stop and escalate to the PR"}]}]},
  tool_response:{answers:{review:"Grant next review window"}}}')
WINDOW_PENDING=$(printf '%s' "$WINDOW_ANSWER" | CLAUDE_PROJECT_DIR="$RV" "$RV/core/hooks/round-grant.sh" 2>&1)
if [ -z "$(find "$RV/.deliver/reviews" -name '*.grant')" ] && printf '%s' "$WINDOW_PENDING" | grep -qFx 'Fix concerns'; then
  pass=$((pass+1)); printf '  ok    %s\n' "Claude retains the concern gate before window renewal"
else fail=$((fail+1)); printf '  FAIL  %s — %s\n' "semantic before window" "$WINDOW_PENDING"; fi
printf '%s' "$ANSWER" | CLAUDE_PROJECT_DIR="$RV" "$RV/core/hooks/review-choice.sh" >/dev/null 2>&1
if CLAUDE_PROJECT_DIR="$RV" /bin/bash -c '. "$1/core/review-receipt.sh"; review_completion_authorized "$1" "$2"' _ "$RV" "$TREE"; then
  pass=$((pass+1)); printf '  ok    %s\n' "one exact Claude choice accepts concerns for the reviewed tree"
else fail=$((fail+1)); printf '  FAIL  %s\n' "one exact Claude choice accepts concerns for the reviewed tree"; fi
DETACHED_ANSWER=$(jq -cn '{tool_name:"AskUserQuestion",tool_input:{questions:[{multiSelect:false,options:[{label:"Resume detached review d-example"},{label:"Stop detached review"}]}]},tool_response:{answers:{review:"Stop detached review"}}}')
DETACHED_STOP=$(printf '%s' "$DETACHED_ANSWER" | CLAUDE_PROJECT_DIR="$RV" "$RV/core/hooks/review-detached-context.sh" 2>&1)
DETACHED_UNRELATED=$(printf '%s' "$DETACHED_ANSWER" | jq '.tool_input.questions[0].options=[{label:"Option A"},{label:"Option B"}]' | CLAUDE_PROJECT_DIR="$RV" "$RV/core/hooks/review-detached-context.sh" 2>&1)
if printf '%s' "$DETACHED_STOP" | grep -q 'stopped; retained context unchanged' && [ -z "$DETACHED_UNRELATED" ]; then
  pass=$((pass+1)); printf '  ok    %s\n' "Claude detached stop belongs only to its complete menu"
else fail=$((fail+1)); printf '  FAIL  %s\n' "detached stop menu binding"; fi
# A real changed tree now needs another review, so test the window menu itself.
printf 'follow-up correction\n' >> "$RV/subject.txt"
for MENU_CASE in single unrelated; do
  if [ "$MENU_CASE" = single ]; then
    BAD_WINDOW=$(printf '%s' "$WINDOW_ANSWER" | jq '.tool_input.questions[0].options=[{label:"Grant next review window"}]')
  else
    BAD_WINDOW=$(printf '%s' "$WINDOW_ANSWER" | jq '.tool_input.questions[0].options=[{label:"Option A"},{label:"Option B"}]')
  fi
  IGNORED=$(printf '%s' "$BAD_WINDOW" | CLAUDE_PROJECT_DIR="$RV" "$RV/core/hooks/round-grant.sh" 2>&1)
  if [ "$?" = 0 ] && [ -z "$IGNORED" ] && [ -z "$(find "$RV/.deliver/reviews" -name '*.grant')" ]; then
    pass=$((pass+1)); printf '  ok    %s\n' "a $MENU_CASE window menu cannot authorize renewal"
  else fail=$((fail+1)); printf '  FAIL  %s — %s\n' "$MENU_CASE window menu" "$IGNORED"; fi
done
MALFORMED=$(printf '%s' "$WINDOW_ANSWER" | jq '.tool_response.answers.review=[]' | CLAUDE_PROJECT_DIR="$RV" "$RV/core/hooks/round-grant.sh" 2>&1)
if printf '%s' "$MALFORMED" | grep -q 'Nothing recorded' && printf '%s' "$MALFORMED" | grep -qFx 'Grant next review window'; then
  pass=$((pass+1)); printf '  ok    %s\n' "a malformed answer to the window menu presents its exact choices"
else fail=$((fail+1)); printf '  FAIL  %s — %s\n' "window malformed answer" "$MALFORMED"; fi
printf '%s' "$WINDOW_ANSWER" | CLAUDE_PROJECT_DIR="$RV" "$RV/core/hooks/round-grant.sh" >/dev/null 2>&1
if [ "$(find "$RV/.deliver/reviews" -name '*.grant' | wc -l | tr -d '[:space:]')" = 1 ]; then
  pass=$((pass+1)); printf '  ok    %s\n' "the complete Claude window menu renews after semantic disposition"
else fail=$((fail+1)); printf '  FAIL  %s\n' "complete window menu renewal"; fi
rm -rf "$RV"


TH=$(mktemp -d)
copy_harness "$PWD" "$TH" core || exit 1
mkdir -p "$TH/docs/design"
cat > "$TH/docs/design/0942-tasks.md" <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-21
---
## 7. Tasks
### Code track
- [ ] **1.** Completed boundary.
- [ ] **2.** Next task.
EOF
(
  cd "$TH" || exit 1
  git init -q -b main . && printf '.deliver/\n' > .gitignore
  git add -A && git -c user.email=t@t -c user.name=t commit -qm init
  git update-ref refs/remotes/origin/main HEAD
  git checkout -q -b deliver/0942
  perl -pi -e 's/^- \[ \] \*\*1\./- [x] **1./' docs/design/0942-tasks.md
  git add -A && git -c user.email=t@t -c user.name=t commit -qm "task 1: boundary" -m "Review-Rounds: 1"
)
task_payload() { jq -cn --arg answer "$1" '{hook_event_name:"PostToolUse",tool_name:"AskUserQuestion",
  tool_input:{questions:[{question:"Continue this run?",header:"Task window",multiSelect:false,
    options:[{label:"Continue with next task window",description:"Continue."},{label:"Open PR with completed tasks",description:"Open PR."},{label:"Stop without opening a PR",description:"Stop."}]}]},
  tool_response:{answers:{"Continue this run?":$answer}}}'; }
task_choice_run() { printf '%s' "$1" | CLAUDE_PROJECT_DIR="$TH" "$TH/core/hooks/task-grant.sh" >/dev/null 2>&1; }
TH_INC=$(git -C "$TH" log --reverse --format=%H origin/main..HEAD | head -n 1)
TH_LEDGER="$TH/.deliver/reviews/task-state/0942/$TH_INC"
TASK_AMBIGUOUS=$(task_payload 'Continue with next task window' | jq '.tool_response.answers["Continue this run?"]=["Continue with next task window","Open PR with completed tasks"]' | CLAUDE_PROJECT_DIR="$TH" "$TH/core/hooks/task-grant.sh" 2>&1)
AMBIGUOUS_EMPTY=0; [ ! -e "$TH_LEDGER" ] && AMBIGUOUS_EMPTY=1
task_choice_run "$(task_payload 'Continue with next task window')"
if [ "$AMBIGUOUS_EMPTY" = 1 ] && printf '%s' "$TASK_AMBIGUOUS" | grep -qFx 'Continue with next task window' && grep -q '^choice: continue$' "$TH_LEDGER/000001.choice"; then
  pass=$((pass+1)); printf '  ok    %s\n' "Claude rejects an ambiguous task answer and records the exact single choice"
else
  fail=$((fail+1)); printf '  FAIL  %s\n' "Claude rejects an ambiguous task answer and records the exact single choice"
fi
rm -rf "$TH"


echo "pre-push does not lend the repository to the verifier"
# A push run from a linked worktree arrives at the hook with GIT_DIR already exported (an
# ordinary push from the primary checkout does not). The verifier called by the hook can run
# suites that create fixture repositories and run git inside them; with GIT_DIR still set they operate
# on the real repository. This is a regression test for damage that actually happened: a fixture
# `git checkout -b` moved the real HEAD and left `deliver/0942`-style branches behind, and a
# fixture `git init` set `core.bare = true`, which hides the working tree from git until
# somebody thinks to look at the flag.
#
# The victim is a linked worktree rather than a plain repository, because that is the shape
# the damage was done to and the only shape that reproduces all of it: a leaked `git init`
# writes `core.bare` into the *shared* config, which a plain-repo victim never exposes. On a
# plain victim the config comparison below is inert — it holds under the unfixed hook — so a
# third of what this test claims to pin would go unproven.
#
# The suites themselves are stubbed here — what is under test is the hook's environment
# hygiene, not the suites, and running them for real would cost minutes and prove nothing
# extra. Each stub does exactly what a fixture does: init, commit and branch in its own
# temp directory.
PP=$(mktemp -d)
PP_MAIN="$PP/main"                                # the primary checkout
PP_WT="$PP/wt"                                    # the linked worktree the hook runs in
mkdir -p "$PP_MAIN"
if ! (
  cd "$PP_MAIN" || exit 1
  git init -q -b main .
  printf 'real\n' > real.txt
  git add -A
  git -c user.email=r@r -c user.name=Real commit -qm "real work"
  git worktree add -q -b wtbranch "$PP_WT"
); then
  printf '  FAIL  %s\n' "pre-push fixture setup succeeds"
  rm -rf "$PP"
  exit 1
fi
mkdir -p "$PP_WT/core/scripts"
cat > "$PP_WT/core/scripts/verify-change.sh" <<'PP_EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s|%s|%s|%s|%s\n' "$1" "$2" "${GIT_DIR:-}" "${GIT_WORK_TREE:-}" "${GIT_PREFIX:-}" >> "$PP_VERIFY_LOG"
d=$(mktemp -d); cd "$d" || exit 1
git init -q -b main . 2>/dev/null
git config user.email test@example.com
git config user.name "Pre-push fixture"
printf 'x\n' > f.txt; git add -A 2>/dev/null
git commit -qm init 2>/dev/null
git checkout -q -b deliver/9999 2>/dev/null
cd /; rm -rf "$d"
[ "${PP_VERIFY_FAIL:-0}" = 0 ]
PP_EOF
chmod +x "$PP_WT/core/scripts/verify-change.sh"
cp integrations/git/pre-push "$PP_WT/pre-push"
chmod +x "$PP_WT/pre-push"
( cd "$PP_WT" && git add -A && git -c user.email=r@r -c user.name=Real commit -qm "install hook fixture" )
PP_VERIFY_LOG="$PP/log"

# HEAD is the worktree's own; refs and config are the shared ones a leak corrupts.
PP_HEAD_BEFORE=$(git -C "$PP_WT" rev-parse HEAD)
PP_REFS_BEFORE=$(git -C "$PP_MAIN" for-each-ref --format='%(refname)' refs/heads/ | LC_ALL=C sort)
PP_CONF_BEFORE=$(git -C "$PP_MAIN" config --local --list | LC_ALL=C sort)
(
  cd "$PP_WT" || exit 1
  printf 'refs/heads/x %s refs/heads/x %s\n' "$PP_HEAD_BEFORE" "$PP_HEAD_BEFORE" \
    | PP_VERIFY_LOG="$PP_VERIFY_LOG" GIT_DIR="$PP_MAIN/.git/worktrees/wt" \
      ./pre-push origin "file://$PP_MAIN" >/dev/null 2>&1
)
PP_RC=$?
PP_HEAD_AFTER=$(git -C "$PP_WT" rev-parse HEAD 2>/dev/null)
PP_REFS_AFTER=$(git -C "$PP_MAIN" for-each-ref --format='%(refname)' refs/heads/ 2>/dev/null | LC_ALL=C sort)
PP_CONF_AFTER=$(git -C "$PP_MAIN" config --local --list 2>/dev/null | LC_ALL=C sort)
if [ "$PP_RC" = 0 ] \
   && [ "$PP_HEAD_AFTER" = "$PP_HEAD_BEFORE" ] \
   && [ "$PP_REFS_AFTER" = "$PP_REFS_BEFORE" ] \
   && [ "$PP_CONF_AFTER" = "$PP_CONF_BEFORE" ] \
   && grep -q '^origin/main|pre-push|||$' "$PP_VERIFY_LOG"; then
  pass=$((pass+1)); printf '  ok    %s\n' "a hook-invoked suite run leaves HEAD, branches and shared config untouched"
else
  fail=$((fail+1)); printf '  FAIL  %s\n' "a hook-invoked suite run leaves HEAD, branches and shared config untouched"
fi

printf 'uncommitted repair\n' > "$PP_WT/real.txt"
: > "$PP_VERIFY_LOG"
if (
  cd "$PP_WT" || exit 1
  printf 'refs/heads/x %s refs/heads/x %s\n' "$PP_HEAD_BEFORE" "$PP_HEAD_BEFORE" \
    | PP_VERIFY_LOG="$PP_VERIFY_LOG" GIT_DIR="$PP_MAIN/.git/worktrees/wt" \
      ./pre-push origin "file://$PP_MAIN" >/dev/null 2>&1
); then
  fail=$((fail+1)); printf '  FAIL  %s\n' "pre-push refuses a dirty repair instead of lending it to pushed HEAD"
elif [ -s "$PP_VERIFY_LOG" ]; then
  fail=$((fail+1)); printf '  FAIL  %s\n' "pre-push refuses a dirty repair before verification"
else
  pass=$((pass+1)); printf '  ok    %s\n' "pre-push refuses a dirty repair before verification"
fi
git -C "$PP_WT" restore real.txt

if (
  cd "$PP_WT" || exit 1
  : > "$PP_VERIFY_LOG"
  printf 'refs/heads/other %s refs/heads/other %s\n' \
    1111111111111111111111111111111111111111 "$PP_HEAD_BEFORE" \
    | PP_VERIFY_LOG="$PP_VERIFY_LOG" GIT_DIR="$PP_MAIN/.git/worktrees/wt" \
      ./pre-push origin "file://$PP_MAIN" >/dev/null 2>&1
); then
  fail=$((fail+1)); printf '  FAIL  %s\n' "pre-push refuses a ref that is not the checked-out HEAD"
elif [ -s "$PP_VERIFY_LOG" ]; then
  fail=$((fail+1)); printf '  FAIL  %s\n' "pre-push refuses a ref that is not the checked-out HEAD before verification"
else
  pass=$((pass+1)); printf '  ok    %s\n' "pre-push refuses a ref that is not the checked-out HEAD"
fi

if (
  cd "$PP_WT" || exit 1
  printf 'refs/heads/x %s refs/heads/x %s\n' "$PP_HEAD_BEFORE" "$PP_HEAD_BEFORE" \
    | PP_VERIFY_LOG="$PP_VERIFY_LOG" PP_VERIFY_FAIL=1 GIT_DIR="$PP_MAIN/.git/worktrees/wt" \
      ./pre-push origin "file://$PP_MAIN" >/dev/null 2>&1
); then
  fail=$((fail+1)); printf '  FAIL  %s\n' "pre-push refuses when the affected verifier fails"
else
  pass=$((pass+1)); printf '  ok    %s\n' "pre-push refuses when the affected verifier fails"
fi
rm -rf "$PP"

# The fixture above catches an unset moved below the steps, and a step hoisted above it. What
# it cannot catch is a list trimmed to `GIT_DIR` alone: one leaked variable already does all
# the damage it measures, so the rest going unset is invisible to it. Pin that by reading the
# source — collect every GIT_* name unset before the first step, and require exactly the set
# the hook is supposed to clear.
PP_WANT=$(printf '%s\n' GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_COMMON_DIR GIT_DIR GIT_INDEX_FILE \
  GIT_NAMESPACE GIT_OBJECT_DIRECTORY GIT_PREFIX GIT_WORK_TREE | LC_ALL=C sort)
PP_GOT=$(awk '
  /^step "/ { exit }                              # only what is cleared before step one counts
  inblk     { print; if ($0 !~ /\\$/) inblk = 0; next }
  /^[[:space:]]*unset[[:space:]]+GIT_/ { print; if ($0 ~ /\\$/) inblk = 1 }
' integrations/git/pre-push | tr -d '\\' | tr '[:blank:]' '\n' | grep '^GIT_' | LC_ALL=C sort -u)
if [ -n "$PP_GOT" ] && [ "$PP_GOT" = "$PP_WANT" ]; then
  pass=$((pass+1)); printf '  ok    %s\n' "pre-push clears the whole inherited git environment before the first step"
else
  fail=$((fail+1)); printf '  FAIL  %s\n' "pre-push clears the whole inherited git environment before the first step"
fi

echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
