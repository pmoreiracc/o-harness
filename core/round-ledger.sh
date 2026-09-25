#!/usr/bin/env bash
# Shared configurable review-window contract (ADRs 0044, 0046, 0051). Sourced, never executed.
#
# Two facts hold this together, and both are derived from committed state or harness-written
# files, never from a number the model reports about itself:
#
#   rounds used   = every immutable attempt start plus valid historical accepted rounds.
#   window        = the series snapshot multiplied by one plus its grants. A grant is written only
#                   by a host's human-input hook: Claude Code's AskUserQuestion PostToolUse
#                   hook or Codex's UserPromptSubmit hook, from the human's real choice.
#
# Both live under .deliver/reviews/. Host hooks are the supported writers; consumers validate
# the exact key and series they use. Deliberate shell forgery is outside that boundary (ADR-0047).
#
# Compatible with bash 3.2 (the macOS default) — no associative arrays, no ${x,,}.

ROUND_LEDGER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$ROUND_LEDGER_DIR/lib.sh" || return 1 2>/dev/null || exit 1
. "$ROUND_LEDGER_DIR/task-ledger.sh" || return 1 2>/dev/null || exit 1
. "$ROUND_LEDGER_DIR/accepted-rounds.sh" || return 1 2>/dev/null || exit 1
. "$ROUND_LEDGER_DIR/review-workflow.sh" || return 1 2>/dev/null || exit 1

# Historical v1/v2 grant validation still needs the pre-ADR-0051 fixed values.
ROUND_WINDOW_BASE=3
ROUND_GRANT_INCREMENT=3

# The exact option label the checkpoint offers for a renewal and the grant hook recognises in
# the human's sole selected answer. One definition so SKILL.md, the hook, and the tests cannot
# drift. Matched against the selected answer only — never the option list — so a question that
# merely *offers* the label does not mint a grant unless it was chosen.
ROUND_LEGACY_GRANT_LABEL="Grant 3 more review rounds"
ROUND_GRANT_LABEL="Grant next review window"

# The other two checkpoint option labels (ADR-0046 Decision 3). Neither writes a grant — both
# end the run — but the refusal hook quotes all three verbatim so the checkpoint the model
# presents is never authored from memory.
ROUND_STOP_TAKE_OVER_LABEL="Stop and take it over"
ROUND_STOP_ESCALATE_LABEL="Stop and escalate to the PR"
ROUND_GRANT_COMMAND="grant next review window"
ROUND_STOP_TAKE_OVER_COMMAND="stop and take it over"
ROUND_STOP_ESCALATE_COMMAND="stop and escalate to the pr"

round_state_root() {
  printf '%s/round-state' "$(review_series_state_root "$1")"
}

# round_task_key <doc> <task> — the per-task ledger key. Task numbers are unique across a
# design doc (plan.sh numbers them per doc, tracks only partition them), so the track is not
# needed to disambiguate — which is what lets complete.sh, told only <doc> <task>, address
# the same ledger the branch-aware hooks write.
round_task_key() {
  printf '%s-t%s' "$1" "$2"
}

# round_ledger_dir <root> <key>
round_ledger_dir() {
  printf '%s/%s' "$(round_state_root "$1")" "$2"
}

# round_ledger_unreadable_ancestor <path> — echoes the first existing ancestor of <path>
# (from the filesystem root down, inclusive of <path> itself) that is not both readable and
# executable, and exits 0; exits 1 and prints nothing when every existing ancestor can be
# traversed. round_count/round_grants_count fall back to "0" whenever their directory
# cannot be stat'd at all (round_ledger_dir()/rounds or /grants) — indistinguishable from a
# directory that legitimately never existed, since `[ -d ]` on a deep path fails to stat it
# at all when ANY ancestor blocks traversal, not just when the leaf itself is missing. A
# caller that must not treat "cannot tell" as "zero" (round-refuse.sh) checks every
# ancestor of the exact leaf those functions read — not a fixed number of levels, since a
# non-delivery key (ADR-0046 Decision 2) is a branch name, which may itself contain any
# number of "/" segments — because `[ -d ]` on an ancestor still succeeds even when the
# ancestor itself is unreadable (stat only needs execute on ITS OWN parent).
round_ledger_unreadable_ancestor() {
  local target="$1" prefix rest comp
  case "$target" in
    /*) prefix="/" ; rest="${target#/}" ;;
    *)  prefix=""  ; rest="$target" ;;
  esac
  while [ -n "$rest" ]; do
    comp="${rest%%/*}"
    if [ "$comp" = "$rest" ]; then rest=""; else rest="${rest#*/}"; fi
    if [ "$prefix" = "/" ]; then prefix="/$comp"
    elif [ -z "$prefix" ]; then prefix="$comp"
    else prefix="$prefix/$comp"
    fi
    if [ -d "$prefix" ] && { [ ! -r "$prefix" ] || [ ! -x "$prefix" ]; }; then
      printf '%s' "$prefix"
      return 0
    fi
  done
  return 1
}

# round_ledger_symlinked_component <root> <path> — echo the first component of <path> AT OR
# BELOW <root> that is a symlink, and exit 0; exit 1 and print nothing when there is none.
#
# A symlink planted on the in-repo path to the evidence — `ln -s /tmp/fake .deliver`, or a link
# at `.deliver/reviews`, or mid-key — redirects every read that follows it into a tree the
# attacker controls, and `[ -d ]`/`-r`/`-x` all PASS because they resolve THROUGH the link
# (round 18 finding). round_ledger_unreadable_ancestor cannot see this: an unreadable dir and a
# link to a usable one look identical to it. Components ABOVE <root> are outside harness control
# (macOS /tmp and /var are themselves symlinks, and every test sandbox lives under one), so they
# are deliberately not checked — only the harness-owned tail from <root> down.
round_ledger_symlinked_component() {
  local root="$1" path="$2" rel comp acc
  if [ -n "${OH_STATE_ROOT:-}" ]; then
    case "$path" in "$OH_STATE_ROOT"|"$OH_STATE_ROOT"/*) root="$(dirname "$OH_STATE_ROOT")" ;; esac
  fi
  case "$path" in
    "$root"/*) rel="${path#"$root"/}" ;;
    *) return 1 ;;
  esac
  acc="$root"
  while [ -n "$rel" ]; do
    comp="${rel%%/*}"
    if [ "$comp" = "$rel" ]; then rel=""; else rel="${rel#*/}"; fi
    acc="$acc/$comp"
    if [ -L "$acc" ]; then printf '%s' "$acc"; return 0; fi
  done
  return 1
}

# round_branch_parse <branch> — echo "<doc>\t<track>" for a deliver/<doc>[-<track>] branch;
# return 1 for anything else. The track may be empty (single-track doc).
round_branch_parse() {
  delivery_branch_parse "$1"
}

# round_recovery_task <root> <doc> <owner> <tsv>
# During Recover, complete.sh has already ticked the reviewed task in the working tree but
# has not committed it yet. That one pending -> done transition is stronger attribution than
# the next runnable task in the edited doc. Recognise only one exact transition and only when
# it belongs to this track; ambiguity fails back to the ordinary runnable-task derivation.
round_recovery_task() {
  local root="$1" doc="$2" owner="$3" tsv="$4" file diff transitions task task_owner
  file=$(task_design_file "$root" "$doc") || return 2
  # Status 1 means the tree is not at the exact recovery boundary and may use ordinary
  # runnable-task attribution. Status 2 means the boundary could not be inspected; callers
  # must fail closed instead of silently attributing the review to the following task.
  diff=$(git -C "$root" diff --text --unified=0 --no-ext-diff HEAD -- "$file" 2>/dev/null) || return 2
  transitions=$(task_transition_records_from_diff "$diff") || return 2
  case "$transitions" in
    done$'\t'[0-9]*) task="${transitions#*$'\t'}" ;;
    *) return 1 ;;
  esac
  case "$task" in ""|*[!0-9]*) return 1 ;; esac
  task_owner=$(printf '%s\n' "$tsv" | awk -F"$TASK_US" -v n="$task" '$1==n {print $3; exit}') || return 2
  [ "$task_owner" = "$owner" ] || return 1
  printf '%s' "$task"
}

# round_current_key <root> <branch> — the ledger key for the task a delivery run is working
# right now, or return 1 when there is none (not a delivery branch, or every task is done and
# the run is finalising). The task is whatever next.sh would hand the loop — the single source
# of truth for "what may I start" — so the key a review round is filed under is exactly the
# key complete.sh will read for that task. Never a number the model chooses.
round_current_key() {
  local root="$1" branch="$2" dir parsed parse_status doc track tsv pending_count file rel transitions
  local trusted_tsv out task status
  dir="${OH_HOME:-$root}/core/scripts"
  parsed=$(round_branch_parse "$branch")
  parse_status=$?
  if [ "$parse_status" -ne 0 ]; then
    case "$branch" in deliver/*) return 2 ;; *) return 1 ;; esac
  fi
  doc="${parsed%%$'\t'*}"
  track="${parsed#*$'\t'}"
  tsv=$(CLAUDE_PROJECT_DIR="$root" "$dir/plan.sh" "$doc" 2>/dev/null) || return 2
  TASK_US=$(printf '\037')
  pending_count=$(printf '%s\n' "$tsv" | awk -F"$TASK_US" '$2 == "pending" {n++} END {print n+0}') || return 2
  # A committed all-done tree has no task in flight and belongs to Finalize. Preserve the
  # interrupted-final-task recovery path by continuing only when the worktree still carries
  # a real checkbox transition; non-task finalization edits do not manufacture a task key.
  if [ "$pending_count" -eq 0 ]; then
    file=$(task_design_file "$root" "$doc") || return 2
    rel="${file#"$root"/}"
    transitions=$(task_worktree_transition_ids "$root" "$rel") || return 2
    [ -n "$transitions" ] || return 1
  fi
  task_authority_load "$root" "$branch" "$doc" "$tsv" || return 2
  trusted_tsv="$TASK_AUTHORITY_TRUSTED_TSV"
  track="$TASK_AUTHORITY_OWNER"
  # Review attribution follows the exact uncommitted completion during Recover. Otherwise it
  # follows canonical runnable selection. Neither path re-runs next.sh's admission gate: the
  # task is already in flight when it is reviewed.
  task=$(round_recovery_task "$root" "$doc" "$track" "$trusted_tsv" 2>/dev/null)
  status=$?
  case "$status" in
    0) ;;
    1) task="" ;;
    *) return 2 ;;
  esac
  if [ -z "$task" ]; then
    out=$(task_first_runnable "$trusted_tsv" "$track" "")
    status=$?
    case "$status" in 0) ;; 1) return 1 ;; *) return 2 ;; esac
    task="${out%%"$TASK_US"*}"
  fi
  case "$task" in ""|*[!0-9]*) return 2 ;; esac
  round_task_key "$doc" "$task"
}

# round_finalization_key <root> <branch> — the shared key for a delivery branch whose
# canonical gate says only finalization/recovery remains. Readiness, receipts and the
# renewable review window must all use this identity; falling back to nd/<branch>/<HEAD>
# would make accepted <doc>-finalize rounds invisible to the refusal and grant paths.
round_finalization_key() {
  local root="$1" branch="$2" parsed parse_status doc track out rc
  parsed=$(round_branch_parse "$branch")
  parse_status=$?
  if [ "$parse_status" -ne 0 ]; then
    case "$branch" in deliver/*) return 2 ;; *) return 1 ;; esac
  fi
  doc="${parsed%%$'\t'*}"
  track="${parsed#*$'\t'}"
  out=$(CLAUDE_PROJECT_DIR="$root" "${OH_HOME:-$root}/core/scripts/next.sh" "$doc" ${track:+"$track"} 2>/dev/null)
  rc=$?
  case "$rc" in
    6|7) printf '%s-finalize' "$doc" ;;
    3) return 1 ;;
    *) return 2 ;;
  esac
}

# round_key_for <root> <branch> — the ledger key for the window that gates the NEXT
# invariant-reviewer round, wherever the run is (ADR-0046 Decision 2). On a delivery branch
# with a task in flight this is round_current_key's per-task key, unchanged. Everywhere else,
# an explicit series follows the canonical branch incarnation across commits and amendments
# until a clean, resolved, takeover, or PR-handoff transition closes it.
round_key_for() {
  local root="$1" branch="$2" key status
  key=$(round_current_key "$root" "$branch" 2>/dev/null)
  status=$?
  case "$status" in 0) printf '%s' "$key"; return 0 ;; 1) ;; *) return 1 ;; esac
  key=$(round_finalization_key "$root" "$branch" 2>/dev/null)
  status=$?
  case "$status" in 0) printf '%s' "$key"; return 0 ;; 1) ;; *) return 1 ;; esac
  review_series_key_for "$root" "$branch"
}

# round_count <root> <key> — rounds used by this exact key.
round_count() {
  local root="$1" key="$2" rounds legacy=0 series attempts=0 status
  rounds=$(accepted_rounds_list "$root" "$key" 2>/dev/null) || return 1
  legacy=$(printf '%s\n' "$rounds" | awk 'NF { n++ } END { print n + 0 }')
  series=$(review_series_find_for_key "$root" "$key" 2>/dev/null)
  status=$?
  case "$status" in
    0) attempts=$(review_attempt_count "$root" "$series") || return 1 ;;
    1) attempts=0 ;;
    *) return 1 ;;
  esac
  printf '%s' "$((legacy + attempts))"
}

# round_grant_validate_v1 <key> <path> <sequence> — validate the original host-hook shape.
# A numbered regular file is not itself accepted workflow evidence: every binding and every
# arithmetic claim the host writer emits must agree before it can widen the window.
round_grant_validate_v1() {
  local key="$1" entry="$2" sequence="$3" doc task before after extra
  local l1 l2 l3 l4 l5 l6 l7 l8 l9 l10 l11 l12 l13 l14
  doc="${key%-t*}"
  task="${key#*-t}"
  before=$(( ROUND_WINDOW_BASE + ROUND_GRANT_INCREMENT * (sequence - 1) ))
  after=$(( before + ROUND_GRANT_INCREMENT ))
  if ! {
    IFS= read -r l1 && IFS= read -r l2 && IFS= read -r l3 && IFS= read -r l4 \
      && IFS= read -r l5 && IFS= read -r l6 && IFS= read -r l7 && IFS= read -r l8 \
      && IFS= read -r l9 && IFS= read -r l10 && IFS= read -r l11 && IFS= read -r l12 \
      && IFS= read -r l13 && IFS= read -r l14 && ! IFS= read -r extra
  } < "$entry"; then
    return 1
  fi
  [ "$l1" = "grant-version: 1" ] \
    && [ "$l2" = "doc: $doc" ] \
    && [ "$l3" = "task: $task" ] \
    && [ "$l4" = "sequence: $sequence" ] \
    && [ "$l5" = "rounds-at-grant: $before" ] \
    && [ "$l6" = "window-before: $before" ] \
    && [ "$l7" = "window-after: $after" ] \
    && printf '%s\n' "$l8" | grep -Eq '^tree: [0-9a-f]{16}$' \
    && printf '%s\n' "$l9" | grep -Eq '^at: [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' \
    && [ "$l10" = "granted-by: human — selected \"$ROUND_LEGACY_GRANT_LABEL\" at the round-ceiling checkpoint" ] \
    && [ "$l11" = "---" ] \
    && [ "$l12" = "The human answered the fixed-shape checkpoint and renewed the review window by" ] \
    && [ "$l13" = "$ROUND_GRANT_INCREMENT rounds (window $before → $after). This record is the" ] \
    && [ "$l14" = "workflow evidence complete.sh consumes; model prose is not a grant." ]
}

round_grant_id_valid() {
  printf '%s\n' "$1" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$'
}

round_grant_source_valid() {
  local source="$1" prefix session message client extra
  IFS=: read -r prefix session message client extra <<EOF
$source
EOF
  if [ "$prefix" = codex ]; then
    [ -z "$client$extra" ] && printf '%s\n' "$session:$message" | grep -Eq '^[A-Za-z0-9_-]+:[A-Za-z0-9_-]+$'
    return
  fi
  [ "$prefix" = codex-desktop ] && [ -z "$extra" ] \
    && printf '%s\n' "$session" | grep -Eq '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$' \
    && round_grant_id_valid "$message" && round_grant_id_valid "$client"
}

# v2 differs only by binding one direct Desktop host message between the timestamp and the
# unchanged canonical human-provenance line. Existing v1 grants remain byte-exact evidence.
round_grant_validate_v2() {
  local key="$1" entry="$2" sequence="$3" doc task before after extra
  local l1 l2 l3 l4 l5 l6 l7 l8 l9 l10 l11 l12 l13 l14 l15
  doc="${key%-t*}"
  task="${key#*-t}"
  before=$(( ROUND_WINDOW_BASE + ROUND_GRANT_INCREMENT * (sequence - 1) ))
  after=$(( before + ROUND_GRANT_INCREMENT ))
  if ! {
    IFS= read -r l1 && IFS= read -r l2 && IFS= read -r l3 && IFS= read -r l4 \
      && IFS= read -r l5 && IFS= read -r l6 && IFS= read -r l7 && IFS= read -r l8 \
      && IFS= read -r l9 && IFS= read -r l10 && IFS= read -r l11 && IFS= read -r l12 \
      && IFS= read -r l13 && IFS= read -r l14 && IFS= read -r l15 \
      && ! IFS= read -r extra
  } < "$entry"; then
    return 1
  fi
  [ "$l1" = "grant-version: 2" ] \
    && [ "$l2" = "doc: $doc" ] \
    && [ "$l3" = "task: $task" ] \
    && [ "$l4" = "sequence: $sequence" ] \
    && [ "$l5" = "rounds-at-grant: $before" ] \
    && [ "$l6" = "window-before: $before" ] \
    && [ "$l7" = "window-after: $after" ] \
    && printf '%s\n' "$l8" | grep -Eq '^tree: [0-9a-f]{16}$' \
    && printf '%s\n' "$l9" | grep -Eq '^at: [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' \
    && round_grant_source_valid "${l10#source-message: }" \
    && [ "$l10" = "source-message: ${l10#source-message: }" ] \
    && [ "$l11" = "granted-by: human — selected \"$ROUND_LEGACY_GRANT_LABEL\" at the round-ceiling checkpoint" ] \
    && [ "$l12" = "---" ] \
    && [ "$l13" = "The human answered the fixed-shape checkpoint and renewed the review window by" ] \
    && [ "$l14" = "$ROUND_GRANT_INCREMENT rounds (window $before → $after). This record is the" ] \
    && [ "$l15" = "workflow evidence complete.sh consumes; model prose is not a grant." ]
}

round_grant_validate() {
  case "$(sed -n '1p' "$2" 2>/dev/null)" in
    'grant-version: 1') round_grant_validate_v1 "$@" ;;
    'grant-version: 2') round_grant_validate_v2 "$@" ;;
    'grant-version: 3') round_grant_validate_v3 "$@" ;;
    *) return 1 ;;
  esac
}

round_grant_validate_v3() {
  local key="$1" entry="$2" sequence="$3" series increment before after used source label at tree root
  [ "$(wc -l < "$entry" | tr -d '[:space:]')" = 13 ] || return 1
  [ "$(sed -n '1p' "$entry")" = 'grant-version: 3' ] || return 1
  [ "$(sed -n '2s/^sequence: //p' "$entry")" = "$sequence" ] || return 1
  [ "$(sed -n '3s/^round-key: //p' "$entry")" = "$key" ] || return 1
  series=$(sed -n '4s/^series-id: //p' "$entry")
  increment=$(sed -n '5s/^window-increment: //p' "$entry")
  used=$(sed -n '6s/^rounds-at-grant: //p' "$entry")
  before=$(sed -n '7s/^window-before: //p' "$entry")
  after=$(sed -n '8s/^window-after: //p' "$entry")
  tree=$(sed -n '9s/^tree: //p' "$entry")
  at=$(sed -n '10s/^at: //p' "$entry")
  source=$(sed -n '11s/^source-message: //p' "$entry")
  label=$(sed -n '12s/^granted-by: human — selected "\(.*\)" at the round-ceiling checkpoint$/\1/p' "$entry")
  [ "$(sed -n '13p' "$entry")" = '---' ] || return 1
  case "$increment:$used:$before:$after" in *[!0-9:]*|:*|*:) return 1 ;; esac
  [ "$increment" -gt 0 ] && [ "$after" -eq $((before + increment)) ] && [ "$used" -eq "$before" ] || return 1
  printf '%s' "$tree" | grep -Eq '^[0-9a-f]{16}$' || return 1
  printf '%s' "$at" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}T' || return 1
  [ "$label" = "$ROUND_GRANT_LABEL" ] || return 1
  [ "$source" = hook ] || round_grant_source_valid "$source" || return 1
  root="${OH_PROJECT_ROOT:-${entry%%/.deliver/*}}"
  [ "$series" = "$(review_series_find_for_key "$root" "$key" 2>/dev/null)" ] || return 1
  [ "$increment" = "$(review_series_window "$root" "$series" 2>/dev/null)" ] || return 1
}

round_grants_count_dir() {
  local key="$1" dir="$2" n entry name i
  if [ -e "$dir" ] || [ -L "$dir" ]; then
    [ -d "$dir" ] && [ ! -L "$dir" ] || return 1
  else
    printf '0'; return 0
  fi
  n=0
  for entry in "$dir"/*; do
    [ -e "$entry" ] || [ -L "$entry" ] || continue
    [ -f "$entry" ] && [ ! -L "$entry" ] || return 1
    name="${entry##*/}"
    printf '%s\n' "$name" | grep -Eq '^[1-9][0-9]*\.grant$' || return 1
    n=$(( n + 1 ))
  done
  i=1
  while [ "$i" -le "$n" ]; do
    [ -f "$dir/$i.grant" ] && [ ! -L "$dir/$i.grant" ] || return 1
    round_grant_validate "$key" "$dir/$i.grant" "$i" || return 1
    i=$(( i + 1 ))
  done
  printf '%s' "$n"
}

# round_grants_count <root> <key> — grants recorded this task.
round_grants_count() {
  local dir
  dir="$(round_ledger_dir "$1" "$2")/grants"
  round_grants_count_dir "$2" "$dir"
}

round_grant_source_unused_state() {
  local grants="$1" source="$2" entry line
  if [ -e "$grants" ] || [ -L "$grants" ]; then
    [ -d "$grants" ] && [ ! -L "$grants" ] || return 1
  else
    return 0
  fi
  [ -z "$(find "$grants" -mindepth 1 -maxdepth 1 -type l -print -quit 2>/dev/null)" ] || return 1
  for entry in "$grants"/*; do
    [ -e "$entry" ] || [ -L "$entry" ] || continue
    [ -f "$entry" ] && [ ! -L "$entry" ] || return 1
    case "$(sed -n '1p' "$entry" 2>/dev/null)" in
      'grant-version: 3') line=11 ;;
      *) line=10 ;;
    esac
    [ "$(sed -n "${line}s/^source-message: //p" "$entry" 2>/dev/null)" != "$source" ] || return 1
  done
  return 0
}

# A source identity is one-shot within the exact review key it grants. The Desktop adapter
# accepts it only as the immediate transition after the direct human message and derives the
# current key and tree at publication; unrelated-key damage must not make this key unavailable
# (ADR-0047).
round_grant_source_unused() {
  round_grant_source_unused_state "$(round_ledger_dir "$1" "$2")/grants" "$3"
}

# round_window <root> <key> — the number of rounds currently permitted for this task.
round_window() {
  local grants series base
  grants=$(round_grants_count "$1" "$2") || return 1
  series=$(review_series_find_for_key "$1" "$2" 2>/dev/null) || series=""
  if [ -n "$series" ]; then
    base=$(review_series_window "$1" "$series") || return 1
  else
    review_policy_load "$1" || return 1
    base="$REVIEW_POLICY_ROUNDS"
  fi
  printf '%s' "$(( base + base * grants ))"
}

# round_needs_grant <root> <key> <rounds-used> — 0 (true) when the NEXT round would exceed the
# window and so needs a grant first; 1 (false) otherwise. A round R is permitted when
# R <= window; after `used` rounds the next is used+1, which needs a grant exactly when
# used >= window.
round_needs_grant() {
  local window
  window=$(round_window "$1" "$2") || return 2
  [ "$3" -ge "$window" ]
}

round_series_for_grant() {
  local root="$1" key="$2" series branch
  series=$(review_series_find_for_key "$root" "$key" 2>/dev/null) && { printf '%s' "$series"; return; }
  review_policy_load "$root" || return 1
  branch=$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null) || return 1
  review_series_ensure "$root" "$branch" "$REVIEW_POLICY_ROUNDS" invariant-reviewer "$key"
}

# round_grant_add <root> <key> <digest> <rounds-used> <window-before> <selected-label> —
# append one grant record (invariant-6 shape). Numbered so successive renewals accumulate;
# the count IS the window arithmetic. Writer is the harness (the grant hook), never the model.
round_grant_add() {
  local root="$1" key="$2" digest="$3" used="$4" before="$5" label="$6"
  local dir n after tmp series increment
  series=$(round_series_for_grant "$root" "$key") || return 1
  review_window_ready "$root" "$series" "$digest" || return 1
  increment=$(review_series_window "$root" "$series") || return 1
  dir="$(round_ledger_dir "$root" "$key")/grants"
  mkdir -p "$dir" || return 1
  n=$(round_grants_count "$root" "$key") || return 1
  n=$(( n + 1 ))
  after=$(( before + increment ))
  tmp="$dir/.grant-$n.$$"
  {
    echo "grant-version: 3"
    echo "sequence: $n"
    echo "round-key: $key"
    echo "series-id: $series"
    echo "window-increment: $increment"
    echo "rounds-at-grant: $used"
    echo "window-before: $before"
    echo "window-after: $after"
    echo "tree: $digest"
    echo "at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "source-message: hook"
    echo "granted-by: human — selected \"$label\" at the round-ceiling checkpoint"
    echo "---"
  } > "$tmp" || { rm -f "$tmp"; return 1; }
  [ ! -e "$dir/$n.grant" ] && [ ! -L "$dir/$n.grant" ] || { rm -f "$tmp"; return 1; }
  # Hard-link publication is an atomic no-replace operation, so concurrent writers cannot
  # overwrite the same sequence.
  ln "$tmp" "$dir/$n.grant" 2>/dev/null || { rm -f "$tmp"; return 1; }
  rm -f "$tmp" || { rm -f "$dir/$n.grant"; return 1; }
  if ! { [ -f "$dir/$n.grant" ] && [ ! -L "$dir/$n.grant" ]; }; then
    rm -f "$dir/$n.grant" 2>/dev/null || true
    return 1
  fi
}

# Transcript-backed Desktop publication. The source id is matched again to the direct host message by the Bash
# post-hook; this writer retains the v1 arithmetic, prose and no-replace publication rules.
round_grant_add_v2() {
  local root="$1" key="$2" digest="$3" used="$4" before="$5" source="$6"
  local dir n after tmp series increment
  round_grant_source_valid "$source" || return 1
  round_grant_source_unused "$root" "$key" "$source" || return 1
  series=$(round_series_for_grant "$root" "$key") || return 1
  review_window_ready "$root" "$series" "$digest" || return 1
  increment=$(review_series_window "$root" "$series") || return 1
  dir="$(round_ledger_dir "$root" "$key")/grants"
  mkdir -p "$dir" || return 1
  n=$(round_grants_count "$root" "$key") || return 1
  n=$(( n + 1 ))
  after=$(( before + increment ))
  tmp="$dir/.grant-$n.$$"
  {
    echo "grant-version: 3"
    echo "sequence: $n"
    echo "round-key: $key"
    echo "series-id: $series"
    echo "window-increment: $increment"
    echo "rounds-at-grant: $used"
    echo "window-before: $before"
    echo "window-after: $after"
    echo "tree: $digest"
    echo "at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "source-message: $source"
    echo "granted-by: human — selected \"$ROUND_GRANT_LABEL\" at the round-ceiling checkpoint"
    echo "---"
  } > "$tmp" || { rm -f "$tmp"; return 1; }
  round_grant_validate "$key" "$tmp" "$n" || { rm -f "$tmp"; return 1; }
  [ ! -e "$dir/$n.grant" ] && [ ! -L "$dir/$n.grant" ] || { rm -f "$tmp"; return 1; }
  ln "$tmp" "$dir/$n.grant" 2>/dev/null || { rm -f "$tmp"; return 1; }
  rm -f "$tmp" || { rm -f "$dir/$n.grant"; return 1; }
  [ -f "$dir/$n.grant" ] && [ ! -L "$dir/$n.grant" ]
}
