#!/usr/bin/env bash
# Render a design doc's lifecycle edit after a task completes. Sourced by the OH design
# adapter, which reviews and commits the rendered tree; this file writes nothing itself.
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

