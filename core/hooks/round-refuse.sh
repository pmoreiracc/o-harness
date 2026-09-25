#!/usr/bin/env bash
# GUARDRAIL — refuses a review round that would cross the window (ADR-0046 Decision 1).
#
# Fires before invariant-reviewer starts: Claude Code's PreToolUse on Agent, and Codex's
# blocking PreToolUse Agent path. SubagentStart rechecks the same state before allocating the
# attempt. SendMessage to a tracked reviewer is refused because every round must use a newly
# spawned reviewer. The model neither counts rounds nor decides whether to halt; it
# discovers the ceiling by being denied, and the denial names the checkpoint's three option
# labels verbatim so the question the model then asks the human cannot be authored from
# memory (the exact failure this ADR's Context records: a checkpoint offering the wrong label
# burned a human's answer, silently).
#
# This is consumer-validated local workflow evidence, not a clean-checkout CI check: supported
# host hooks write it, while deliberate same-user rewriting is outside ADR-0047's boundary.
# complete.sh's exit 4 stays the backstop for a run where this hook was absent or bypassed —
# never the primary brake.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/lib.sh" || {
  echo "GUARDRAIL CANNOT RUN: core/hooks/lib.sh is missing or unreadable." >&2
  echo "No operation was inspected. Restore this reviewed harness file in the checkout and retry; do not disable the guardrail." >&2
  exit 2
}
hook_init

. "$DIR/../round-ledger.sh" || {
  echo "GUARDRAIL CANNOT RUN: core/round-ledger.sh is missing or unreadable." >&2
  exit 2
}

# Claude Code sends PreToolUse with tool_name "Agent" and tool_input.subagent_type for a
# fresh spawn, or tool_name "SendMessage" for a reused one. Codex's SubagentStart carries no
# tool_name at all, only agent_type at the top level — read the same way review-start.sh
# already does, rather than gating on hook_event_name, whose casing this repository's own
# Codex fixtures do not agree on and which no artifact here actually pins down.
ROOT=$(project_root)
ACTION="the spawn"
TOOL=$(hook_field '.tool_name')
case "$TOOL" in
  Agent)
    AGENT=$(hook_field '.tool_input.subagent_type')
    ;;
  SendMessage)
    # Do not guess which field carries the recipient. Match against every string value
    # anywhere in tool_input — this is what lets an array-valued `to`, an `agent_id` or
    # `teammate_id` field, an "@name" address, or a ref with no separating space all reach
    # the same check a bare `to` does, without enumerating field-name shapes one at a time.
    AGENT=""
    AGENTS_DIR="${OH_STATE_ROOT:-$ROOT/.deliver}/reviewer-agents"
    # A directory that exists but cannot be enumerated (permissions, a mid-command mishap)
    # is not the same fact as "no reviewer has ever been tracked" — treating it that way
    # silently admits a resumed reviewer. `[ -d "$AGENTS_DIR" ]` alone only catches the
    # marker directory's OWN permissions; an unreadable ANCESTOR (`.deliver` itself, say)
    # makes `[ -d ]` fail to stat it at all, which reads as "never existed" — the identical
    # class of bug the round-window check just below already had to be fixed for. Same
    # walker, same reason: every existing ancestor, not just the leaf.
    BAD_ANCESTOR=$(round_ledger_unreadable_ancestor "$AGENTS_DIR")
    if [ -n "$BAD_ANCESTOR" ]; then
      echo "round-refuse: GUARDRAIL CANNOT RUN: $BAD_ANCESTOR exists but cannot be read." >&2
      echo "Failing closed rather than treating an unreadable state as no live reviewer." >&2
      exit 2
    fi
    # A symlink at or below .deliver on the reviewer-agents path redirects the marker read into a
    # tree the attacker controls (`ln -s /tmp/empty .deliver/reviewer-agents`), hiding a live
    # reviewer's marker so a resume is admitted — `[ -d ]`/`find` resolve THROUGH it (round 18).
    # The main-flow guard below cannot catch this: a hidden marker leaves AGENT empty and the hook
    # exits 0 before reaching it, so the check has to sit on this route too.
    BAD_LINK=$(round_ledger_symlinked_component "$ROOT" "$AGENTS_DIR")
    if [ -n "$BAD_LINK" ]; then
      echo "round-refuse: GUARDRAIL CANNOT RUN: $BAD_LINK is a symlink, redirecting the reviewer-" >&2
      echo "identity read into a tree the harness does not own. Failing closed rather than reading" >&2
      echo "through a planted link and admitting a resumed reviewer." >&2
      exit 2
    fi
    if [ -d "$AGENTS_DIR" ] && [ -n "$(find "$AGENTS_DIR" -type f -print -quit 2>/dev/null)" ]; then
      CANDIDATES=$(printf '%s' "$PAYLOAD" | jq -r '[.tool_input | .. | strings] | .[]' 2>/dev/null)
      while IFS= read -r RAW; do
        [ -n "$RAW" ] || continue
        # Strip a "[ref]" disambiguator (with or without a preceding space) and a leading
        # "@", trim surrounding whitespace, and match case-insensitively — the host resolves
        # an address the same ways.
        TARGET="${RAW%%\[*}"
        TARGET="${TARGET#@}"
        TARGET="$(printf '%s' "$TARGET" | tr -d '\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | tr '[:upper:]' '[:lower:]')"
        [ -n "$TARGET" ] || continue
        for f in "$AGENTS_DIR"/*; do
          if [ ! -e "$f" ] && [ ! -L "$f" ]; then
            continue # the glob matched nothing real — an empty directory, not a marker
          fi
          # An entry that exists but is not a regular file — a directory or a dangling
          # symlink standing in where a marker used to be — is not the same fact as an
          # empty directory either. `[ -f ]` alone treats both identically; distinguishing
          # them the way the line above does is what keeps this from being the very
          # "cannot tell = no live reviewer" judgement the unreadable-marker check just
          # below already refuses to make.
          if [ ! -f "$f" ]; then
            echo "round-refuse: GUARDRAIL CANNOT RUN: a reviewer-identity marker exists but" >&2
            echo "is not a regular file. Failing closed rather than treating an unexpected" >&2
            echo "entry as no live reviewer." >&2
            exit 2
          fi
          # An unreadable marker (permissions, a mid-command mishap) is not the same fact
          # as an empty one — `continue`ing past it the same way the empty case does would
          # treat "cannot tell" as "no live reviewer" one level further down than the
          # ancestor walk above already closed.
          if [ ! -r "$f" ]; then
            echo "round-refuse: GUARDRAIL CANNOT RUN: a reviewer-identity marker exists but" >&2
            echo "cannot be read. Failing closed rather than treating an unreadable marker" >&2
            echo "as no live reviewer." >&2
            exit 2
          fi
          RID=$(tr -d '\n' < "$f" | tr '[:upper:]' '[:lower:]')
          [ -n "$RID" ] || continue
          # Exact match, or TARGET is a (host-documented) address prefix of a recorded
          # identity — the safe direction, since a gate that misses this admits an
          # unbounded loop. A short TARGET is exempted from the prefix side: below this
          # length a prefix is too generic to mean anything, and scanning the whole envelope
          # (rather than one named field) already makes short incidental substrings — a
          # word in a message body, say — more likely, so a false refusal there would be
          # frequent rather than rare.
          if [ "$RID" = "$TARGET" ]; then
            AGENT="invariant-reviewer"; break 2
          fi
          if [ "${#TARGET}" -ge 4 ]; then
            case "$RID" in "$TARGET"*) AGENT="invariant-reviewer"; break 2 ;; esac
          fi
        done
      done <<CANDIDATES_EOF
$CANDIDATES
CANDIDATES_EOF
    fi
    ACTION="sending this message"
    ;;
  "")
    AGENT=$(hook_field '.agent_type')
    ;;
  *) exit 0 ;;
esac
[ "$AGENT" = "invariant-reviewer" ] || exit 0

if [ "$TOOL" = SendMessage ]; then
  echo "BLOCKED — every review round requires a newly spawned invariant reviewer." >&2
  echo "This is missing fresh-reviewer admission, not a stale session. Spawn a new reviewer" >&2
  echo "in this same session; the unchanged exact-tree readiness request remains valid." >&2
  exit 2
fi

# review-ready-gate.sh asks this hook to classify the payload instead of maintaining a
# second, inevitably drifting copy of the Agent/SendMessage/SubagentStart route logic.
# No round-window state is read in this mode; stdout is private to the calling hook.
if [ "${ROUND_REFUSE_CLASSIFY_ONLY:-}" = 1 ]; then
  echo invariant-reviewer
  exit 0
fi

BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null)
if [ -z "$BRANCH" ]; then
  echo "round-refuse: GUARDRAIL CANNOT RUN: HEAD could not be resolved, so the review-round" >&2
  echo "window cannot be read. Failing closed rather than allowing an unaccounted round." >&2
  exit 2
fi

if [ "$BRANCH" = HEAD ]; then
  SESSION="${CODEX_SESSION_ID:-$(hook_field '.session_id')}"
  [ -n "$SESSION" ] || SESSION=$(hook_field '.conversation_id')
  review_detached_context_activate_for_session "$ROOT" "$BRANCH" "$SESSION" 1 || {
    echo "round-refuse: detached HEAD requires its explicit review context; no reviewer started." >&2
    exit 2
  }
fi

KEY=$(round_key_for "$ROOT" "$BRANCH") || {
  echo "round-refuse: GUARDRAIL CANNOT RUN: no review-round window key could be derived for" >&2
  echo "$BRANCH. Failing closed rather than allowing an unaccounted round." >&2
  exit 2
}

# Each consumer validates only the evidence paths for this key. Damage elsewhere must not make
# an unrelated review unavailable (ADR-0047), while a symlink or unreadable component on these
# exact paths still fails closed.
LEDGER_DIR=$(round_ledger_dir "$ROOT" "$KEY")
ACCEPTED=$(accepted_rounds_root "$ROOT" "$KEY")
for EVIDENCE_PATH in \
  "$ACCEPTED" \
  "$LEDGER_DIR/grants"; do
  BAD_LINK=$(round_ledger_symlinked_component "$ROOT" "$EVIDENCE_PATH")
  if [ -n "$BAD_LINK" ]; then
    echo "round-refuse: GUARDRAIL CANNOT RUN: $BAD_LINK is a symlink, redirecting the review-round" >&2
    echo "evidence read into a tree the harness does not own. Failing closed rather than reading" >&2
    echo "through a planted link and admitting an unaccounted round." >&2
    echo "" >&2
    echo "Do not retry $ACTION. Hand this to the human: restore .deliver to a real directory tree." >&2
    exit 2
  fi
done
BAD_ANCESTOR=$(round_ledger_unreadable_ancestor "$ACCEPTED") \
  || BAD_ANCESTOR=$(round_ledger_unreadable_ancestor "$LEDGER_DIR/grants")
if [ -n "$BAD_ANCESTOR" ]; then
  echo "round-refuse: GUARDRAIL CANNOT RUN: $BAD_ANCESTOR exists but cannot be read, so" >&2
  echo "the review-round window cannot be read. Failing closed rather than treating an" >&2
  echo "unreadable state as zero rounds used." >&2
  exit 2
fi

USED=$(round_count "$ROOT" "$KEY") || {
  echo "round-refuse: GUARDRAIL CANNOT RUN: accepted-round evidence is malformed or unreadable." >&2
  exit 2
}
round_needs_grant "$ROOT" "$KEY" "$USED"
NEEDS_RC=$?
if [ "$NEEDS_RC" = 2 ]; then
  echo "round-refuse: GUARDRAIL CANNOT RUN: review-grant evidence has an unexpected shape." >&2
  exit 2
fi
if [ "$NEEDS_RC" = 0 ]; then
  WINDOW=$(round_window "$ROOT" "$KEY") || exit 2
  SERIES=$(review_series_find_for_key "$ROOT" "$KEY" 2>/dev/null || true)
  if [ -n "$SERIES" ]; then
    TREE=$(CLAUDE_PROJECT_DIR="$ROOT" "${OH_HOME:-$ROOT}/core/scripts/tree-digest.sh") || exit 2
    review_window_ready "$ROOT" "$SERIES" "$TREE" || exit 2
  fi
  echo "BLOCKED — the next invariant-reviewer round would cross the review window for" >&2
  echo "$KEY: $USED round(s) used, $WINDOW granted (ADR-0046)." >&2
  if [ -n "$SERIES" ]; then
    SOURCE=$(jq -r '.policySource // "default"' "$(review_series_dir "$ROOT" "$SERIES")/series.json" 2>/dev/null)
    echo "Review window snapshot: $WINDOW rounds from $SOURCE policy." >&2
    LATEST=$(review_attempt_latest "$ROOT" "$SERIES" 2>/dev/null || true)
    [ -z "$LATEST" ] || review_attempt_summary "$LATEST" >&2
    echo "Before asking, summarize completed/uncommitted work and checks; recommend the option justified by the unresolved findings." >&2
  fi
  echo "" >&2
  echo "Do not retry $ACTION." >&2
  if [ -n "${CODEX_HOOK:-}" ]; then
    DETAIL=-; [ "$USED" -le "$WINDOW" ] || DETAIL=exceeded
    codex_gate_present review-window "$DETAIL" >&2 || exit 2
  else
    echo "Present one single-select question with exactly these options:" >&2
    [ "$USED" -gt "$WINDOW" ] || printf '%s\n' "$ROUND_GRANT_LABEL" >&2
    printf '%s\n' "$ROUND_STOP_TAKE_OVER_LABEL" "$ROUND_STOP_ESCALATE_LABEL" >&2
  fi
  echo "" >&2
  echo "On the grant option, the host hook records the grant; re-run round-status.sh to" >&2
  echo "confirm the window renewed, then retry. On either Stop, end the run." >&2
  exit 2
fi

exit 0
