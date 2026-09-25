#!/usr/bin/env bash
# Verifies the delivery process from the outside — from what landed, not from what the
# workflow claims it did.
#
# The point: /deliver is a skill, and a skill is a prompt. A prompt cannot guarantee that
# the gate was consulted, that the branch was cut, or that the commits are shaped right.
# This does, after the fact, on a clean checkout. It is the reason bypassing the skill
# fails rather than merely being discouraged.
#
# The trick in check 3 is worth stating: it never asks whether next.sh was run. It
# re-derives the answer next.sh would have given at the branch point, and fails if the
# task was not runnable then. Verify the conclusion, not the call.
#
# Usage:  verify-delivery.sh [base-ref]        default: origin/main
set -uo pipefail

BASE="${1:-origin/main}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$(cd "$DIR/.." && pwd)/lib.sh" || { echo "verify-delivery: core/lib.sh is missing." >&2; exit 1; }
. "$(cd "$DIR/.." && pwd)/task-ledger.sh" || { echo "verify-delivery: core/task-ledger.sh is missing." >&2; exit 1; }
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
cd "$ROOT" || exit 1

fails=0
fail() { fails=$((fails+1)); echo "FAIL  $1" >&2; }
ok()   { echo "ok    $1"; }

git rev-parse --verify "$BASE" >/dev/null 2>&1 || { echo "verify-delivery: unknown base ref '$BASE'" >&2; exit 1; }
MERGE_BASE=$(git merge-base "$BASE" HEAD 2>/dev/null) || {
  echo "verify-delivery: cannot resolve the merge base for '$BASE'." >&2
  exit 1
}

TICKED=$(git diff --text "$BASE...HEAD" -- 'docs/design/[0-9]*.md' 2>/dev/null \
  | awk '/^\+- \[x\] \*\*[0-9]+\.\*\*/ { line=$0; sub(/^\+- \[x\] \*\*/, "", line); sub(/\..*/, "", line); print line }') || {
    echo "verify-delivery: cannot inspect delivered task transitions." >&2
    exit 1
  }

# What counts as implementation — the product and the shape it deploys in, both of which
# are delivered through a design doc. Deliberately excludes docs/ and core/, which are
# the specification and the tooling that delivers it, and the root README, which changes
# for reasons that are not implementation.
#
# infra/ and the Compose file are in the list because ADR-0016 makes the Compose file the
# deployment shape: it is built to a design-doc task like everything else, and leaving it
# out would let a whole work track bypass this check.
IMPL_PATHS="packages apps tools e2e infra
docker-compose.yml compose.yaml .env.example
pnpm-workspace.yaml package.json turbo.json tsconfig.base.json"

IMPL_CHANGED=$(git diff --name-only "$BASE...HEAD" -- $IMPL_PATHS 2>/dev/null) || {
  echo "verify-delivery: cannot inspect implementation paths." >&2
  exit 1
}
# ADR-0050 makes this one source inert catalog data. Exempt only proven literal
# intent/notes/confirmation edits; a parser/read failure keeps the implementation rule.
FILTERED_IMPL_CHANGED=""
while IFS= read -r path; do
  [ -n "$path" ] || continue
  if [ "$path" = packages/application/src/planned-capabilities.ts ] \
    && node "$DIR/planned-catalog-doc-change.mjs" "$ROOT" "$MERGE_BASE" HEAD; then
    continue
  fi
  FILTERED_IMPL_CHANGED="${FILTERED_IMPL_CHANGED}${FILTERED_IMPL_CHANGED:+$'\n'}$path"
done <<EOF
$IMPL_CHANGED
EOF
IMPL_CHANGED="$FILTERED_IMPL_CHANGED"
TOUCHES_CODE="${IMPL_CHANGED%%$'\n'*}"
DOCS=$(git diff --name-only "$BASE...HEAD" -- 'docs/design/[0-9]*.md' 2>/dev/null) || {
  echo "verify-delivery: cannot inspect changed design documents." >&2
  exit 1
}

# A rename detaches a doc from its history here: `git show $MERGE_BASE:<new path>` finds
# nothing, so the regression and approval checks have nothing to compare against and pass
# by default — a completed task can be un-ticked in the same breath and nothing notices.
# Reconstructing the old path is guesswork; refusing is not. Rename a design doc in its own
# PR, where there is no delivery to verify.
DESIGN_STATUS=$(git diff --name-status -M "$BASE...HEAD" -- 'docs/design/[0-9]*.md' 2>/dev/null) || {
  echo "verify-delivery: cannot inspect design-document rename state." >&2
  exit 1
}
RENAMED=$(printf '%s\n' "$DESIGN_STATUS" | awk '$1 ~ /^R/ {print $2" -> "$3}') || {
  echo "verify-delivery: cannot parse design-document rename state." >&2
  exit 1
}
RENAMED_NEW=$(printf '%s\n' "$DESIGN_STATUS" | awk '$1 ~ /^R/ {print $3}') || {
  echo "verify-delivery: cannot parse renamed design-document paths." >&2
  exit 1
}

# ticks_for <path> — the task numbers THIS doc had ticked by this branch.
# Attribution matters: a branch that ticks a task in one doc and touches another must be
# judged against the doc the ticks came from, not against whichever filename sorts first.
ticks_for() {
  local diff
  diff=$(git diff --text "$BASE...HEAD" -- "$1" 2>/dev/null) || return 1
  printf '%s\n' "$diff" \
    | awk '/^\+- \[x\] \*\*[0-9]+\.\*\*/ { line=$0; sub(/^\+- \[x\] \*\*/, "", line); sub(/\..*/, "", line); print line }'
}

# --- 1. code changes deliver a design-doc task ----------------------------------------
if [ -n "$TOUCHES_CODE" ] && [ -z "$TICKED" ]; then
  fail "this PR changes code but ticks no design-doc task"
  echo "        Implementation is delivered through a design doc (ADR-0030). If this work" >&2
  echo "        is not in one, it needs a task first — or it is not implementation." >&2
else
  ok "code changes are accounted for by a design-doc task"
fi

# --- 2. commit shape on a delivery branch ---------------------------------------------
# GITHUB_HEAD_REF first: pull-request checkouts are detached, whether the workflow selected
# GitHub's merge ref or the authored head SHA. `abbrev-ref HEAD` is the literal string "HEAD"
# and every branch-name check below would silently match nothing. A guard that only runs on the
# developer's machine, where `git push --no-verify` skips it, is the "looks present and is not"
# failure this repository refuses everywhere else.
if [ -n "${GITHUB_HEAD_REF:-}" ]; then
  BRANCH="$GITHUB_HEAD_REF"
else
  BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || {
    echo "verify-delivery: cannot resolve the authored branch identity." >&2
    exit 1
  }
fi
HISTORICAL_RUN_DOC=""
NON_DELIVERY_IMPL=0
case "$BRANCH" in
  deliver/*)
    shape_bad=0
    SHAPE_COMMITS=$(git rev-list "$MERGE_BASE..HEAD" 2>/dev/null) || {
      fail "cannot enumerate delivery commits from the branch point"
      shape_bad=1
      SHAPE_COMMITS=""
    }
    while IFS= read -r sha; do
      [ -n "$sha" ] || continue
      SUBJ=$(git log -1 --format=%s "$sha" 2>/dev/null) || {
        fail "cannot inspect delivery commit $sha"
        shape_bad=1
        continue
      }
      case "$SUBJ" in
        task\ [0-9]*:\ *)
          BODY=$(git log -1 --format=%B "$sha" 2>/dev/null) || {
            fail "cannot inspect delivery commit body $sha"
            shape_bad=1
            continue
          }
          SHORT_SHA=$(git log -1 --format=%h "$sha" 2>/dev/null) || {
            fail "cannot abbreviate delivery commit $sha"
            shape_bad=1
            continue
          }
          printf '%s\n' "$BODY" | grep -qE '^Review-Rounds: [0-9]+$' \
            || { fail "commit $SHORT_SHA has no Review-Rounds trailer: $SUBJ"; shape_bad=1; }
          if printf '%s\n' "$BODY" | grep -q '^Review-Resolution:' \
             && printf '%s\n' "$BODY" | grep '^Review-Resolution:' \
               | grep -qvE '^Review-Resolution: [0-9a-f]{64}$'; then
            fail "commit $SHORT_SHA has a malformed Review-Resolution trailer: $SUBJ"
            shape_bad=1
          fi ;;
        review:\ *|Merge\ *) ;;
        *)
          SHORT_SHA=$(git log -1 --format=%h "$sha" 2>/dev/null) || {
            fail "cannot abbreviate delivery commit $sha"
            shape_bad=1
            continue
          }
          fail "commit $SHORT_SHA is not a task or review commit: $SUBJ"; shape_bad=1 ;;
      esac
    done <<EOF
$SHAPE_COMMITS
EOF
    TASK_US=$(printf '\037')
    attribution_bad=0
    PARSED=$(delivery_branch_parse "$BRANCH" 2>/dev/null) || {
      fail "$BRANCH is not a valid canonical delivery branch"
      attribution_bad=1
      PARSED=""
    }
    if [ -n "$PARSED" ]; then
      DOCNUM="${PARSED%%$'\t'*}"; BRANCH_OWNER="${PARSED#*$'\t'}"
    else
      # A trailing-hyphen branch is grammatically malformed, but its four-digit design
      # identity is still unambiguous. Let the canonical loader derive the reviewed shape
      # and print the actionable spelling without treating this partial parse as authority.
      case "$BRANCH" in
        deliver/[0-9][0-9][0-9][0-9]-*)
          DOCNUM="${BRANCH#deliver/}"; DOCNUM="${DOCNUM%%-*}" ;;
        *) DOCNUM="" ;;
      esac
      BRANCH_OWNER=""
    fi
    if [ -n "$DOCNUM" ]; then
      if ! STATE=$(CLAUDE_PROJECT_DIR="$ROOT" "$DIR/plan.sh" "$DOCNUM" 2>/dev/null); then
        fail "design $DOCNUM: current task state is unreadable"
        attribution_bad=1
        STATE=""
      fi
    else
      STATE=""
    fi
    if [ -n "$STATE" ]; then
      if task_authority_load "$ROOT" "$BRANCH" "$DOCNUM" "$STATE" "$MERGE_BASE"; then
        TRUSTED_STATE="$TASK_AUTHORITY_TRUSTED_TSV"
        SHAPE_STATE="$TASK_AUTHORITY_SHAPE_TSV"
        BRANCH_OWNER="$TASK_AUTHORITY_OWNER"
        # The canonical authority loader checks each task against the reviewed authority in
        # force at its own commit. Do not project the latest moving merge base backward.
        HISTORICAL_RUN_DOC="$DOCNUM"
      else
        case "$TASK_AUTHORITY_ERROR" in
          trusted) fail "design $DOCNUM: reviewed branch-point task state is unavailable" ;;
          shape) fail "design $DOCNUM: original delivery-incarnation track shape is unavailable" ;;
          branch) fail "design $DOCNUM: branch does not encode its reviewed track shape" ;;
          *) fail "design $DOCNUM: task transitions are not attributable to this delivery branch" ;;
        esac
        attribution_bad=1
      fi
    fi
    [ "$attribution_bad" = 0 ] && ok "every task transition belongs to its matching task commit"
    [ "$shape_bad" = 0 ] && ok "every commit is a task or review commit with its rounds recorded"
    ;;
  *)
    if [ -n "$TOUCHES_CODE" ]; then
      fail "implementation changes require a canonical deliver/<design>[-<track>] branch"
      NON_DELIVERY_IMPL=1
    else
      ok "not a delivery branch — commit shape not checked"
    fi
    ;;
esac

# --- 3 / 4 / 6. per design doc: approved, runnable, and nothing regressed --------------
# Scoped to the doc the ticks came from. Reading "the" design doc from `head -1` made all
# three answer about whichever filename sorted first, so a branch could tick a task in a
# draft doc, touch an approved one, and have the approval check clear the wrong file.
SNAP=$(mktemp -d) || {
  echo "verify-delivery: cannot prepare isolated design snapshots." >&2
  exit 1
}
trap 'rm -rf "$SNAP"' EXIT
US=$(printf '\037')

if [ -n "$RENAMED" ]; then
  fail "a design doc was renamed on this branch"
  printf '%s\n' "$RENAMED" | sed 's/^/        /' >&2
  echo "        A rename detaches the doc from its history, so nothing here can tell a" >&2
  echo "        delivery from a regression. Rename it in a PR that does nothing else." >&2
fi

approval_bad=0; run_bad=0; run_skipped="$NON_DELIVERY_IMPL"; regressed=0; any_ticks=0; seq=0
# read rather than word-splitting $DOCS, and a here-doc rather than a pipe so the counters
# below stay in this shell.
while IFS= read -r doc; do
  [ -n "$doc" ] || continue
  # A renamed doc has already failed the run above, and every check below would describe it
  # wrongly — "not on $BASE" about a doc that was there under another name, pointing the
  # author at the wrong fix.
  task_id_list_contains "$RENAMED_NEW" "$doc" && continue
  seq=$((seq+1))
  BN=$(basename "$doc")
  DOCNUM=$(printf '%s' "$BN" | cut -c1-4)

  # One tree per doc, per end. plan.sh resolves a doc by its four-digit prefix, so two docs
  # sharing one — 0002-alpha.md and 0002-beta.md — would collide in a shared tree and the
  # regression check would compare one doc's past against the other's present.
  WASDIR="$SNAP/$seq/was"; NOWDIR="$SNAP/$seq/now"
  mkdir -p "$WASDIR/docs/design" "$NOWDIR/docs/design" || {
    echo "verify-delivery: cannot prepare isolated design snapshots." >&2
    exit 1
  }
  SNAPFILE="$WASDIR/docs/design/$BN"
  BASE_ENTRY=$(git ls-tree "$MERGE_BASE" -- "$doc" 2>/dev/null) || {
    echo "verify-delivery: cannot inspect historical design-document identity for $BN." >&2
    exit 1
  }
  if [ -n "$BASE_ENTRY" ]; then
    git show "$MERGE_BASE:$doc" > "$SNAPFILE" 2>/dev/null || {
      echo "verify-delivery: cannot read historical design document $BN." >&2
      exit 1
    }
  fi
  if [ -f "$doc" ]; then
    cp "$doc" "$NOWDIR/docs/design/$BN" || {
      echo "verify-delivery: cannot prepare current design snapshot for $BN." >&2
      exit 1
    }
  fi

  # 4 — no completed task regresses. Applies whether or not this branch ticked anything.
  # Compares parsed state at both ends, not diff lines: a task whose wording changed while
  # staying pending produces a "+- [ ] **N.**" line and is legitimate. Check the conclusion.
  if [ -s "$SNAPFILE" ]; then
    WAS_STATE=$(CLAUDE_PROJECT_DIR="$WASDIR" "$DIR/plan.sh" "$DOCNUM" 2>/dev/null) || {
      fail "$BN: could not parse historical completed-task state"
      regressed=1; run_skipped=1; continue
    }
    WAS=$(printf '%s\n' "$WAS_STATE" | awk -F"$US" '$2=="done" {print $1}') || {
      fail "$BN: could not derive historical completed-task state"
      regressed=1; run_skipped=1; continue
    }
    NOW_STATE=$(CLAUDE_PROJECT_DIR="$NOWDIR" "$DIR/plan.sh" "$DOCNUM" 2>/dev/null) || {
      fail "$BN: could not parse current completed-task state"
      regressed=1; run_skipped=1; continue
    }
    NOW=$(printf '%s\n' "$NOW_STATE" | awk -F"$US" '$2=="done" {print $1}') || {
      fail "$BN: could not derive current completed-task state"
      regressed=1; run_skipped=1; continue
    }
    for n in $WAS; do
      task_id_list_contains "$NOW" "$n" \
        || { fail "$BN: task $n was complete at the branch point and is not complete now"; regressed=1; }
    done
  fi

  TICKS=$(ticks_for "$doc") || {
    fail "$BN: could not inspect delivered task transitions"
    run_skipped=1
    continue
  }
  [ -n "$TICKS" ] || continue
  any_ticks=1

  # 6 — approved on the trunk before it was delivered. next.sh refuses an unapproved doc,
  # but next.sh reads the working tree, so an agent that wrote `status: approved` on its own
  # branch would satisfy it. This asks the only question the branch cannot answer.
  if [ ! -s "$SNAPFILE" ]; then
    fail "$BN: tasks were ticked against a design doc that is not on $BASE"
    echo "        A decomposition is approved by being merged. Land the doc first," >&2
    echo "        then deliver it (ADR-0031)." >&2
    approval_bad=1
    run_skipped=1        # check 3 needs the branch-point state, and there is none
    continue
  fi
  WAS_STATUS=$(fm_value "$SNAPFILE" "status") || {
    fail "$BN: could not read its historical lifecycle status"
    approval_bad=1
    run_skipped=1
    continue
  }
  if [ "$WAS_STATUS" != "approved" ]; then
    fail "$BN: was '${WAS_STATUS:-without a status}' when this branch was cut, and was delivered anyway"
    echo "        Approving the decomposition is approving the implementation plan, and it" >&2
    echo "        happens on the trunk (ADR-0031). If it was approved after you branched," >&2
    echo "        rebase." >&2
    approval_bad=1
  fi

  # 3 — every ticked task was runnable under its reviewed authority. Delivery branches are
  # checked per commit above, including authority changes from refreshed-main merges. The
  # aggregate branch-point check remains the fallback for non-delivery refs.
  [ "$DOCNUM" = "$HISTORICAL_RUN_DOC" ] && continue
  if ! STATE=$(CLAUDE_PROJECT_DIR="$WASDIR" "$DIR/plan.sh" "$DOCNUM" 2>/dev/null); then
    fail "$BN: could not re-derive the task list at the branch point"
    run_bad=1
    continue
  fi
  for n in $TICKS; do
    LINE=$(printf '%s\n' "$STATE" | awk -F"$US" -v n="$n" '$1==n {print; exit}') || {
      fail "$BN: could not inspect task $n at the branch point"; run_bad=1; continue
    }
    if [ -z "$LINE" ]; then
      fail "$BN: task $n was ticked but does not exist in the doc at the branch point"; run_bad=1; continue
    fi
    BL=$(printf '%s' "$LINE" | cut -d"$US" -f5) || {
      fail "$BN: could not inspect task $n blocker state"; run_bad=1; continue
    }
    NE=$(printf '%s' "$LINE" | cut -d"$US" -f4) || {
      fail "$BN: could not inspect task $n dependency state"; run_bad=1; continue
    }
    if [ -n "$BL" ]; then
      fail "$BN: task $n was blocked on $BL at the branch point and was delivered anyway"; run_bad=1
    fi
    DEPS="${NE//,/$'\n'}"
    while IFS= read -r dep; do
      [ -n "$dep" ] || continue
      DST=$(printf '%s\n' "$STATE" | awk -F"$US" -v n="$dep" '$1==n {print $2; exit}') || {
        fail "$BN: could not inspect dependency task $dep"; run_bad=1; continue
      }
      # Delivered in this same run. `$TICKS` is newline-separated, so it needs the same
      # normalisation the regression check above uses — matching on `" $TICKS "` looks for a
      # space-delimited number and finds newlines, so the carve-out never fired for any run that
      # ticked more than one task. Which is every run: a doc whose tasks depend on each other
      # reported every in-run dependency as "not done".
      task_id_list_contains "$TICKS" "$dep" && continue
      [ "$DST" = "done" ] || { fail "$BN: task $n depends on task $dep, which was not done"; run_bad=1; }
    done <<EOF
$DEPS
EOF
  done
done <<EOF
$DOCS
EOF

if [ -n "$RENAMED" ] && [ "$any_ticks" = 0 ]; then
  :   # a renamed doc was skipped, so "no tasks ticked" would not be a claim worth making
elif [ "$any_ticks" = 0 ]; then
  ok "no tasks ticked"
else
  [ "$approval_bad" = 0 ] && ok "every delivered doc was approved on $BASE before the branch was cut"
  # Only claim this when it was actually checked. A doc with no branch-point state has no
  # runnability to re-derive, and a green line for a check that was skipped is the failure
  # this whole file exists to prevent.
  [ "$run_bad" = 0 ] && [ "$run_skipped" = 0 ] \
    && ok "every ticked task was runnable under its reviewed authority"
fi
[ "$regressed" = 0 ] && ok "no completed task regressed"

# --- 5. a multi-track doc delivers on a per-track branch (ADR-0030) --------------------
# The branch name is otherwise the agent's own reading of "does this doc have several
# tracks?", which is exactly the kind of question ADR-0027 says never to leave to a
# reading when the answer is derivable. plan.sh knows the owners; ask it.
case "$BRANCH" in
  deliver/*)
    US=$(printf '\037')
    BR=${BRANCH#deliver/}
    BDOC=${BR%%-*}
    BRANCH_SHAPE="${SHAPE_STATE:-}"
    OWNERS=$(printf '%s\n' "$BRANCH_SHAPE" | cut -d"$US" -f3 | sort -u) || {
      echo "verify-delivery: cannot derive branch track ownership." >&2
      exit 1
    }
    NOWN=$(printf '%s\n' "$OWNERS" | awk 'NF {n++} END {print n+0}') || {
      echo "verify-delivery: cannot count branch track ownership." >&2
      exit 1
    }
    if [ "$NOWN" -eq 0 ]; then
      fail "branch is $BRANCH but no design doc $BDOC could be parsed"
    elif [ "$NOWN" -gt 1 ]; then
      TRACK=${BR#"$BDOC"}; TRACK=${TRACK#-}
      if printf '%s\n' "$OWNERS" | grep -qxF "$TRACK"; then
        ok "branch names the track, as a $NOWN-track doc requires"
      else
        fail "design doc $BDOC has $NOWN tracks, so the branch must be deliver/$BDOC-<track>"
        echo "        Found '$BRANCH'. Tracks: $(printf '%s' "$OWNERS" | tr '\n' ' ')" >&2
        echo "        Two tracks on one branch land two runs in one PR (ADR-0030)." >&2
      fi
    else
      SUFFIX=${BR#"$BDOC"}
      if [ -n "$SUFFIX" ]; then
        fail "design doc $BDOC has one track, so the branch is deliver/$BDOC — found '$BRANCH'"
      else
        ok "single-track doc — branch carries no track, as expected"
      fi
    fi
    ;;
esac

echo
if [ "$fails" -gt 0 ]; then echo "$fails check(s) failed" >&2; exit 1; fi
echo "delivery verified against $BASE"
