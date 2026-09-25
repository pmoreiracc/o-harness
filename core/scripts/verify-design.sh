#!/usr/bin/env bash
# Is this design doc deliverable?
#
# plan.sh answers "what does the task list say"; this answers "does what it says hold
# together". Both questions are cheap now and expensive during a run: a dependency naming a
# task that was never written does not fail — next.sh reports "Waiting on task 99 ( track):"
# with an empty title and stops, every time, forever. A blocked-on marker pointing at a
# section that is not there does the same.
#
# The bar is structural, not editorial. Whether the decomposition is *good* is what the
# human approving it decides (ADR-0028); this only refuses one that cannot be executed.
# The form it enforces is stated in docs/design/README.md, "The shape a task list has to
# have" — that doc owns the grammar, this only holds it to it.
#
# Usage:  verify-design.sh [design-doc-number]     default: every design doc
#         verify-design.sh --review <number>       pre-claim/finalization review state
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$(cd "$DIR/.." && pwd)/lib.sh" || { echo "verify-design: core/lib.sh is missing." >&2; exit 1; }
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
cd "$ROOT" || exit 1

REVIEW_MODE=0
case "${1:-}" in
  --review)
    [ "$#" = 2 ] || { echo "Usage: verify-design.sh --review <number>" >&2; exit 2; }
    REVIEW_MODE=1
    WANT="$2"
    ;;
  *)
    [ "$#" -le 1 ] || { echo "Usage: verify-design.sh [number]" >&2; exit 2; }
    WANT="${1:-}"
    ;;
esac
US=$(printf '\037')

fails=0
fail() { fails=$((fails+1)); echo "FAIL  $1" >&2; }
ok()   { echo "ok    $1"; }
skip() { echo "skip  $1"; }

ALL_DOCS=$(ls docs/design/[0-9]*.md 2>/dev/null)
if [ -n "$WANT" ]; then
  DOCS=$(ls "docs/design/$WANT"-*.md 2>/dev/null)
  MATCH_COUNT=$(printf '%s\n' "$DOCS" | awk 'NF{n++} END{print n+0}')
  if [ "$MATCH_COUNT" -ne 1 ]; then
    echo "verify-design: docs/design/$WANT-*.md resolves to $MATCH_COUNT docs; expected one" >&2
    exit 1
  fi
else
  DOCS="$ALL_DOCS"
  # "Nothing to check" is decided from every .md in the directory, not just the numbered
  # ones. Deciding it from the numbered glob let `ledger.md` exit the script early and
  # escape every check below, which is the same invisibility, one step sooner.
  ANY=$(ls docs/design/*.md 2>/dev/null | grep -v '/README\.md$')
  if [ -z "$ANY" ]; then
    if [ -f docs/roadmap.md ]; then
      EMPTY_POINTERS=$("$DIR/roadmap.sh" --delivered 2>&1)
      if [ $? -ne 0 ]; then
        echo "FAIL  collapsed roadmap pointers do not parse" >&2
        printf '%s\n' "$EMPTY_POINTERS" | sed 's/^/      /' >&2
        exit 1
      fi
      if [ -n "$EMPTY_POINTERS" ]; then
        echo "FAIL  collapsed roadmap pointers exist, but there are no design docs" >&2
        exit 1
      fi
    fi
    skip "no design docs yet"
    echo
    echo "design docs verified"
    exit 0
  fi
fi

# --- the registry loop closes in both directions --------------------------------------
# Review mode still protects the global registry: targeting one lifecycle transition must
# not hide an unrelated number collision or approved orphan elsewhere in the tree.
if [ -z "$WANT" ] || [ "$REVIEW_MODE" = 1 ]; then
  # Two docs sharing a number is not cosmetic. plan.sh resolves a doc by `ls NNNN-*.md |
  # head -1`, so every later stage would silently work on whichever sorted first. The name
  # is checked first: the key has to be the same four characters every consumer takes, or
  # 0980-a and 09800-b would not collide here and would collide everywhere else.
  # Enumerated with a bare *.md, not the [0-9]* glob every loop below uses. A doc named
  # `ledger.md` is excluded from that glob, so it escapes the number check, the roadmap
  # claim, and the whole deliverability loop — silently, and with no skip line. That is
  # worse than a collision: a collision leaves one doc visible, this leaves none.
  name_bad=0
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    case "$(basename "$d")" in
      README.md) ;;
      [0-9][0-9][0-9][0-9]-*.md) ;;
      *) fail "$(basename "$d") is not named NNNN-<slug>.md"
         echo "        Every stage resolves a doc by its first four characters, so a name" >&2
         echo "        without them is a design doc nothing can find." >&2
         name_bad=1 ;;
    esac
  done <<EOF
$(ls docs/design/*.md 2>/dev/null)
EOF
  if [ "$name_bad" = 0 ]; then
    NDUPES=$(printf '%s\n' "$ALL_DOCS" | while IFS= read -r d; do
      [ -n "$d" ] && basename "$d" | cut -c1-4
    done | sort | uniq -d)
    if [ -n "$NDUPES" ]; then
      fail "two design docs share a number: $(printf '%s' "$NDUPES" | tr '\n' ' ')"
      echo "        plan.sh resolves a doc by its number and takes the first match, so the" >&2
      echo "        other one is invisible to every stage after it." >&2
    else
      ok "every design doc has its own number"
    fi
  fi

  # An approved doc no roadmap row points at is unreachable: nothing schedules it, and
  # /design would happily write a second one for the same work. Frozen docs are validated
  # below because their row legitimately expires when a shipped milestone collapses to a
  # prose pointer. A draft has not claimed its row yet, and an abandoned one never will.
  if [ ! -f docs/roadmap.md ]; then
    skip "no roadmap — cannot tell which design docs are claimed"
  else
    CLAIMED=$("$DIR/roadmap.sh" 2>&1)
    if [ $? -ne 0 ]; then
      fail "the roadmap does not parse, so no design doc can be matched to a row"
      printf '%s\n' "$CLAIMED" | sed 's/^/        /' >&2
    else
      CLAIMED=$(printf '%s\n' "$CLAIMED" | cut -d"$US" -f4 | grep -v '^$')
      ORPHAN=0
      while IFS= read -r d; do
        [ -n "$d" ] || continue
        [ "$(fm_value "$d" "status")" = "approved" ] || continue
        N=$(basename "$d" | cut -c1-4)
        printf '%s\n' "$CLAIMED" | grep -qxF "$N" && continue
        if [ "$REVIEW_MODE" = 1 ] && [ "$d" = "$DOCS" ]; then
          TARGET_STATE=$("$DIR/plan.sh" "$N" 2>/dev/null)
          if [ $? -eq 0 ] && printf '%s\n' "$TARGET_STATE" \
            | awk -F"$US" '$2 == "pending" {found=1} END {exit !found}'; then
            continue
          fi
        fi
        fail "$(basename "$d") is approved and named by no roadmap row"
        echo "        Fill the initiative's \`design\` column, or the doc is work nothing" >&2
        echo "        schedules and /design will write a second one for it." >&2
        ORPHAN=1
      done <<EOF
$ALL_DOCS
EOF
      [ "$ORPHAN" = 0 ] && ok "every approved design doc is claimed by a roadmap row"
    fi
  fi
fi

# Collapsed pointers close the registry in the reverse direction. It is not enough for a
# frozen doc to find its pointer below: otherwise a shipped milestone can claim a draft,
# abandoned, missing, incomplete, or differently delivered design and that target is
# skipped by the normal lifecycle loop.
if [ -f docs/roadmap.md ]; then
  COLLAPSED_STATE=$("$DIR/roadmap.sh" --delivered 2>&1)
  if [ $? -ne 0 ]; then
    fail "collapsed roadmap pointers do not parse"
    printf '%s\n' "$COLLAPSED_STATE" | sed 's/^/        /' >&2
  else
    pointer_bad=0
    while IFS="$US" read -r pnum pms; do
      [ -n "$pnum" ] || continue
      MATCHES=$(ls "docs/design/$pnum"-*.md 2>/dev/null)
      MATCH_COUNT=$(printf '%s\n' "$MATCHES" | grep -c .)
      if [ "$MATCH_COUNT" -ne 1 ]; then
        fail "collapsed pointer $pms/$pnum resolves to $MATCH_COUNT design docs; expected one"
        pointer_bad=1
        continue
      fi
      pdoc=$(printf '%s\n' "$MATCHES" | head -1)
      pstatus=$(fm_value "$pdoc" "status")
      pdelivered=$(fm_value "$pdoc" "delivered")
      if [ "$pstatus" != "frozen" ] || [ "$pdelivered" != "$pms" ]; then
        fail "collapsed pointer $pms/$pnum targets a '$pstatus' doc delivered in '${pdelivered:-nothing}'"
        pointer_bad=1
        continue
      fi
      pstate=$("$DIR/plan.sh" "$pnum" 2>&1)
      if [ $? -ne 0 ] || printf '%s\n' "$pstate" | awk -F"$US" '$2 == "pending" {bad=1} END {exit !bad}'; then
        fail "collapsed pointer $pms/$pnum targets a design that is invalid or incomplete"
        pointer_bad=1
      fi
    done <<EOF
$COLLAPSED_STATE
EOF
    [ "$pointer_bad" = 0 ] && ok "every collapsed milestone pointer names one complete frozen design"
  fi
fi

while IFS= read -r doc; do
  [ -n "$doc" ] || continue
  BN=$(basename "$doc")
  NUM=$(printf '%s' "$BN" | cut -c1-4)

  # Deliverability has force at `approved` (ADR-0031), while `frozen` has a smaller closed-
  # record contract: all tasks are complete and delivered names the roadmap milestone. A
  # draft is allowed loose ends, and an abandoned doc is kept as the record of work dropped.
  STATUS=$(fm_value "$doc" "status")
  case "$STATUS" in approved|frozen) ;; *)
    skip "$BN is '${STATUS:-without a status}', not approved — not yet a delivery contract"
    continue
    ;; esac

  # --- 0. it parses ---------------------------------------------------------------------
  STATE=$("$DIR/plan.sh" "$NUM" 2>&1)
  if [ $? -ne 0 ]; then
    fail "$BN does not parse"
    printf '%s\n' "$STATE" | sed 's/^/        /' >&2
    continue
  fi

  PENDING=$(printf '%s\n' "$STATE" | awk -F"$US" '$2 == "pending" {print $1}')
  if [ "$STATUS" = "frozen" ]; then
    frozen_bad=0
    if [ -n "$PENDING" ]; then
      fail "$BN is frozen with pending tasks: $(printf '%s' "$PENDING" | tr '\n' ' ')"
      frozen_bad=1
    fi

    DELIVERED=$(fm_value "$doc" "delivered")
    case "$DELIVERED" in
      M[0-9]*)
        case "${DELIVERED#M}" in *[!0-9]*|"")
          fail "$BN has invalid delivered milestone '$DELIVERED'"; frozen_bad=1
        esac
        ;;
      *) fail "$BN has invalid delivered milestone '${DELIVERED:-missing}'"; frozen_bad=1 ;;
    esac

    ROADMAP_STATE=$("$DIR/roadmap.sh" 2>&1)
    if [ $? -ne 0 ]; then
      fail "$BN is frozen but its roadmap milestone cannot be resolved"
      printf '%s\n' "$ROADMAP_STATE" | sed 's/^/        /' >&2
      frozen_bad=1
    else
      MILESTONES=$(printf '%s\n' "$ROADMAP_STATE" \
        | awk -F"$US" -v n="$NUM" '$4 == n {print $2}')
      MILESTONE_COUNT=$(printf '%s\n' "$MILESTONES" | grep -c .)
      case "$MILESTONE_COUNT" in
        0)
          COLLAPSED=$("$DIR/roadmap.sh" --delivered 2>&1)
          if [ $? -ne 0 ]; then
            fail "$BN cannot validate collapsed milestone pointers"
            printf '%s\n' "$COLLAPSED" | sed 's/^/        /' >&2
            frozen_bad=1
          fi
          POINTERS=$(printf '%s\n' "$COLLAPSED" \
            | awk -F"$US" -v n="$NUM" '$1 == n {print $2}')
          POINTER_COUNT=$(printf '%s\n' "$POINTERS" | grep -c .)
          MILESTONE=$(printf '%s\n' "$POINTERS" | head -1)
          if [ "$POINTER_COUNT" -ne 1 ] || [ "$DELIVERED" != "$MILESTONE" ]; then
            fail "$BN is frozen but has no matching roadmap row or pointer under $DELIVERED"
            frozen_bad=1
          fi
          ;;
        1)
          MILESTONE=$(printf '%s\n' "$MILESTONES" | head -1)
          if [ "$DELIVERED" != "$MILESTONE" ]; then
            fail "$BN says delivered: '${DELIVERED:-missing}', but its roadmap row is in $MILESTONE"
            frozen_bad=1
          fi
          ;;
        *)
          fail "$BN is frozen but is named by $MILESTONE_COUNT roadmap rows; expected at most one"
          frozen_bad=1
          ;;
      esac
    fi
    [ "$frozen_bad" = 0 ] \
      && ok "$BN: frozen in $MILESTONE with every task complete"
    continue
  fi

  if [ -z "$PENDING" ]; then
    if [ "$REVIEW_MODE" = 1 ]; then
      ROADMAP_STATE=$("$DIR/roadmap.sh" 2>&1)
      if [ $? -ne 0 ]; then
        fail "$BN is complete and approved but its roadmap owner cannot be resolved"
        printf '%s\n' "$ROADMAP_STATE" | sed 's/^/        /' >&2
      else
        OWNER_COUNT=$(printf '%s\n' "$ROADMAP_STATE" \
          | awk -F"$US" -v n="$NUM" '$4 == n {owners++} END {print owners+0}')
        if [ "$OWNER_COUNT" -eq 1 ]; then
          ok "$BN: complete and approved, awaiting reviewed finalization"
        else
          fail "$BN is complete and approved but named by $OWNER_COUNT roadmap rows; reviewed finalization requires exactly one"
        fi
      fi
    else
      fail "$BN is approved but every task is complete"
      echo "        Run core/scripts/freeze.sh $NUM; a delivered design cannot remain approved." >&2
    fi
  fi

  TASKS=$(printf '%s\n' "$STATE" | cut -d"$US" -f1)

  # --- 1. every dependency names a task that exists -------------------------------------
  dep_bad=0
  while IFS="$US" read -r n st ow needs blocked title; do
    [ -n "$n" ] || continue
    [ -n "$needs" ] || continue
    for d in $(printf '%s' "$needs" | tr ',' ' '); do
      printf '%s\n' "$TASKS" | grep -qxF "$d" && continue
      fail "$BN: task $n depends on task $d, which does not exist"
      dep_bad=1
    done
  done <<EOF
$STATE
EOF

  # --- 2. the dependency graph is acyclic -----------------------------------------------
  if [ "$dep_bad" = 0 ]; then
    REMAIN=$(printf '%s\n' "$TASKS")
    while :; do
      [ -n "$REMAIN" ] || break
      NEXT=""; moved=0
      for t in $REMAIN; do
        needs=$(printf '%s\n' "$STATE" | awk -F"$US" -v t="$t" '$1==t {print $4; exit}')
        blocked=0
        for d in $(printf '%s' "$needs" | tr ',' ' '); do
          printf '%s\n' "$REMAIN" | grep -qxF "$d" && { blocked=1; break; }
        done
        if [ "$blocked" = 1 ]; then NEXT="$NEXT$t
"; else moved=1; fi
      done
      REMAIN=$(printf '%s' "$NEXT" | grep -v '^$')
      [ "$moved" = 1 ] || break
    done
    if [ -n "$REMAIN" ]; then
      fail "$BN: dependency cycle among tasks $(printf '%s' "$REMAIN" | tr '\n' ' ')"
      dep_bad=1
    fi
  fi
  [ "$dep_bad" = 0 ] && ok "$BN: every dependency names a real task, and the graph is acyclic"

  # --- 3. every blocked-on marker resolves to a section ---------------------------------
  # Only the *Blocked on §N.* marker is checked, not every § in the prose: most of those
  # point into another document ("operations.md §8"), and line wrapping makes the two
  # indistinguishable by pattern. This one is unambiguous, and it is the one the pipeline
  # consumes — plan.sh extracts it and next.sh stops on it.
  # The direction matters. Requiring every Open section to block a task would fire the
  # moment a question is *answered*: settling §5 removes task 11's marker, and the section
  # — still headed "Open", because that is the historical record — would then block nothing
  # and turn every later push red. Checking the marker instead cannot misfire, because a
  # settled question has no marker left to check.
  # Headings are read from the doc with its fenced blocks removed. A "## 5. Open" quoted
  # inside a ```md fence would otherwise forge a section that does not exist — passing a
  # task blocked on nothing, which is the hang this check is for — and a fenced heading
  # earlier in the file would shadow the real one and fail a doc that is correct.
  BODY=$(awk '/^```/ { inf = !inf; next } !inf { print }' "$doc")

  blocked_bad=0
  while IFS="$US" read -r n st ow needs blocked title; do
    [ -n "$blocked" ] || continue
    # Strictly §N. `tr -dc` mashed "§5 and §7" into "§57" and then reported a section
    # nobody wrote — a diagnosis naming the wrong cause is worse than none.
    SEC=$(printf '%s' "$blocked" | sed -nE 's/^[[:space:]]*§?([0-9]+)[[:space:]]*$/\1/p')
    if [ -z "$SEC" ]; then
      fail "$BN: task $n is blocked on '$blocked', which is not of the form §N"
      blocked_bad=1
      continue
    fi
    HEAD_LINE=$(printf '%s\n' "$BODY" | grep -E "^## $SEC\." | head -1)
    if [ -z "$HEAD_LINE" ]; then
      fail "$BN: task $n is blocked on §$SEC, and the doc has no section $SEC"
      blocked_bad=1
    elif ! printf '%s' "$HEAD_LINE" | grep -qE "^## $SEC\.[[:space:]]+Open"; then
      fail "$BN: task $n is blocked on §$SEC, which is not an open-questions section"
      echo "        Found: $HEAD_LINE" >&2
      echo "        A task waits on a question, not on a part of the document." >&2
      blocked_bad=1
    fi
  done <<EOF
$STATE
EOF
  [ "$blocked_bad" = 0 ] && ok "$BN: every blocked-on marker names a real open-questions section"
done <<EOF
$DOCS
EOF

echo
if [ "$fails" -gt 0 ]; then echo "$fails check(s) failed" >&2; exit 1; fi
echo "design docs verified"
