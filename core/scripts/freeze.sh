#!/usr/bin/env bash
# Freeze a design doc exactly when its last task is complete.
#
# Usage:  freeze.sh <design-doc-number>
#
# Exit 0  tasks remain (no-op), frozen now, or already frozen correctly
# Exit 1  malformed state, no unique roadmap owner, or an invalid lifecycle transition
# Exit 5  no authorized review outcome for the current tree
#
# freeze_render and freeze_diff_validate are deliberately pure: complete.sh shares them,
# but only review-authorized wrappers replace a repository file. Sourcing this file therefore
# exposes no alternate supported workflow path around the review gate (ADR-0047).
set -uo pipefail

freeze_render() (
  set -uo pipefail
  local dir root doc_num task file state us type status delivered pending task_state
  local pending_after roadmap milestones milestone_count collapsed milestone pointers
  local pointer_count pointer_milestone fm status_count verified_count delivered_count
  local today do_tick freeze_now pending_marker done_marker

  dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  root="${CLAUDE_PROJECT_DIR:-$(cd "$dir/../.." && pwd)}"
  doc_num="${1:-}"
  task="${2:-}"

  . "${OH_HOME:-$root}/core/lib.sh" || {
    echo "freeze.sh: core/lib.sh is missing or unreadable." >&2
    exit 1
  }
  case "$doc_num" in
    [0-9][0-9][0-9][0-9]) ;;
    *) echo "usage: freeze.sh <four-digit-design-doc-number>" >&2; exit 1 ;;
  esac
  case "$task" in ""|*[!0-9]*) [ -z "$task" ] || {
    echo "freeze.sh: completion task must be numeric." >&2; exit 1; } ;; esac

  file=$(ls "$root/docs/design/$doc_num"-*.md 2>/dev/null | head -1)
  if [ -z "$file" ] || [ ! -f "$file" ]; then
    echo "freeze.sh: no design doc matching docs/design/$doc_num-*.md" >&2
    exit 1
  fi
  state=$(CLAUDE_PROJECT_DIR="$root" "$dir/plan.sh" "$doc_num" 2>&1)
  if [ $? -ne 0 ]; then
    echo "freeze.sh: $(basename "$file") does not have a valid task list." >&2
    printf '%s\n' "$state" | sed 's/^/  /' >&2
    exit 1
  fi
  us=$(printf '\037')
  type=$(fm_value "$file" "type")
  status=$(fm_value "$file" "status")
  delivered=$(fm_value "$file" "delivered")
  [ "$type" = design ] || {
    echo "freeze.sh: $(basename "$file") has type '${type:-missing}', not 'design'." >&2
    exit 1
  }

  pending=$(printf '%s\n' "$state" | awk -F"$us" '$2 == "pending" {print $1}')
  task_state=""
  do_tick=0
  if [ -n "$task" ]; then
    task_state=$(printf '%s\n' "$state" | awk -F"$us" -v t="$task" '$1 == t {print $2}')
    [ -n "$task_state" ] || {
      echo "freeze.sh: no task $task in $(basename "$file")." >&2
      exit 1
    }
    if [ "$task_state" = pending ]; then do_tick=1; fi
  fi

  pending_after="$pending"
  if [ "$do_tick" = 1 ]; then
    pending_after=$(printf '%s\n' "$state" \
      | awk -F"$us" -v t="$task" '$2 == "pending" && $1 != t {print $1}')
  fi

  if [ "$status" = approved ] && [ -n "$delivered" ]; then
    echo "freeze.sh: approved design doc $doc_num already carries delivered: $delivered." >&2
    echo "Only a frozen design doc may claim delivery." >&2
    exit 1
  fi
  if [ "$status" = frozen ] && [ -n "$pending" ]; then
    echo "freeze.sh: frozen design doc $doc_num still has pending tasks." >&2
    exit 1
  fi
  case "$status" in
    approved|frozen) ;;
    *)
      echo "freeze.sh: design doc $doc_num is '${status:-missing a status}', not 'approved'." >&2
      echo "Only an approved, complete design doc can be frozen." >&2
      exit 1
      ;;
  esac

  freeze_now=0
  milestone=""
  if [ "$status" = approved ] && [ -z "$pending_after" ]; then freeze_now=1; fi
  if [ "$freeze_now" = 1 ] || [ "$status" = frozen ]; then
    roadmap=$(CLAUDE_PROJECT_DIR="$root" "$dir/roadmap.sh" 2>&1)
    if [ $? -ne 0 ]; then
      echo "freeze.sh: the roadmap does not parse, so the delivering milestone is unknown." >&2
      printf '%s\n' "$roadmap" | sed 's/^/  /' >&2
      exit 1
    fi
    milestones=$(printf '%s\n' "$roadmap" \
      | awk -F"$us" -v n="$doc_num" '$4 == n {print $2}')
    milestone_count=$(printf '%s\n' "$milestones" | grep -c .)
    collapsed=$(CLAUDE_PROJECT_DIR="$root" "$dir/roadmap.sh" --delivered 2>&1)
    if [ $? -ne 0 ]; then
      echo "freeze.sh: collapsed milestone pointers do not parse." >&2
      printf '%s\n' "$collapsed" | sed 's/^/  /' >&2
      exit 1
    fi

    if [ "$status" = approved ]; then
      if [ "$milestone_count" -ne 1 ]; then
        echo "freeze.sh: design doc $doc_num must be named by exactly one roadmap row; found $milestone_count." >&2
        echo "The roadmap row is the authority for the delivering milestone." >&2
        exit 1
      fi
      milestone=$(printf '%s\n' "$milestones" | head -1)
    else
      case "$milestone_count" in
        0)
          pointers=$(printf '%s\n' "$collapsed" \
            | awk -F"$us" -v n="$doc_num" '$1 == n {print $2}')
          pointer_count=$(printf '%s\n' "$pointers" | grep -c .)
          pointer_milestone=$(printf '%s\n' "$pointers" | head -1)
          if [ "$pointer_count" -ne 1 ] || [ "$delivered" != "$pointer_milestone" ]; then
            echo "freeze.sh: frozen design doc $doc_num has no matching roadmap row or collapsed milestone pointer." >&2
            exit 1
          fi
          milestone="$delivered"
          ;;
        1) milestone=$(printf '%s\n' "$milestones" | head -1) ;;
        *)
          echo "freeze.sh: frozen design doc $doc_num is named by $milestone_count roadmap rows; expected one." >&2
          exit 1
          ;;
      esac
      if [ "$delivered" != "$milestone" ]; then
        echo "freeze.sh: design doc $doc_num says delivered: '${delivered:-missing}', but its roadmap record is in $milestone." >&2
        exit 1
      fi
    fi
  fi

  if [ "$freeze_now" = 1 ]; then
    fm=$(frontmatter "$file")
    status_count=$(printf '%s\n' "$fm" | grep -c '^status:')
    verified_count=$(printf '%s\n' "$fm" | grep -c '^last-verified:')
    delivered_count=$(printf '%s\n' "$fm" | grep -c '^delivered:')
    if [ "$status_count" -ne 1 ] || [ "$verified_count" -ne 1 ] || [ "$delivered_count" -ne 0 ]; then
      echo "freeze.sh: $(basename "$file") has ambiguous lifecycle frontmatter." >&2
      echo "Expected one status, one last-verified, and no delivered field before freezing." >&2
      exit 1
    fi
  fi

  today=$(date +%F)
  pending_marker="- [ ] **$task.**"
  done_marker="- [x] **$task.**"
  awk -v milestone="$milestone" -v today="$today" -v freeze="$freeze_now" \
      -v tick="$do_tick" -v pending="$pending_marker" -v done="$done_marker" '
    NR == 1 && $0 == "---" { in_frontmatter = 1; print; next }
    in_frontmatter && $0 == "---" { in_frontmatter = 0; print; next }
    freeze && in_frontmatter && /^status:[[:space:]]*/ {
      print "status: frozen"
      print "delivered: " milestone
      next
    }
    freeze && in_frontmatter && /^last-verified:[[:space:]]*/ {
      print "last-verified: " today
      next
    }
    tick && index($0, pending) == 1 {
      print done substr($0, length(pending) + 1)
      next
    }
    { print }
  ' "$file"
)

# Inspect only; callers still own their review gate and atomic replacement.
freeze_diff_validate() {
  local before="$1" after="$2" old_task="${3:-}" new_task="${4:-}"
  local output status changes offending
  output=$(diff -U0 "$before" "$after" 2>/dev/null)
  status=$?
  case "$status" in 0|1) ;; *)
    echo "freeze.sh: could not inspect the proposed lifecycle edit. Aborted." >&2
    return 1
  esac
  changes=$(printf '%s\n' "$output" | grep -E '^[+-]' | grep -vE '^(---|\+\+\+)' || :)
  offending=$(printf '%s\n' "$changes" \
    | grep -vE '^[+-](status: (approved|frozen)|delivered: M[0-9]+|last-verified: [0-9]{4}-[0-9]{2}-[0-9]{2})$' \
    || :)
  if [ -n "$old_task" ]; then
    offending=$(printf '%s\n' "$offending" \
      | grep -vFx -- "-$old_task" | grep -vFx -- "+$new_task" || :)
  fi
  if [ -n "$offending" ]; then
    echo "freeze.sh: the lifecycle edit would change unexpected content. Aborted." >&2
    printf '%s\n' "$offending" | sed 's/^/  /' >&2
    return 1
  fi
}

freeze_main() (
  local script_dir root doc_num digest file doc_dir tmp old_status new_status delivered review_key auth_attempt recovery_output
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  root="${CLAUDE_PROJECT_DIR:-$(cd "$script_dir/../.." && pwd)}"
  doc_num="${1:-}"
  case "$doc_num" in
    [0-9][0-9][0-9][0-9]) ;;
    *) echo "usage: freeze.sh <four-digit-design-doc-number>" >&2; return 1 ;;
  esac

  . "$script_dir/../review-receipt.sh" || {
    echo "freeze.sh: shared review receipt contract is missing or unreadable." >&2
    return 1
  }
  . "${OH_HOME:-$root}/core/lib.sh" || {
    echo "freeze.sh: core/lib.sh is missing or unreadable." >&2
    return 1
  }
  file=$(ls "$root/docs/design/$doc_num"-*.md 2>/dev/null | head -1)
  [ -n "$file" ] && [ -f "$file" ] || {
    echo "freeze.sh: no design doc matching docs/design/$doc_num-*.md" >&2
    return 1
  }
  recovery_output=$(review_consumption_recover_current "$root" "freeze:$doc_num" "$file" 2>/dev/null)
  if [ $? -eq 0 ]; then
    echo "freeze.sh: recovered the already-applied lifecycle transition and closed its review series." >&2
    return 0
  fi
  digest=$(CLAUDE_PROJECT_DIR="$root" "$script_dir/tree-digest.sh")
  if [ -z "$digest" ]; then
    echo "STOP: cannot fingerprint the working tree, so finalization cannot be reviewed." >&2
    return 5
  fi
  if ! review_receipt_validate "$root" "$digest"; then
    echo "STOP: no review of the current tree. Finalization was not applied." >&2
    if ! review_rejection_note "$root" "$digest" >&2; then
      echo "Run invariant-reviewer on this exact tree, then retry freeze.sh." >&2
    fi
    return 5
  fi
  if ! review_completion_authorized "$root" "$digest"; then
    echo "REFUSED: the current review does not authorize finalization; no freeze applied." >&2
    review_completion_diagnose "$root"
    return 5
  fi
  auth_attempt=$(review_receipt_attempt "$root" "$digest" 2>/dev/null || true)
  review_key=$(review_current_key "$root" 2>/dev/null) || return 5
  old_status=$(fm_value "$file" status)
  doc_dir=$(dirname "$file")
  mkdir -p "$root/.deliver/transitions" || return 1
  tmp=$(mktemp "$root/.deliver/transitions/.freeze.XXXXXX") || {
    echo "freeze.sh: could not create an ignored replacement file." >&2
    return 1
  }
  trap 'rm -f "${tmp:-}"' EXIT
  cp -p "$file" "$tmp" || {
    echo "freeze.sh: could not preserve the design doc's file mode. Aborted." >&2
    return 1
  }
  if ! freeze_render "$doc_num" > "$tmp"; then return 1; fi
  freeze_diff_validate "$file" "$tmp" || return 1
  new_status=$(fm_value "$tmp" status)
  delivered=$(fm_value "$tmp" delivered)
  if cmp -s "$file" "$tmp"; then
    if [ "$old_status" = frozen ]; then
      echo "freeze.sh: design doc $doc_num is already frozen in $delivered — nothing to do." >&2
    else
      echo "freeze.sh: design doc $doc_num still has pending tasks — leaving it approved." >&2
    fi
    return 0
  fi
  if [ "$new_status" != frozen ] || [ -z "$delivered" ]; then
    echo "freeze.sh: proposed replacement did not produce valid frozen state. Aborted." >&2
    return 1
  fi
  if [ -n "$auth_attempt" ]; then
    review_consumption_intent_start "$root" "$auth_attempt" "freeze:$doc_num" "$file" "$tmp" "" || {
      echo "freeze.sh: could not publish the recoverable lifecycle intent. The design is unchanged." >&2
      return 1
    }
  fi
  if ! mv "$tmp" "$file"; then
    echo "freeze.sh: could not atomically replace $(basename "$file"). The original is unchanged." >&2
    return 1
  fi
  tmp=""
  if [ -n "$auth_attempt" ]; then
    review_consumption_recover "$root" "$auth_attempt" "freeze:$doc_num" "$file" >/dev/null || {
      echo "freeze.sh: lifecycle changed, but its recoverable transition could not be completed." >&2
      return 1
    }
  else
    review_completion_close "$root" "$digest" "$review_key" || {
      echo "freeze.sh: lifecycle changed, but the consumed review series could not be closed." >&2
      return 1
    }
  fi
  echo "froze design doc $doc_num in $delivered" >&2
)

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  freeze_main "$@"
fi
