#!/usr/bin/env bash
# The gate. Answers "what is the next task I may start?" — and refuses when the answer
# is none.
#
# Usage:  next.sh <design-doc-number> [track]
#
# The track is required only when the doc has more than one. A doc with a single kind of
# worker has nothing to disambiguate.
#
# Exit 0  a task is runnable. stdout: "<n>\t<title>"
# Exit 3  nothing is runnable. stderr says why. THIS IS NOT ADVICE.
# Exit 6  every task is complete but the approved doc still needs finalization
# Exit 7  an unmerged delivery branch is already complete and frozen; finish the run
# Exit 8  a completed-task boundary needs a human continue/pr/stop choice
# Exit 9  a recorded pr choice makes this existing branch terminal; finish its PR
# Exit 1  error.
#
# Idempotent by construction: runnable work comes from committed design state; after the
# first task, admission also comes from harness-written task-window choices. Re-running after
# a crash or interrupt resumes from those two sources rather than model prose.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOC_NUM="${1:-}"
OWNER="${2:-}"

if [ -z "$DOC_NUM" ]; then
  echo "usage: next.sh <design-doc-number> [track]" >&2
  exit 1
fi

. "$(cd "$DIR/.." && pwd)/lib.sh" || { echo "next.sh: core/lib.sh is missing." >&2; exit 1; }
. "$(cd "$DIR/.." && pwd)/task-ledger.sh" || { echo "next.sh: task-window contract is missing." >&2; exit 1; }

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
# `next.sh` deliberately has parser-only unit tests outside a repository. A live delivery
# invocation is always in one; there, index flags and branch-read failures must be rejected
# before task state is read.
IN_GIT=0
INSIDE_GIT=$(git -C "$ROOT" rev-parse --is-inside-work-tree 2>/dev/null)
INSIDE_GIT_STATUS=$?
if [ "$INSIDE_GIT_STATUS" -eq 0 ] && [ "$INSIDE_GIT" = true ]; then
  IN_GIT=1
elif [ -e "$ROOT/.git" ]; then
  echo "next.sh: cannot inspect the repository work-tree state." >&2
  exit 1
fi
if [ "$IN_GIT" = 1 ] && ! "$DIR/tree-digest.sh" --check-index >/dev/null; then
  echo "next.sh: tracked files carry index flags, so task state cannot be trusted." >&2
  exit 1
fi

# Parse before judging status: a doc that cannot be parsed is broken, and saying "not
# approved" about it would send the reader to the wrong problem.
TSV=$("$DIR/plan.sh" "$DOC_NUM") || exit 1
US=$(printf '\037')
TASK_US="$US"

FILE=$(task_design_file "$ROOT" "$DOC_NUM") || {
  echo "next.sh: design doc $DOC_NUM does not resolve to exactly one file." >&2
  exit 1
}

# Approval is a precondition on the invocation, not a stop reason — hence exit 1, like
# every other precondition here (no doc number, unparseable doc, unknown track). Nothing in
# the delivery loop writes frontmatter, so unlike the exit-3 conditions this one cannot
# arrive after a productive iteration: there is no branch yet and no PR to report it into.
# Approving the decomposition is approving the implementation plan (ADR-0028, ADR-0031).
STATUS=$(fm_value "$FILE" "status") || exit 1
BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null)
BRANCH_STATUS=$?
if [ "$BRANCH_STATUS" -ne 0 ]; then
  if [ "$IN_GIT" = 1 ]; then
    echo "next.sh: cannot resolve the current branch." >&2
    exit 1
  fi
  BRANCH=""
fi
PENDING_COUNT=$(printf '%s\n' "$TSV" | awk -F"$US" '$2 == "pending" {n++} END {print n+0}') || {
  echo "next.sh: cannot inspect pending task state." >&2
  exit 1
}
if [ "$STATUS" = "frozen" ] \
  && [ "$PENDING_COUNT" -eq 0 ] \
  && printf '%s' "$BRANCH" | grep -q '^deliver/'; then
  echo "FINISH: design doc $DOC_NUM is complete and frozen on $BRANCH." >&2
  echo "Resume the run at verification, commit if needed, then push and open its PR." >&2
  exit 7
fi
if [ "$STATUS" != "approved" ]; then
  echo "next.sh: design doc $DOC_NUM is '${STATUS:-missing a status}', not 'approved'." >&2
  case "$STATUS" in
    draft)
      echo "  A draft has not been reviewed as a whole. Get it merged as 'approved' first." >&2 ;;
    frozen)
      echo "  This doc has already shipped. Its tasks are history, not work." >&2 ;;
    abandoned)
      echo "  This doc was abandoned. Whatever replaced it is what gets delivered." >&2 ;;
  esac
  echo "  Approval is the merge: it lands on the trunk as 'approved', and nothing before." >&2
  exit 1
fi

# Completion is global, not per track. Check it before asking for a track so an approved
# doc whose independently delivered branches have all merged has one unambiguous resume
# path: finalize it from fresh trunk state. This is distinct from exit 3 because it is work
# the delivery workflow must perform, not a reason to stop.
if [ "$PENDING_COUNT" -eq 0 ]; then
  echo "FINALIZE: every task in design doc $DOC_NUM is complete, but the doc is still approved." >&2
  echo "Run core/scripts/freeze.sh $DOC_NUM before finishing." >&2
  exit 6
fi

# A SCOPE finding may append a pending follow-up task to this PR. It becomes part of the
# reviewed decomposition only after merge, so the live run selects work exclusively from
# task identities present at this branch's reviewed branch point. The full TSV still goes
# to the gate below so the commit validator can enforce that the appended task stayed pending.
SELECTION_TSV="$TSV"
SHAPE_TSV="$TSV"
AUTHORITY_OWNER=""
if printf '%s' "$BRANCH" | grep -q '^deliver/'; then
  task_authority_load "$ROOT" "$BRANCH" "$DOC_NUM" "$TSV" || exit 1
  BASE="$TASK_AUTHORITY_BASE"
  SELECTION_TSV="$TASK_AUTHORITY_TRUSTED_TSV"
  SHAPE_TSV="$TASK_AUTHORITY_SHAPE_TSV"
  AUTHORITY_OWNER="$TASK_AUTHORITY_OWNER"
fi

if [ -z "$OWNER" ]; then
  if [ -n "$AUTHORITY_OWNER" ]; then
    OWNER="$AUTHORITY_OWNER"
  else
    TRACKS=$(printf '%s\n' "$SHAPE_TSV" | cut -d"$US" -f3 | sort -u) || {
      echo "next.sh: cannot derive the reviewed track set." >&2
      exit 1
    }
    N=$(printf '%s\n' "$TRACKS" | awk 'NF {n++} END {print n+0}') || exit 1
    if [ "$N" = "1" ]; then
      OWNER="$TRACKS"
    else
      echo "usage: next.sh $DOC_NUM <track> — design doc $DOC_NUM has $N tracks:" >&2
      printf '%s\n' "$SHAPE_TSV" \
        | awk -F"$US" '{c[$3]++; if ($2=="pending") p[$3]++} END {for (o in c) printf "  %-8s %d pending of %d\n", o, p[o]+0, c[o]}' >&2 \
        || exit 1
      exit 1
    fi
  fi
fi

# An unknown track is an error, not a stop reason. Without this it falls through to "no
# tasks left for owner 'Code'" and exits 3 — which the skill is told to treat as the run
# being over, so a typo lands nothing and reports something indistinguishable from a
# genuinely finished track.
printf '%s\n' "$SHAPE_TSV" | cut -d"$US" -f3 | grep -qxF "$OWNER"
TRACK_STATUS=$?
if [ "$TRACK_STATUS" -gt 1 ]; then
  echo "next.sh: cannot inspect the reviewed track set." >&2
  exit 1
elif [ "$TRACK_STATUS" -eq 1 ]; then
  echo "next.sh: design doc $DOC_NUM has no track '$OWNER'. Its tracks are:" >&2
  printf '%s\n' "$SHAPE_TSV" \
    | awk -F"$US" '{c[$3]++; if ($2=="pending") p[$3]++} END {for (o in c) printf "  %-8s %d pending of %d\n", o, p[o]+0, c[o]}' >&2 \
    || exit 1
  exit 1
fi

field() { printf '%s\n' "$SELECTION_TSV" | awk -F"$US" -v n="$1" '$1==n {print $'"$2"'; exit}'; }

# First runnable comes from the same function continuation grants use to project their exact
# permitted task IDs. One algorithm means the authorization and gate cannot diverge.
RUNNABLE_RAW=$(task_first_runnable "$SELECTION_TSV" "$OWNER" "" 2>/dev/null)
RUNNABLE_STATUS=$?
case "$RUNNABLE_STATUS" in
  0) ;;
  1) RUNNABLE_RAW="" ;;
  *) echo "next.sh: cannot derive the reviewed runnable-task order." >&2; exit 1 ;;
esac
RUNNABLE=""
if [ -n "$RUNNABLE_RAW" ]; then
  RUNNABLE_N="${RUNNABLE_RAW%%"$US"*}"
  RUNNABLE_TITLE="${RUNNABLE_RAW#*"$US"}"
  RUNNABLE="$RUNNABLE_N  $RUNNABLE_TITLE"
fi

if [ -n "$RUNNABLE" ]; then
  case "$BRANCH" in
    main)
      MAIN_STATUS=$(git -C "$ROOT" status --porcelain 2>/dev/null) || {
        echo "next.sh: cannot inspect main branch cleanliness." >&2
        exit 1
      }
      if [ -n "$MAIN_STATUS" ]; then
        echo "next.sh: first-task discovery requires a clean main branch." >&2
        exit 1
      fi
      HEAD_SHA=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null) || {
        echo "next.sh: cannot resolve main HEAD." >&2
        exit 1
      }
      TRUNK_SHA=$(git -C "$ROOT" rev-parse origin/main 2>/dev/null) || {
        echo "next.sh: origin/main is unavailable; refresh trunk before starting a run." >&2
        exit 1
      }
      [ "$HEAD_SHA" = "$TRUNK_SHA" ] || {
        echo "next.sh: main is not refreshed to origin/main; pull before starting a run." >&2
        exit 1
      }
      ;;
    deliver/*)
      REFRESHED_EMPTY_RESUME=0
      PARSED=$(delivery_branch_parse "$BRANCH") || {
        echo "next.sh: malformed delivery branch '$BRANCH'." >&2; exit 1;
      }
      BDOC="${PARSED%%$'\t'*}"; BTRACK="${PARSED#*$'\t'}"
      if [ "$BDOC" != "$DOC_NUM" ] || { [ -n "$BTRACK" ] && [ "$BTRACK" != "$OWNER" ]; }; then
        echo "next.sh: branch $BRANCH does not match design $DOC_NUM track '$OWNER'." >&2
        exit 1
      fi
      REL_FILE="${FILE#"$ROOT"/}"
      if ! TASK_TRANSITIONS=$(task_worktree_transition_ids "$ROOT" "$REL_FILE"); then
        echo "next.sh: cannot compare the working-tree task state with HEAD." >&2
        exit 1
      fi
      if [ -n "$TASK_TRANSITIONS" ]; then
        echo "STOP: the design task state differs from HEAD. Commit the completed task before" >&2
        echo "asking for another; task-boundary authority begins only after a completed commit." >&2
        exit 1
      fi
      if ! task_gate_evaluate "$ROOT" "$BRANCH" "$DOC_NUM" "$TSV" "$RUNNABLE_N"; then
        echo "next.sh: task-window state is unreadable; refusing task $RUNNABLE_N." >&2
        exit 1
      fi
      # The skill may be interrupted after it creates the canonical delivery branch and
      # starts implementation but before the first task commit. That branch still points at
      # refreshed trunk, so its immutable HEAD is the same fresh authority next.sh issued on
      # main. Dirt alone cannot distinguish it from a completed branch after a fast-forward
      # merge. The current branch reflog entry supplies the local incarnation fact: a branch
      # created at this exact commit has no task/reset/merge/rename history, while a spent ref
      # does. The shared predicate also protects complete.sh's two consequential fresh paths,
      # so every consumer derives this exception from the same evidence.
      if task_fresh_branch_resume_valid "$ROOT" "$BRANCH"; then
        REFRESHED_EMPTY_RESUME=1
      fi
      if [ "$REFRESHED_EMPTY_RESUME" = 1 ]; then
        :
      elif git -C "$ROOT" merge-base --is-ancestor HEAD origin/main 2>/dev/null; then
        echo "next.sh: delivery branch $BRANCH is already absorbed by origin/main." >&2
        echo "Return to refreshed main; a later run gets a new branch point there." >&2
        exit 1
      fi
      case "$TASK_GATE_STATE" in
        fresh)
          if [ "$REFRESHED_EMPTY_RESUME" = 1 ]; then
            :
          else
            echo "next.sh: delivery branch $BRANCH changes task state without a canonical" >&2
            echo "task commit; fresh first-task authority is issued only from refreshed main." >&2
            exit 1
          fi ;;
        covered) ;;
        checkpoint)
          echo "CHECKPOINT: task $TASK_GATE_BOUNDARY_TASK is committed and task $RUNNABLE_N is runnable." >&2
          "$DIR/task-status.sh" "$DOC_NUM" "$OWNER" >&2 || {
            echo "The checkpoint remains pending. Repair the status/preview failure above, then rerun next.sh before offering continuation." >&2
            exit 8
          }
          if [ -n "${CODEX_SESSION_ID:-}${CODEX_HOOK:-}" ]; then
            codex_gate_present task - >&2
          else
            printf 'Choose one: %s / %s / %s\n' "$TASK_CONTINUE_LABEL" "$TASK_PR_LABEL" "$TASK_STOP_LABEL" >&2
          fi
          exit 8 ;;
        stop)
          echo "CHECKPOINT: the previous choice after task $TASK_GATE_BOUNDARY_TASK was stop." >&2
          echo "A resumed run needs a new human choice before task $RUNNABLE_N may begin." >&2
          "$DIR/task-status.sh" "$DOC_NUM" "$OWNER" >&2 || {
            echo "The checkpoint remains pending. Repair the status/preview failure above, then rerun next.sh before offering continuation." >&2
            exit 8
          }
          if [ -n "${CODEX_SESSION_ID:-}${CODEX_HOOK:-}" ]; then
            codex_gate_present task - >&2
          else
            printf 'Choose one: %s / %s / %s\n' "$TASK_CONTINUE_LABEL" "$TASK_PR_LABEL" "$TASK_STOP_LABEL" >&2
          fi
          exit 8 ;;
        pr)
          echo "FINISH: the human chose pr after task $TASK_GATE_BOUNDARY_TASK." >&2
          echo "This existing delivery branch is terminal; push and open or recover its PR." >&2
          exit 9 ;;
        *) echo "next.sh: unknown task-window state '$TASK_GATE_STATE'." >&2; exit 1 ;;
      esac
      ;;
    "")
      # Parser/unit fixtures may provide a project directory without a Git repository. The
      # real delivery workflow always runs in Git; any actual non-main branch is refused below.
      ;;
    *)
      echo "next.sh: runnable work may be discovered only on refreshed main or admitted on" >&2
      echo "the matching deliver/<doc>[-<track>] branch; current branch is '$BRANCH'." >&2
      exit 1
      ;;
  esac
  printf '%s\n' "$RUNNABLE"
  echo "(track: $OWNER)" >&2
  exit 0
fi

# Nothing runnable. Say precisely why, using the lowest pending task for this owner.
PENDING=$(printf '%s\n' "$SELECTION_TSV" | sort -t"$US" -k1,1n | awk -F"$US" -v o="$OWNER" '$2=="pending" && $3==o {print; exit}') || {
  echo "next.sh: cannot inspect the remaining reviewed task order." >&2
  exit 1
}

if [ -z "$PENDING" ]; then
  ANY=$(printf '%s\n' "$SELECTION_TSV" | awk -F"$US" '$2=="pending" {printf "%s (%s) ", $1, $3}') || exit 1
  if [ -z "$ANY" ]; then
    ROUTED=$(printf '%s\n' "$TSV" | awk -F"$US" '$2=="pending" {printf "%s (%s) ", $1, $3}') || exit 1
    if [ -n "$ROUTED" ] && [ "$SELECTION_TSV" != "$TSV" ]; then
      echo "STOP: every task reviewed for this delivery run is complete." >&2
      echo "Pending follow-up tasks routed in this PR are not runnable until merged: $ROUTED" >&2
      exit 3
    fi
    # Global completion exits 6 above. Keep this defensive branch fail-closed if the
    # task-state logic is ever changed without this block changing with it.
    echo "next.sh: every task is complete, but finalization was not detected." >&2
    exit 1
  else
    echo "STOP: no tasks left for owner '$OWNER' in design doc $DOC_NUM." >&2
    echo "Still pending for others: $ANY" >&2
  fi
  exit 3
fi

n=$(printf '%s' "$PENDING" | cut -d"$US" -f1) || exit 1
ne=$(printf '%s' "$PENDING" | cut -d"$US" -f4) || exit 1
bl=$(printf '%s' "$PENDING" | cut -d"$US" -f5) || exit 1
ti=$(printf '%s' "$PENDING" | cut -d"$US" -f6) || exit 1

echo "STOP: task $n is the next for '$OWNER' and is not runnable." >&2
echo "  $n. $ti" >&2

if [ -n "$bl" ]; then
  echo "  Blocked on: $bl — an open question in the design doc." >&2
  echo "  Settling it is a conversation and possibly an ADR. Never a task commit." >&2
  echo "  Present the unresolved question with its actual alternatives and recommendation; offer preparing that decision or finishing the completed work while waiting." >&2
  exit 3
fi

DEPS="${ne//,/$'\n'}"
while IFS= read -r d; do
  [ -n "$d" ] || continue
  DEP_STATE=$(field "$d" 2) || exit 1
  if [ "$DEP_STATE" != done ]; then
    DEP_OWNER=$(field "$d" 3) || exit 1
    DEP_TITLE=$(field "$d" 6) || exit 1
    echo "  Waiting on task $d ($DEP_OWNER track): $DEP_TITLE" >&2
  fi
done <<EOF
$DEPS
EOF
exit 3
