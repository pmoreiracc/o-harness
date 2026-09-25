#!/usr/bin/env bash
# Shared task-window contract (ADR-0045). Sourced, never executed.
#
# A fresh delivery branch may start one task. Every later runnable task must either be
# named by a human-written continue record or wait at a checkpoint. The same state machine
# is used by next.sh, the host hooks, task-status.sh, and PR-history rendering.
#
# Records live under .deliver/reviews/ and are written atomically by human-input hooks.
# Consumers validate the exact branch incarnation, boundary, sequence and task projection.
# Compatible with Bash 3.2.

TASK_LEDGER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$TASK_LEDGER_DIR/review-workflow.sh" || return 1 2>/dev/null || exit 1
TASK_CONTINUE_LABEL="Continue with next task window"
TASK_PR_LABEL="Open PR with completed tasks"
TASK_STOP_LABEL="Stop without opening a PR"
TASK_CONTINUE_COMMAND="continue"
TASK_PR_COMMAND="pr"
TASK_STOP_COMMAND="stop"

task_state_root() {
  printf '%s/task-state' "$(review_series_state_root "$1")"
}

task_branch_key() {
  printf '%s' "${1#deliver/}"
}

task_ledger_dir() {
  printf '%s/%s/%s' "$(task_state_root "$1")" "$(task_branch_key "$2")" "$3"
}

task_decimal_gt_small() {
  local value="$1" small="$2"
  while [ "${value#0}" != "$value" ]; do value="${value#0}"; done
  [ -n "$value" ] || value=0
  if [ "${#value}" -gt "${#small}" ]; then return 0; fi
  if [ "${#value}" -lt "${#small}" ]; then return 1; fi
  [[ "$value" > "$small" ]]
}

task_integer_literal_valid() {
  local literal="$1" integer fraction sign exponent digits scale remaining
  [[ "$literal" =~ ^([0-9]+)(\.([0-9]+))?([eE]([+-]?)([0-9]+))?$ ]] || return 1
  integer="${BASH_REMATCH[1]}"; fraction="${BASH_REMATCH[3]}"
  sign="${BASH_REMATCH[5]}"; exponent="${BASH_REMATCH[6]}"
  [ -n "$exponent" ] || exponent=0
  while [ "${exponent#0}" != "$exponent" ]; do exponent="${exponent#0}"; done
  [ -n "$exponent" ] || exponent=0
  digits="$integer$fraction"
  if [ "$sign" = - ]; then
    task_decimal_gt_small "$exponent" "${#digits}" && return 1
    scale=$(( ${#fraction} + exponent ))
  else
    if task_decimal_gt_small "$exponent" "${#fraction}"; then return 0; fi
    scale=$(( ${#fraction} - exponent ))
  fi
  [ "$scale" -eq 0 ] && return 0
  [ "$scale" -le "${#digits}" ] || return 1
  remaining="${digits:$((${#digits} - scale))}"
  case "$remaining" in *[!0]*) return 1 ;; *) return 0 ;; esac
}

task_policy_parse() {
  local values
  values=$(review_policy_parse) || return 1
  printf '%s' "${values%%$'\t'*}"
}

# Read choice-version 3's historical one-field policy blob. New policy files never use this
# shape, but old task grants remain valid evidence after ADR-0051.
task_legacy_policy_parse() {
  local payload compact prefix literal
  payload=$(cat)
  printf '%s' "$payload" | jq -e '
    type == "object" and (keys | sort) == ["continuation_window_tasks"] and
    (.continuation_window_tasks | type == "number" and floor == . and . > 0)
  ' >/dev/null 2>&1 || return 1
  compact="${payload//[[:space:]]/}"; prefix='{"continuation_window_tasks":'
  case "$compact" in "$prefix"*'}') ;; *) return 1 ;; esac
  literal="${compact#"$prefix"}"; literal="${literal%?}"
  review_integer_literal_valid "$literal" || return 1
  printf '%s' "$literal"
}

task_policy_window() {
  local root="$1" file="$1/core/delivery-policy.json" value head_blob trunk_blob
  if [ -n "${OH_HOME:-}" ]; then
    review_policy_load "$root" || return 1
    printf '%s' "$REVIEW_POLICY_CONTINUATION"
    return 0
  fi
  if ! git -C "$root" diff --quiet HEAD -- core/delivery-policy.json 2>/dev/null; then
    echo "task-window: core/delivery-policy.json differs from HEAD; only checked-in policy can grant a window." >&2
    return 1
  fi
  head_blob=$(git -C "$root" rev-parse HEAD:core/delivery-policy.json 2>/dev/null) || return 1
  trunk_blob=$(git -C "$root" rev-parse origin/main:core/delivery-policy.json 2>/dev/null) || {
    echo "task-window: origin/main has no readable delivery policy; refresh trunk." >&2
    return 1
  }
  [ "$head_blob" = "$trunk_blob" ] || {
    echo "task-window: the active branch changes delivery policy relative to origin/main." >&2
    echo "Land that reviewed policy change first, then sync the delivery branch." >&2
    return 1
  }
  git -C "$root" show origin/main:core/delivery-policy.json 2>/dev/null \
    | review_policy_parse >/dev/null || {
    echo "task-window: core/delivery-policy.json must contain exactly two positive integer fields:" >&2
    echo "  continuation_window_tasks and review_window_rounds" >&2
    return 1
  }
  review_policy_load "$root" || {
    echo "task-window: delivery policy is invalid; a present local override never falls back." >&2
    return 1
  }
  printf '%s' "$REVIEW_POLICY_CONTINUATION"
}

# task_branch_owner <branch> <doc> <trusted-tsv>
# Prints the owner encoded by ADR-0030's branch grammar. Track cardinality comes only from
# the reviewed branch-point snapshot: a pending SCOPE task may introduce a new track in this
# PR, but cannot retroactively rename or reclassify the already-running delivery branch.
task_branch_owner() {
  local branch="$1" doc="$2" tsv="$3" parsed bdoc btrack tracks count
  parsed=$(delivery_branch_parse "$branch") || return 1
  bdoc="${parsed%%$'\t'*}"; btrack="${parsed#*$'\t'}"
  [ "$bdoc" = "$doc" ] || return 1
  tracks=$(printf '%s\n' "$tsv" | cut -d"$TASK_US" -f3 | sort -u) || return 1
  count=$(printf '%s\n' "$tracks" | awk 'NF {n++} END {print n+0}') || return 1
  [ "$count" -gt 0 ] || return 1
  if [ "$count" = 1 ]; then
    [ -z "$btrack" ] || return 1
    printf '%s' "$tracks"
  else
    [ -n "$btrack" ] || return 1
    printf '%s\n' "$tracks" | grep -qxF "$btrack" || return 1
    printf '%s' "$btrack"
  fi
}

# task_branch_shape_diagnose <branch> <doc> <reviewed-shape-tsv>
# Explain a failed branch-shape check from the exact projection task_branch_owner consumed.
# This is diagnostic only: it neither publishes authority nor reconstructs another snapshot.
task_branch_shape_diagnose() {
  local branch="$1" doc="$2" tsv="$3" tracks count
  tracks=$(printf '%s\n' "$tsv" | cut -d"$TASK_US" -f3 | sort -u) || return 1
  count=$(printf '%s\n' "$tracks" | awk 'NF {n++} END {print n+0}') || return 1
  case "$count" in
    0)
      echo "task-window: design $doc has no reviewed track shape." >&2 ;;
    1)
      echo "task-window: design doc $doc has one track, so the branch is deliver/$doc — found '$branch'." >&2 ;;
    *)
      echo "task-window: design doc $doc has $count tracks, so the branch must be deliver/$doc-<track>." >&2
      echo "task-window: found '$branch'. Tracks: $(printf '%s' "$tracks" | tr '\n' ' ')" >&2 ;;
  esac
}

# task_fresh_branch_incarnation_valid <root> <branch>
#
# A canonical branch created from refreshed main has one local fact that an absorbed branch
# reset back to trunk does not: its latest branch-ref reflog entry is the creation event at
# the current trunk SHA. This proves only that incarnation; callers own branch shape, task
# state, and (where relevant) the presence of implementation changes.
task_fresh_branch_incarnation_valid() {
  local root="$1" branch="$2" head trunk reflog start_sha start_subject
  head=$(git -C "$root" rev-parse HEAD 2>/dev/null) || return 1
  trunk=$(git -C "$root" rev-parse origin/main 2>/dev/null) || return 1
  [ "$head" = "$trunk" ] || return 1
  reflog=$(git -C "$root" reflog show --format='%H%x09%gs' -n 1 \
    "refs/heads/$branch" 2>/dev/null) || return 1
  start_sha="${reflog%%$'\t'*}"
  start_subject="${reflog#*$'\t'}"
  [ "$start_subject" != "$reflog" ] || return 1
  [ "$start_sha" = "$head" ] || return 1
  case "$start_subject" in
    branch:\ Created\ from\ *) return 0 ;;
    *) return 1 ;;
  esac
}

# task_fresh_branch_resume_valid <root> <branch>
#
# A delivery run may be interrupted after canonical creation and implementation but before
# its first task commit. Dirt plus the creation incarnation distinguishes that live resume
# from a clean empty branch and from an absorbed/reset branch made dirty again.
task_fresh_branch_resume_valid() {
  local root="$1" branch="$2" status
  status=$(git -C "$root" status --porcelain 2>/dev/null) || return 1
  [ -n "$status" ] || [ -n "${OH_HOME:-}" ] || return 1
  task_fresh_branch_incarnation_valid "$root" "$branch"
}

# task_tsv_path_at_ref <root> <doc> <path> <ref>
# Parse one historical design endpoint through plan.sh's canonical grammar. Return 3 only
# when the path is genuinely absent at a readable ref; every read or parse failure is 1.
task_tsv_path_at_ref() {
  local root="$1" doc="$2" rel="$3" ref="$4" entry tmp out status
  entry=$(git -C "$root" ls-tree "$ref" -- "$rel" 2>/dev/null) || return 1
  [ -n "$entry" ] || return 3
  tmp=$(mktemp -d) || return 1
  mkdir -p "$tmp/docs/design" || { rmdir "$tmp" 2>/dev/null; return 1; }
  if ! git -C "$root" show "$ref:$rel" > "$tmp/docs/design/$(basename "$rel")" 2>/dev/null; then
    rm -rf "$tmp"
    return 1
  fi
  out=$(CLAUDE_PROJECT_DIR="$tmp" "$TASK_LEDGER_DIR/scripts/plan.sh" "$doc" 2>/dev/null)
  status=$?
  rm -rf "$tmp"
  [ "$status" -eq 0 ] || return 1
  printf '%s\n' "$out"
}

# task_tsv_at_ref <root> <doc> <ref>
# Resolve the current design path, then parse that path at the named historical endpoint.
task_tsv_at_ref() {
  local root="$1" doc="$2" ref="$3" file rel
  file=$(task_design_file "$root" "$doc") || return 1
  rel="${file#"$root"/}"
  task_tsv_path_at_ref "$root" "$doc" "$rel" "$ref"
}

# task_design_file <root> <doc>
# Resolve exactly one design path without an ls/head producer pipeline whose failure can
# collapse into an empty filename. The subshell keeps nullglob local to this lookup.
task_design_file() (
  local root="$1" doc="$2" matches
  shopt -s nullglob
  matches=("$root"/docs/design/"$doc"-*.md)
  [ "${#matches[@]}" -eq 1 ] || return 1
  printf '%s' "${matches[0]}"
)

# task_tsv_has_id <tsv> <task>
# Return 0 when present, 1 when absent, and 2 when the parser itself failed.
task_tsv_has_id() {
  local rc
  printf '%s\n' "$1" | awk -F"$TASK_US" -v x="$2" '$1==x {found=1} END {exit !found}'
  rc=$?
  case "$rc" in 0|1) return "$rc" ;; *) return 2 ;; esac
}

task_owners_match_trunk() {
  local current="$1" trusted="$2" n owner other state has_id
  while IFS="$TASK_US" read -r n owner; do
    [ -n "$n" ] || continue
    other=$(printf '%s\n' "$current" | awk -F"$TASK_US" -v x="$n" '$1==x {print $3; exit}') || return 1
    [ "$other" = "$owner" ] || {
      echo "task-window: task $n owner '$other' differs from reviewed trunk owner '$owner'." >&2
      return 1
    }
  done <<EOF
$trusted
EOF
  while IFS="$TASK_US" read -r n _; do
    [ -n "$n" ] || continue
    task_tsv_has_id "$trusted" "$n"
    has_id=$?
    [ "$has_id" -ne 2 ] || return 1
    if [ "$has_id" -eq 1 ]; then
      state=$(printf '%s\n' "$current" | awk -F"$TASK_US" -v x="$n" '$1==x {print $2; exit}') || return 1
      [ "$state" = pending ] || {
        echo "task-window: unreviewed task $n may be routed as pending but cannot be completed on this branch." >&2
        return 1
      }
    fi
  done <<EOF
$current
EOF
}

# task_trusted_projection <current-tsv> <reviewed-authority-tsv>
# Project current checkbox state and wording onto reviewed identities, ownership, dependency,
# and blocker authority. This pure projection is shared by the live branch point and original
# incarnation shape so neither consumer can invent a different merge rule.
task_trusted_projection() {
  local current="$1" trusted="$2"
  local n _ owner needs blocked title line current_n state current_owner current_needs current_blocked current_title
  while IFS="$TASK_US" read -r n _ owner needs blocked title; do
    [ -n "$n" ] || continue
    line=$(printf '%s\n' "$current" | awk -F"$TASK_US" -v x="$n" '$1==x {print; exit}') || return 1
    [ -n "$line" ] || {
      echo "task-window: reviewed task $n is absent from the current design." >&2
      return 1
    }
    IFS="$TASK_US" read -r current_n state current_owner current_needs current_blocked current_title <<EOF
$line
EOF
    printf '%s%s%s%s%s%s%s%s%s%s%s\n' \
      "$n" "$TASK_US" "$state" "$TASK_US" "$owner" "$TASK_US" \
      "$needs" "$TASK_US" "$blocked" "$TASK_US" "$current_title"
  done <<EOF
$trusted
EOF
}

# task_id_list_contains <newline-separated-ids> <id>
# Shell-only membership keeps a failed normalizer from becoming an empty successful set.
task_id_list_contains() {
  local list="$1" wanted="$2" item
  while IFS= read -r item; do
    [ "$item" = "$wanted" ] && return 0
  done <<EOF
$list
EOF
  return 1
}

# task_transition_records_from_diff <diff>
# Prints one "done<TAB>id" or "pending<TAB>id" record for each real checkbox transition.
# A task merely reworded in the same state appears on both sides and cancels out; a newly
# routed pending task has no removed done line and is ignored. Direction remains explicit so
# interrupted recovery can require one pending-to-done transition without reparsing raw hunks.
task_transition_records_from_diff() {
  local diff="$1" pending_removed done_added done_removed pending_added n
  pending_removed=$(printf '%s\n' "$diff" | sed -n 's/^-- \[ \] \*\*\([0-9][0-9]*\)\.\*\*.*/\1/p') || return 1
  done_added=$(printf '%s\n' "$diff" | sed -n 's/^+- \[x\] \*\*\([0-9][0-9]*\)\.\*\*.*/\1/p') || return 1
  done_removed=$(printf '%s\n' "$diff" | sed -n 's/^-- \[x\] \*\*\([0-9][0-9]*\)\.\*\*.*/\1/p') || return 1
  pending_added=$(printf '%s\n' "$diff" | sed -n 's/^+- \[ \] \*\*\([0-9][0-9]*\)\.\*\*.*/\1/p') || return 1
  for n in $done_added; do
    if task_id_list_contains "$pending_removed" "$n"; then printf 'done\t%s\n' "$n"; fi
  done
  for n in $pending_added; do
    if task_id_list_contains "$done_removed" "$n"; then printf 'pending\t%s\n' "$n"; fi
  done
  return 0
}

# task_transition_ids_from_diff <diff>
# Prints only real checkbox transition IDs, retaining the historical space-separated API.
task_transition_ids_from_diff() {
  local records direction n out=""
  records=$(task_transition_records_from_diff "$1") || return 1
  while IFS=$'\t' read -r direction n; do
    [ -n "$n" ] || continue
    case " $out " in *" $n "*) ;; *) out="${out}${out:+ }$n" ;; esac
  done <<EOF
$records
EOF
  printf '%s' "$out"
}

# task_transition_ids_between <root> <from> <to> <path>
# Prints checkbox IDs whose state actually changed, ignoring wording-only line edits.
task_transition_ids_between() {
  local root="$1" from="$2" to="$3" path="$4" name doc from_tsv to_tsv rc
  local n state _ line other_state out=""
  name="${path##*/}"; doc="${name:0:4}"
  from_tsv=$(task_tsv_path_at_ref "$root" "$doc" "$path" "$from")
  rc=$?
  case "$rc" in 0) ;; 3) from_tsv="" ;; *) return 1 ;; esac
  to_tsv=$(task_tsv_path_at_ref "$root" "$doc" "$path" "$to")
  rc=$?
  case "$rc" in 0) ;; 3) to_tsv="" ;; *) return 1 ;; esac
  while IFS="$TASK_US" read -r n state _; do
    [ -n "$n" ] || continue
    line=$(printf '%s\n' "$to_tsv" | awk -F"$TASK_US" -v x="$n" '$1==x {print; exit}') || return 1
    if [ -z "$line" ]; then
      case " $out " in *" $n "*) ;; *) out="${out}${out:+ }$n" ;; esac
      continue
    fi
    other_state=$(printf '%s\n' "$line" | awk -F"$TASK_US" '{print $2; exit}') || return 1
    if [ "$state" != "$other_state" ]; then
      case " $out " in *" $n "*) ;; *) out="${out}${out:+ }$n" ;; esac
    fi
  done <<EOF
$from_tsv
EOF
  while IFS="$TASK_US" read -r n state _; do
    [ -n "$n" ] || continue
    task_tsv_has_id "$from_tsv" "$n"
    rc=$?
    [ "$rc" -ne 2 ] || return 1
    if [ "$rc" -eq 1 ]; then
      [ "$state" = done ] || continue
      case " $out " in *" $n "*) ;; *) out="${out}${out:+ }$n" ;; esac
    fi
  done <<EOF
$to_tsv
EOF
  printf '%s' "$out"
}

# task_worktree_transition_ids <root> <path>
# The interrupted-task resume check compares checked-in task state with both staged and
# unstaged changes. Failure to read that diff is different from an empty transition set.
task_worktree_transition_ids() {
  local root="$1" path="$2" diff
  diff=$(git -C "$root" diff --text --unified=0 --no-ext-diff HEAD -- "$path" 2>/dev/null) || return 1
  task_transition_ids_from_diff "$diff" || return 1
}

# task_commits_validate <root> <doc> <owner> <tsv> <base>
# Every pending -> done transition for this track must be the sole task transition in its
# matching canonical task commit, with its review-round trailer. This closes the aggregate-diff
# hole where a later tick could hide in an allowed review commit and consume no boundary.
task_commits_validate() {
  local root="$1" doc="$2" owner="$3" tsv="$4" base="$5" file rel sha parent subject
  local ticks regressed n task_owner trusted_state trusted_owner parents parent_list other trunk_parent state_sha state_trunk common state_common is_regression rc
  local changed_path changed_name changed_doc changed_paths transitions sha_entry trunk_entry trusted trusted_full commits parent_tsv sha_tsv trunk_tsv common_tsv parent_line sha_line trunk_line common_line parent_n parent_state parent_owner parent_rest sha_n sha_state sha_owner sha_rest trusted_rest inherited
  local parent_authority_ref sha_authority_ref parent_authority_tsv sha_authority_tsv sha_trusted_line sha_trusted_owner
  local parent_projection runnable_line runnable_task commit_body history=""
  local owned_ticks="" owned_regressed=""
  TASK_COMMIT_HISTORY=""
  file=$(task_design_file "$root" "$doc") || return 1
  rel="${file#"$root"/}"
  trusted_full="${6:-}"
  if [ -z "$trusted_full" ]; then
    trusted_full=$(task_tsv_at_ref "$root" "$doc" "$base") || {
      echo "task-window: cannot read reviewed task ownership for design $doc from the branch point." >&2
      return 1
    }
  fi
  trusted=$(printf '%s\n' "$trusted_full" | awk -F"$TASK_US" -v OFS="$TASK_US" '{print $1,$3}') || return 1
  task_owners_match_trunk "$tsv" "$trusted" || return 1
  commits=$(git -C "$root" rev-list --reverse --first-parent "$base..HEAD" 2>/dev/null) || {
    echo "task-window: cannot enumerate delivery commits from the branch point." >&2
    return 1
  }
  while IFS= read -r sha; do
    [ -n "$sha" ] || continue
    parents=$(git -C "$root" rev-list --parents -n 1 "$sha" 2>/dev/null) || {
      echo "task-window: cannot inspect parents for commit ${sha%${sha#????????}}." >&2
      return 1
    }
    parent_list="${parents#* }"; parent="${parent_list%% *}"
    [ -n "$parent" ] || continue
    subject=$(git -C "$root" show -s --format=%s "$sha" 2>/dev/null) || {
      echo "task-window: cannot inspect subject for commit ${sha%${sha#????????}}." >&2
      return 1
    }
    trunk_parent=""
    for other in ${parent_list#"$parent"}; do
      git -C "$root" merge-base --is-ancestor "$other" origin/main 2>/dev/null
      rc=$?
      case "$rc" in
        0) trunk_parent="$other"; break ;;
        1) ;;
        *) echo "task-window: cannot classify merge parent ${other%${other#????????}}." >&2; return 1 ;;
      esac
    done
    common=""; trunk_tsv=""; common_tsv=""
    if [ -n "$trunk_parent" ]; then
      common=$(git -C "$root" merge-base "$parent" "$trunk_parent" 2>/dev/null) || {
        echo "task-window: cannot find the common ancestor for merge commit ${sha%${sha#????????}}." >&2
        return 1
      }
      trunk_tsv=$(task_tsv_path_at_ref "$root" "$doc" "$rel" "$trunk_parent") || {
        echo "task-window: cannot parse reviewed task state at merged trunk parent ${trunk_parent%${trunk_parent#????????}}." >&2
        return 1
      }
      if [ -n "$common" ]; then
        common_tsv=$(task_tsv_path_at_ref "$root" "$doc" "$rel" "$common") || {
          echo "task-window: cannot parse reviewed task state at the merge common ancestor." >&2
          return 1
        }
      fi
    fi
    changed_paths=$(git -C "$root" diff --name-only "$parent" "$sha" -- \
      'docs/design/[0-9]*.md' 2>/dev/null) || {
      echo "task-window: cannot enumerate design paths in commit ${sha%${sha#????????}}." >&2
      return 1
    }
    while IFS= read -r changed_path; do
      [ -n "$changed_path" ] || continue
      changed_name="${changed_path##*/}"; changed_doc="${changed_name:0:4}"
      [ "$changed_doc" = "$doc" ] && continue
      transitions=$(task_transition_ids_between "$root" "$parent" "$sha" "$changed_path") || {
        echo "task-window: cannot inspect task transitions in $changed_path at commit ${sha%${sha#????????}}." >&2
        return 1
      }
      [ -n "$transitions" ] || continue
      if [ -n "$trunk_parent" ]; then
        sha_entry=$(git -C "$root" ls-tree "$sha" -- "$changed_path" 2>/dev/null) || {
          echo "task-window: cannot inspect $changed_path at commit ${sha%${sha#????????}}." >&2
          return 1
        }
        trunk_entry=$(git -C "$root" ls-tree "$trunk_parent" -- "$changed_path" 2>/dev/null) || {
          echo "task-window: cannot inspect $changed_path at merged trunk parent ${trunk_parent%${trunk_parent#????????}}." >&2
          return 1
        }
        [ "$sha_entry" = "$trunk_entry" ] && continue
      fi
      echo "task-window: commit ${sha%${sha#????????}} changes task(s) $transitions in design $changed_doc on design $doc's branch." >&2
      return 1
    done <<EOF
$changed_paths
EOF
    parent_tsv=$(task_tsv_path_at_ref "$root" "$doc" "$rel" "$parent") || {
      echo "task-window: cannot parse reviewed task state before commit ${sha%${sha#????????}}." >&2
      return 1
    }
    sha_tsv=$(task_tsv_path_at_ref "$root" "$doc" "$rel" "$sha") || {
      echo "task-window: cannot parse reviewed task state at commit ${sha%${sha#????????}}." >&2
      return 1
    }
    # The merge-base passed to this function advances whenever refreshed main is merged.
    # Applying its final task identities to every earlier first-parent commit would make a
    # legitimate task added by that merge retroactively mandatory. Resolve reviewed authority
    # separately at both endpoints: before the merge it is the older trunk snapshot; at and
    # after the merge it is the newly reviewed snapshot.
    parent_authority_ref=$(git -C "$root" merge-base "$parent" "$base" 2>/dev/null) || {
      echo "task-window: cannot resolve reviewed authority before commit ${sha%${sha#????????}}." >&2
      return 1
    }
    sha_authority_ref=$(git -C "$root" merge-base "$sha" "$base" 2>/dev/null) || {
      echo "task-window: cannot resolve reviewed authority at commit ${sha%${sha#????????}}." >&2
      return 1
    }
    [ -n "$parent_authority_ref" ] && [ -n "$sha_authority_ref" ] || {
      echo "task-window: reviewed authority is absent at commit ${sha%${sha#????????}}." >&2
      return 1
    }
    parent_authority_tsv=$(task_tsv_path_at_ref "$root" "$doc" "$rel" "$parent_authority_ref") || {
      echo "task-window: cannot parse reviewed authority before commit ${sha%${sha#????????}}." >&2
      return 1
    }
    sha_authority_tsv=$(task_tsv_path_at_ref "$root" "$doc" "$rel" "$sha_authority_ref") || {
      echo "task-window: cannot parse reviewed authority at commit ${sha%${sha#????????}}." >&2
      return 1
    }
    ticks=""; regressed=""
    while IFS="$TASK_US" read -r n trusted_state trusted_owner trusted_rest; do
      [ -n "$n" ] || continue
      parent_line=$(printf '%s\n' "$parent_tsv" | awk -F"$TASK_US" -v x="$n" '$1==x {print; exit}') || return 1
      sha_line=$(printf '%s\n' "$sha_tsv" | awk -F"$TASK_US" -v x="$n" '$1==x {print; exit}') || return 1
      [ -n "$parent_line" ] && [ -n "$sha_line" ] || {
        echo "task-window: reviewed task $n is absent at a primary-design endpoint of commit ${sha%${sha#????????}}." >&2
        return 1
      }
      IFS="$TASK_US" read -r parent_n parent_state parent_owner parent_rest <<EOF
$parent_line
EOF
      IFS="$TASK_US" read -r sha_n sha_state sha_owner sha_rest <<EOF
$sha_line
EOF
      sha_trusted_line=$(printf '%s\n' "$sha_authority_tsv" | awk -F"$TASK_US" -v x="$n" '$1==x {print; exit}') || return 1
      [ -n "$sha_trusted_line" ] || {
        echo "task-window: reviewed task $n disappears from reviewed authority at commit ${sha%${sha#????????}}." >&2
        return 1
      }
      sha_trusted_owner=$(printf '%s\n' "$sha_trusted_line" | awk -F"$TASK_US" '{print $3; exit}') || return 1
      [ "$parent_owner" = "$trusted_owner" ] && [ "$sha_owner" = "$sha_trusted_owner" ] || {
        echo "task-window: reviewed task $n changes owner at commit ${sha%${sha#????????}}." >&2
        return 1
      }
      case "$parent_state:$sha_state" in
        pending:done) ticks="${ticks}${ticks:+ }$n" ;;
        done:pending) regressed="${regressed}${regressed:+ }$n" ;;
        pending:pending|done:done) ;;
        *) echo "task-window: reviewed task $n has unreadable endpoint state at commit ${sha%${sha#????????}}." >&2; return 1 ;;
      esac
    done <<EOF
$parent_authority_tsv
EOF

    # A task newly reviewed on refreshed trunk becomes authority only at the exact merge
    # that introduced it. The first-parent endpoint must still match the merge common
    # ancestor and the result must match the trunk parent, preventing a branch-local task
    # with the same id from laundering itself into reviewed authority.
    while IFS="$TASK_US" read -r n sha_state sha_owner sha_rest; do
      [ -n "$n" ] || continue
      task_tsv_has_id "$parent_authority_tsv" "$n"; rc=$?
      [ "$rc" -ne 2 ] || return 1
      if [ "$rc" -eq 0 ]; then
        continue
      fi
      parent_line=$(printf '%s\n' "$parent_tsv" | awk -F"$TASK_US" -v x="$n" '$1==x {print; exit}') || return 1
      sha_line=$(printf '%s\n' "$sha_tsv" | awk -F"$TASK_US" -v x="$n" '$1==x {print; exit}') || return 1
      inherited=0
      if [ -n "$trunk_parent" ] && [ -n "$common" ]; then
        trunk_line=$(printf '%s\n' "$trunk_tsv" | awk -F"$TASK_US" -v x="$n" '$1==x {print; exit}') || return 1
        common_line=$(printf '%s\n' "$common_tsv" | awk -F"$TASK_US" -v x="$n" '$1==x {print; exit}') || return 1
        [ "$parent_line" = "$common_line" ] && [ -n "$sha_line" ] \
          && [ "$sha_line" = "$trunk_line" ] && inherited=1
      fi
      [ "$inherited" = 1 ] || {
        echo "task-window: reviewed task $n is introduced outside an exact trunk merge at commit ${sha%${sha#????????}}." >&2
        return 1
      }
    done <<EOF
$sha_authority_tsv
EOF

    # Identities routed after the authority in force at this point may be appended as
    # pending prose and remain pending, but they may never disappear, complete, reopen, or
    # collide with a later reviewed identity. Compare the union of actual endpoints so a
    # final pending state cannot hide an intermediate tick.
    while IFS="$TASK_US" read -r n parent_state parent_owner parent_rest; do
      [ -n "$n" ] || continue
      task_tsv_has_id "$parent_authority_tsv" "$n"; rc=$?
      [ "$rc" -ne 2 ] || return 1
      if [ "$rc" -eq 0 ]; then
        continue
      fi
      sha_line=$(printf '%s\n' "$sha_tsv" | awk -F"$TASK_US" -v x="$n" '$1==x {print; exit}') || return 1
      task_tsv_has_id "$sha_authority_tsv" "$n"; rc=$?
      [ "$rc" -ne 2 ] || return 1
      if [ "$rc" -eq 0 ]; then
        # The authority-introduction loop above accepts only an exact merge, whose parent
        # side must equal the common ancestor. Reaching here with an actual branch-local
        # record therefore means the identity collided with reviewed trunk authority.
        echo "task-window: unreviewed task $n collides with reviewed trunk authority at commit ${sha%${sha#????????}}." >&2
        return 1
      fi
      [ "$parent_state" = pending ] && [ -n "$sha_line" ] || {
        echo "task-window: unreviewed task $n is removed or completed at commit ${sha%${sha#????????}}." >&2
        return 1
      }
      IFS="$TASK_US" read -r sha_n sha_state sha_owner sha_rest <<EOF
$sha_line
EOF
      [ "$sha_state" = pending ] || {
        echo "task-window: unreviewed task $n is removed or completed at commit ${sha%${sha#????????}}." >&2
        return 1
      }
    done <<EOF
$parent_tsv
EOF
    while IFS="$TASK_US" read -r n sha_state sha_owner sha_rest; do
      [ -n "$n" ] || continue
      sha_line=$(printf '%s\n' "$sha_tsv" | awk -F"$TASK_US" -v x="$n" '$1==x {print; exit}') || return 1
      task_tsv_has_id "$parent_tsv" "$n"; rc=$?
      [ "$rc" -ne 2 ] || return 1
      if [ "$rc" -eq 0 ]; then
        continue
      fi
      # A newly reviewed identity was already proved to be an exact trunk introduction.
      task_tsv_has_id "$sha_authority_tsv" "$n"; rc=$?
      [ "$rc" -ne 2 ] || return 1
      if [ "$rc" -eq 0 ]; then
        continue
      fi
      [ "$sha_state" = pending ] || {
        echo "task-window: unreviewed task $n is introduced completed at commit ${sha%${sha#????????}}." >&2
        return 1
      }
    done <<EOF
$sha_tsv
EOF

    # A merge from refreshed main may legitimately introduce another track's completed task.
    # Classify a transition as inherited only when the merged trunk parent has exactly the
    # resulting state; manual conflict-resolution ticks remain branch-local and are rejected.
    owned_ticks=""; owned_regressed=""
    for n in $ticks $regressed; do
      is_regression=0
      case " $regressed " in *" $n "*) is_regression=1 ;; esac
      # Only a completion can be inherited, and only when trunk itself changed this task
      # from pending at the parents' common ancestor to done. A done -> pending transition
      # is always a branch regression, even if a merge resolution copies trunk's older text.
      if [ "$is_regression" = 0 ] && [ -n "$trunk_parent" ] && [ -n "$common" ]; then
        state_sha=$(printf '%s\n' "$sha_tsv" | awk -F"$TASK_US" -v x="$n" '$1==x {print $2; exit}') || return 1
        state_trunk=$(printf '%s\n' "$trunk_tsv" | awk -F"$TASK_US" -v x="$n" '$1==x {print $2; exit}') || return 1
        state_common=$(printf '%s\n' "$common_tsv" | awk -F"$TASK_US" -v x="$n" '$1==x {print $2; exit}') || return 1
        [ "$state_sha" = done ] && [ "$state_trunk" = done ] \
          && [ "$state_common" = pending ] && continue
      fi
      task_owner=$(printf '%s\n' "$parent_authority_tsv" | awk -F"$TASK_US" -v x="$n" '$1==x {print $3; exit}') || return 1
      [ "$task_owner" = "$owner" ] || {
        echo "task-window: commit ${sha%${sha#????????}} changes task $n from track '$task_owner' on the '$owner' branch." >&2
        return 1
      }
      case "$is_regression" in 1) owned_regressed="${owned_regressed}${owned_regressed:+ }$n" ;;
        *) owned_ticks="${owned_ticks}${owned_ticks:+ }$n" ;; esac
    done
    [ -z "$owned_regressed" ] || {
      echo "task-window: commit ${sha%${sha#????????}} regresses completed task(s): $owned_regressed." >&2
      return 1
    }
    if [ -n "$owned_ticks" ]; then
      case "$owned_ticks" in *' '*)
          echo "task-window: commit ${sha%${sha#????????}} does not contain exactly one matching task transition." >&2
          return 1
          ;;
      esac
      n="$owned_ticks"
      # State comes from the task commit's first parent; owner, dependency, and blocker
      # authority come from the reviewed trunk snapshot in force at that endpoint. Later
      # refreshed-main metadata must neither legalize an historically blocked tick nor
      # invalidate work that was canonical when committed.
      parent_projection=$(task_tsv_at_commit "$root" "$doc" "$parent_authority_tsv" "$parent") || {
        echo "task-window: cannot reconstruct reviewed runnability before commit ${sha%${sha#????????}}." >&2
        return 1
      }
      runnable_line=$(task_first_runnable "$parent_projection" "$owner" "") || {
        echo "task-window: task $n was not runnable under reviewed authority at commit ${sha%${sha#????????}}." >&2
        return 1
      }
      runnable_task="${runnable_line%%"$TASK_US"*}"
      [ "$runnable_task" = "$n" ] || {
        echo "task-window: task $n was not the next runnable task under reviewed authority at commit ${sha%${sha#????????}} (task $runnable_task was)." >&2
        return 1
      }
      case "$subject" in "task $n: "*) ;; *)
        echo "task-window: task $n was completed in noncanonical commit ${sha%${sha#????????}}: $subject" >&2
        return 1 ;; esac
      commit_body=$(git -C "$root" show -s --format=%B "$sha" 2>/dev/null) || {
        echo "task-window: cannot inspect task $n commit ${sha%${sha#????????}} body." >&2
        return 1
      }
      printf '%s\n' "$commit_body" | grep -qE '^Review-Rounds: [0-9]+$' || {
        echo "task-window: task $n commit ${sha%${sha#????????}} has no Review-Rounds trailer." >&2
        return 1
      }
      history="${history}${history:+
}${sha}${TASK_US}${n}${TASK_US}${task_owner}${TASK_US}${parent_authority_ref}"
    fi
  done <<EOF
$commits
EOF
  TASK_COMMIT_HISTORY="$history"
}

# task_is_done <tsv> <task> <simulated-done-csv>
task_is_done() {
  local state
  state=$(printf '%s\n' "$1" | awk -F"$TASK_US" -v n="$2" '$1==n {print $2; exit}') || return 2
  [ "$state" = done ] && return 0
  case ",$3," in *",$2,"*) return 0 ;; esac
  return 1
}

# task_first_runnable <tsv> <owner> [simulated-done-csv]
# Prints "<n><US><title>". This is the one runnable-task algorithm used by next.sh and by
# continuation-window projection, so a grant cannot disagree with the gate it authorizes.
task_first_runnable() {
  local tsv="$1" owner="$2" simulated="${3:-}" n st ow ne bl ti ok d deps sorted rc
  sorted=$(printf '%s\n' "$tsv" | sort -t"$TASK_US" -k1,1n) || return 2
  while IFS="$TASK_US" read -r n st ow ne bl ti; do
    [ "$st" = pending ] || continue
    case ",$simulated," in *",$n,"*) continue ;; esac
    [ "$ow" = "$owner" ] || continue
    [ -z "$bl" ] || continue
    ok=1
    if [ -n "$ne" ]; then
      deps="${ne//,/$'\n'}"
      while IFS= read -r d; do
        [ -n "$d" ] || { ok=0; break; }
        task_is_done "$tsv" "$d" "$simulated"
        rc=$?
        case "$rc" in 0) ;; 1) ok=0; break ;; *) return 2 ;; esac
      done <<EOF
$deps
EOF
    fi
    [ "$ok" = 1 ] || continue
    printf '%s%s%s' "$n" "$TASK_US" "$ti"
    return 0
  done <<EOF
$sorted
EOF
  return 1
}

# task_project_ids <tsv> <owner> <count>
# Repeatedly applies task_first_runnable to simulated completions. It skips blocked tasks
# exactly as next.sh does and stops only when the canonical selection finds no runnable task.
task_project_ids() {
  local tsv="$1" owner="$2" count="$3" simulated="" out n i=0 available limit rc
  available=$(printf '%s\n' "$tsv" | awk -F"$TASK_US" -v o="$owner" '$2=="pending" && $3==o {n++} END {print n+0}') || return 1
  limit=$(jq -nr --arg requested "$count" --argjson available "$available" '
    ($requested | fromjson) as $r
    | if $r < $available then $r else $available end
    | floor | tostring
  ' 2>/dev/null) || return 1
  while [ "$i" -lt "$limit" ]; do
    out=$(task_first_runnable "$tsv" "$owner" "$simulated")
    rc=$?
    case "$rc" in 0) ;; 1) break ;; *) return 1 ;; esac
    n="${out%%"$TASK_US"*}"
    if [ -n "$simulated" ]; then simulated="$simulated,$n"; else simulated="$n"; fi
    i=$((i+1))
  done
  printf '%s' "$simulated"
}

# Reconstruct the trusted task states at the recorded checkpoint commit. Ownership,
# dependency and blocking metadata comes from the already branch-point-filtered TSV; task
# completion state comes from the exact recorded HEAD.
task_tsv_at_commit() {
  local root="$1" doc="$2" tsv="$3" ref="$4" historical line n _ owner needs blocked title state
  historical=$(task_tsv_at_ref "$root" "$doc" "$ref") || return 1
  while IFS="$TASK_US" read -r n _ owner needs blocked title; do
    [ -n "$n" ] || continue
    line=$(printf '%s\n' "$historical" | awk -F"$TASK_US" -v x="$n" '$1==x {print; exit}') || return 1
    [ -n "$line" ] || return 1
    state=$(printf '%s\n' "$line" | awk -F"$TASK_US" '{print $2; exit}') || return 1
    case "$state" in pending|done) ;; *) return 1 ;; esac
    printf '%s%s%s%s%s%s%s%s%s%s%s\n' \
      "$n" "$TASK_US" "$state" "$TASK_US" "$owner" "$TASK_US" \
      "$needs" "$TASK_US" "$blocked" "$TASK_US" "$title"
  done <<EOF
$tsv
EOF
}

task_branch_point() {
  local root="$1" remote_status symbolic_status remote_refs remote_ref
  # Parser and isolated harness fixtures may intentionally have no remote-tracking ref and
  # use local main as their reviewed authority. Once origin/main exists, however, it is the
  # authority: an unreadable/failed merge-base must not silently downgrade to a stale local
  # main that predates reviewed task metadata. `show-ref --verify` is available on the
  # harness's existing Git baseline; its missing status is ambiguous for a non-resolving
  # symbolic ref, so confirm that case separately before accepting remote absence.
  git -C "$root" show-ref --verify --quiet refs/remotes/origin/main 2>/dev/null
  remote_status=$?
  case "$remote_status" in
    0) git -C "$root" merge-base origin/main HEAD 2>/dev/null ;;
    1)
      git -C "$root" symbolic-ref -q refs/remotes/origin/main >/dev/null 2>&1
      symbolic_status=$?
      case "$symbolic_status" in
        0) return 1 ;;
        1) ;;
        *) return 1 ;;
      esac
      remote_refs=$(git -C "$root" for-each-ref --format='%(refname)' \
        refs/remotes/origin/main 2>/dev/null) || return 1
      while IFS= read -r remote_ref; do
        [ "$remote_ref" = refs/remotes/origin/main ] && return 1
      done <<EOF
$remote_refs
EOF
      git -C "$root" merge-base main HEAD 2>/dev/null
      ;;
    *) return 1 ;;
  esac
}

# task_commit_first_parent <root> <commit>
# The delivery incarnation starts at a first-parent task commit. Its first parent is the
# reviewed snapshot that fixed the branch spelling and track ownership for that incarnation.
task_commit_first_parent() {
  local root="$1" commit="$2" parents parent_list parent
  parents=$(git -C "$root" rev-list --parents -n 1 "$commit" 2>/dev/null) || return 1
  parent_list="${parents#* }"; parent="${parent_list%% *}"
  [ -n "$parent" ] || return 1
  printf '%s' "$parent"
}

# task_branch_shape_base <root> [latest-branch-point]
# Branch spelling and owner are properties of the delivery incarnation, not of a later
# refreshed-main merge. The first still-unmerged first-parent commit starts that incarnation;
# its first parent is the reviewed snapshot that chose suffixless versus per-track naming.
task_branch_shape_base() {
  local root="$1" base="${2:-}" commits first
  [ -n "$base" ] || base=$(task_branch_point "$root") || return 1
  commits=$(git -C "$root" rev-list --reverse --first-parent "$base..HEAD" 2>/dev/null) || return 1
  first="${commits%%$'\n'*}"
  if [ -z "$first" ]; then printf '%s' "$base"; return 0; fi
  task_commit_first_parent "$root" "$first"
}

# task_history_record <validated-history> <task-commit> <task>
# Print the one canonical transition record for a task boundary. The history is emitted by
# task_commits_validate only after every first-parent endpoint, reviewed-authority change,
# transition, commit subject, and trailer has passed. Consumers never reconstruct a second
# opinion about the owner that admitted the task commit.
task_history_record() {
  local history="$1" commit="$2" task="$3" matches count
  matches=$(printf '%s\n' "$history" | awk -F"$TASK_US" -v c="$commit" -v n="$task" \
    '$1 == c && $2 == n {print}') || return 1
  count=$(printf '%s\n' "$matches" | awk 'NF {n++} END {print n+0}') || return 1
  [ "$count" -eq 1 ] || return 1
  printf '%s' "$matches"
}

# task_boundary <branch-point> <validated-history>
# Prints "<branch-point><US><incarnation><US><boundary-commit><US><boundary-task>". The
# incarnation is the first still-unmerged task commit: stable across main merges, new after
# the preceding delivery merges. An empty result means this branch has completed no task.
task_boundary() {
  local base="$1" history="$2" sha n owner authority first="" latest=""
  while IFS="$TASK_US" read -r sha n owner authority; do
    [ -n "$sha" ] || continue
    [ -n "$n" ] && [ -n "$owner" ] && [ -n "$authority" ] || return 2
    [ -n "$first" ] || first="$sha"
    latest="$base$TASK_US$first$TASK_US$sha$TASK_US$n"
  done <<EOF
$history
EOF
  printf '%s' "$latest"
}

# task_authority_load <root> <branch> <doc> <current-tsv> [latest-branch-point]
#
# Build the one consequential authority view used by live selection, checkpoint history,
# persisted choices, completion, and CI. Globals are published only after the complete view
# validates, so a failed producer cannot leave a partially trusted context behind:
# TASK_AUTHORITY_BASE, TASK_AUTHORITY_TRUSTED_TSV, TASK_AUTHORITY_SHAPE_TSV,
# TASK_AUTHORITY_OWNER, TASK_AUTHORITY_HISTORY, and the exact ROOT/BRANCH/DOC/CURRENT
# identity checked by task_gate_evaluate before it consumes the loaded view.
task_authority_load() {
  local root="$1" branch="$2" doc="$3" current="$4" base="${5:-}"
  local base_authority trusted shape_base shape_authority shape owner history parsed
  TASK_AUTHORITY_BASE=""; TASK_AUTHORITY_TRUSTED_TSV=""; TASK_AUTHORITY_SHAPE_TSV=""
  TASK_AUTHORITY_OWNER=""; TASK_AUTHORITY_HISTORY=""; TASK_AUTHORITY_ERROR=""
  TASK_AUTHORITY_ROOT=""; TASK_AUTHORITY_BRANCH=""; TASK_AUTHORITY_DOC=""; TASK_AUTHORITY_CURRENT=""
  [ -n "$base" ] || base=$(task_branch_point "$root") || {
    TASK_AUTHORITY_ERROR=base
    echo "task-window: cannot resolve the delivery branch point against origin/main or main." >&2
    return 1
  }
  base_authority=$(task_tsv_at_ref "$root" "$doc" "$base") || {
    TASK_AUTHORITY_ERROR=trusted; return 1; }
  trusted=$(task_trusted_projection "$current" "$base_authority") || {
    TASK_AUTHORITY_ERROR=trusted; return 1; }
  shape_base=$(task_branch_shape_base "$root" "$base") || {
    TASK_AUTHORITY_ERROR=shape; return 1; }
  if [ "$shape_base" = "$base" ]; then
    shape_authority="$base_authority"
  else
    shape_authority=$(task_tsv_at_ref "$root" "$doc" "$shape_base") || {
      TASK_AUTHORITY_ERROR=shape; return 1; }
  fi
  shape=$(task_trusted_projection "$current" "$shape_authority") || {
    TASK_AUTHORITY_ERROR=shape; return 1; }
  parsed=$(delivery_branch_parse "$branch" 2>/dev/null) || {
    TASK_AUTHORITY_ERROR=branch
    echo "task-window: malformed delivery branch '$branch'." >&2
    task_branch_shape_diagnose "$branch" "$doc" "$shape" || :
    return 1
  }
  owner=$(task_branch_owner "$branch" "$doc" "$shape") || {
    TASK_AUTHORITY_ERROR=branch
    echo "task-window: $branch is not the canonical branch for design $doc's reviewed track shape." >&2
    task_branch_shape_diagnose "$branch" "$doc" "$shape" || :
    return 1
  }
  task_commits_validate "$root" "$doc" "$owner" "$current" "$base" "$base_authority" || {
    TASK_AUTHORITY_ERROR=history; return 1; }
  history="$TASK_COMMIT_HISTORY"
  TASK_AUTHORITY_BASE="$base"
  TASK_AUTHORITY_TRUSTED_TSV="$trusted"
  TASK_AUTHORITY_SHAPE_TSV="$shape"
  TASK_AUTHORITY_OWNER="$owner"
  TASK_AUTHORITY_HISTORY="$history"
  TASK_AUTHORITY_ROOT="$root"
  TASK_AUTHORITY_BRANCH="$branch"
  TASK_AUTHORITY_DOC="$doc"
  TASK_AUTHORITY_CURRENT="$current"
}

task_record_value() {
  awk -v k="$2" '$0 ~ "^"k": " {sub("^"k":[[:space:]]*", ""); print; exit}' "$1"
}

task_record_shape_valid() {
  awk '
    BEGIN {
      old=split("choice-version sequence branch branch-point incarnation boundary-commit boundary-task doc track choice window-tasks policy-blob permitted-tasks tree head at chosen-by record-sha256", oldkeys, " ")
      fresh=split("choice-version sequence branch branch-point incarnation boundary-commit boundary-task doc track choice window-tasks policy-source policy-blob policy-sha256 permitted-tasks tree head at chosen-by choice-source record-sha256", newkeys, " ")
    }
    {
      key=$0; sub(/:.*/, "", key)
      if (NR == 1) {
        if ($0 == "choice-version: 3") { count=old; for (i=1;i<=old;i++) keys[i]=oldkeys[i] }
        else if ($0 == "choice-version: 4") { count=fresh; for (i=1;i<=fresh;i++) keys[i]=newkeys[i] }
        else exit 1
      }
      if (NR > count || key != keys[NR]) exit 1
    }
    END { if (NR != count) exit 1 }
  ' "$1"
}

task_record_checksum() {
  if command -v shasum >/dev/null 2>&1; then
    sed '$d' "$1" | shasum -a 256 | awk '{print $1}'
  else
    sed '$d' "$1" | sha256sum | awk '{print $1}'
  fi
}

task_full_commit_valid() {
  local full
  printf '%s\n' "$2" | grep -Eq '^[0-9a-f]{40,64}$' || return 1
  full=$(git -C "$1" rev-parse --verify "$2^{commit}" 2>/dev/null) || return 1
  [ "$full" = "$2" ]
}

task_full_blob_valid() {
  local full
  printf '%s\n' "$2" | grep -Eq '^[0-9a-f]{40,64}$' || return 1
  full=$(git -C "$1" rev-parse --verify "$2^{blob}" 2>/dev/null) || return 1
  [ "$full" = "$2" ]
}

# Loads and validates all records for the current branch. Globals set:
# TASK_RECORD_COUNT, TASK_TERMINAL_PR, TASK_LATEST_BOUNDARY_CHOICE,
# TASK_COVERING_RECORD and TASK_HISTORY_FILES.
task_records_load() {
  local root="$1" branch="$2" doc="$3" owner="$4" tsv="$5" base="$6" incarnation="$7"
  local boundary_commit="$8" boundary_task="$9" candidate="${10}" history="${11}"
  local dir file name canonical expected=1 version rbranch rbase rincarnation rcommit rtask rdoc rtrack choice window permitted sequence
  local policy_blob policy_window policy_source policy_sha policy_actual tree rhead at chosen choice_source checksum expected_checksum expected_chosen
  local record_authority_tsv record_tsv expected_permitted
  local task_state task_owner boundary_owner boundary_record permitted_task permitted_lines
  TASK_RECORD_COUNT=0; TASK_TERMINAL_PR=""; TASK_LATEST_BOUNDARY_CHOICE=""
  TASK_COVERING_RECORD=""; TASK_HISTORY_FILES=""
  dir=$(task_ledger_dir "$root" "$branch" "$incarnation")
  if [ -e "$dir" ] || [ -L "$dir" ]; then
    [ -d "$dir" ] && [ ! -L "$dir" ] && [ -r "$dir" ] && [ -x "$dir" ] || return 1
  else
    return 0
  fi
  # Dot-prefixed files are the writer's provisional namespace. They never become accepted
  # evidence and remain inert if publication is interrupted before unlink. Every visible
  # entry is still required to be the next canonical regular, non-symlink record.
  for file in "$dir"/*; do
    [ -e "$file" ] || [ -L "$file" ] || continue
    name="${file##*/}"
    canonical=$(printf '%06d.choice' "$expected")
    [ "$name" = "$canonical" ] && [ -f "$file" ] && [ ! -L "$file" ] && [ -r "$file" ] || {
      echo "task-window: noncanonical choice record $file." >&2
      return 1
    }
    task_record_shape_valid "$file" || {
      echo "task-window: invalid or duplicate fields in choice record $file." >&2
      return 1
    }
    version=$(task_record_value "$file" choice-version) || return 1
    sequence=$(task_record_value "$file" sequence) || return 1
    rbranch=$(task_record_value "$file" branch) || return 1
    rbase=$(task_record_value "$file" branch-point) || return 1
    rincarnation=$(task_record_value "$file" incarnation) || return 1
    rcommit=$(task_record_value "$file" boundary-commit) || return 1
    rtask=$(task_record_value "$file" boundary-task) || return 1
    rdoc=$(task_record_value "$file" doc) || return 1
    rtrack=$(task_record_value "$file" track) || return 1
    choice=$(task_record_value "$file" choice) || return 1
    window=$(task_record_value "$file" window-tasks) || return 1
    policy_source=default; policy_sha=""
    if [ "$version" = 4 ]; then
      policy_source=$(task_record_value "$file" policy-source) || return 1
    fi
    policy_blob=$(task_record_value "$file" policy-blob) || return 1
    if [ "$version" = 4 ]; then
      policy_sha=$(task_record_value "$file" policy-sha256) || return 1
    fi
    permitted=$(task_record_value "$file" permitted-tasks) || return 1
    tree=$(task_record_value "$file" tree) || return 1
    rhead=$(task_record_value "$file" head) || return 1
    at=$(task_record_value "$file" at) || return 1
    chosen=$(task_record_value "$file" chosen-by) || return 1
    choice_source=legacy
    if [ "$version" = 4 ]; then choice_source=$(task_record_value "$file" choice-source) || return 1; fi
    checksum=$(task_record_value "$file" record-sha256) || return 1
    if { [ "$version" != 3 ] && [ "$version" != 4 ]; } || [ "$sequence" != "$expected" ]; then
      echo "task-window: invalid choice record $file (version or sequence mismatch)." >&2
      return 1
    fi
    TASK_RECORD_COUNT=$expected
    expected=$((expected+1))
    if [ "$rbranch" != "$branch" ] || [ "$rdoc" != "$doc" ] || [ "$rtrack" != "$owner" ]; then
      echo "task-window: invalid choice record $file (version, sequence, branch, doc, or track mismatch)." >&2
      return 1
    fi
    [ "$rincarnation" = "$incarnation" ] || {
      echo "task-window: choice record $file belongs to a different branch incarnation." >&2
      return 1
    }
    task_full_commit_valid "$root" "$rbase" || {
      echo "task-window: invalid branch-point hash in choice record $file." >&2; return 1; }
    task_full_commit_valid "$root" "$rincarnation" || {
      echo "task-window: invalid incarnation hash in choice record $file." >&2; return 1; }
    task_full_commit_valid "$root" "$rcommit" || {
      echo "task-window: invalid boundary-commit hash in choice record $file." >&2; return 1; }
    task_full_commit_valid "$root" "$rhead" || {
      echo "task-window: invalid HEAD hash in choice record $file." >&2; return 1; }
    if [ "$version" = 3 ] || [ "$policy_source" = default ]; then
      task_full_blob_valid "$root" "$policy_blob" || {
        echo "task-window: invalid policy blob in choice record $file." >&2; return 1; }
    else
      [ "$policy_source" = local ] && [ "$policy_blob" = - ] || {
        echo "task-window: invalid local policy source in choice record $file." >&2; return 1; }
    fi
    case "$rtask" in ""|*[!0-9]*)
      echo "task-window: invalid boundary task in choice record $file." >&2; return 1 ;; esac
    printf '%s\n' "$tree" | grep -Eq '^[0-9a-f]{16}$' || {
      echo "task-window: invalid tree digest in choice record $file." >&2; return 1; }
    printf '%s\n' "$at" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' || {
      echo "task-window: invalid timestamp in choice record $file." >&2; return 1; }
    printf '%s\n' "$checksum" | grep -Eq '^[0-9a-f]{64}$' || {
      echo "task-window: invalid checksum in choice record $file." >&2; return 1; }
    printf '{"continuation_window_tasks":%s,"review_window_rounds":1}' "$window" | task_policy_parse >/dev/null || {
      echo "task-window: invalid window in choice record $file." >&2; return 1; }
    if [ "$version" = 3 ]; then
      policy_window=$(git -C "$root" cat-file -p "$policy_blob" 2>/dev/null | task_legacy_policy_parse) || {
        echo "task-window: unreadable policy snapshot in choice record $file." >&2; return 1; }
      [ "$window" = "$policy_window" ] || {
        echo "task-window: window does not match the recorded policy in $file." >&2; return 1; }
    else
      printf '%s\n' "$policy_sha" | grep -Eq '^[0-9a-f]{64}$' || {
        echo "task-window: invalid policy hash in choice record $file." >&2; return 1; }
      if [ "$policy_source" = default ]; then
        policy_actual=$(if command -v shasum >/dev/null 2>&1; then git -C "$root" cat-file -p "$policy_blob" 2>/dev/null | shasum -a 256 | awk '{print $1}'; else git -C "$root" cat-file -p "$policy_blob" 2>/dev/null | sha256sum | awk '{print $1}'; fi) || return 1
        [ "$policy_actual" = "$policy_sha" ] || {
          echo "task-window: default policy hash mismatch in choice record $file." >&2; return 1; }
      fi
    fi
    git -C "$root" merge-base --is-ancestor "$rcommit" HEAD 2>/dev/null || {
      echo "task-window: stale choice record $file; boundary commit is not in this branch." >&2
      return 1
    }
    git -C "$root" merge-base --is-ancestor "$rbase" HEAD 2>/dev/null || {
      echo "task-window: invalid choice record $file; recorded branch point is not in this branch." >&2
      return 1
    }
    git -C "$root" merge-base --is-ancestor "$rincarnation" "$rcommit" 2>/dev/null || {
      echo "task-window: invalid choice record $file; incarnation is not in its task history." >&2
      return 1
    }
    git -C "$root" merge-base --is-ancestor "$rcommit" "$rhead" 2>/dev/null \
      && git -C "$root" merge-base --is-ancestor "$rhead" HEAD 2>/dev/null || {
      echo "task-window: invalid choice record $file; recorded HEAD is outside this branch history." >&2
      return 1
    }
    # The record branch point supplies then-current state and bounded projection. Boundary
    # ownership comes only from the already validated task-commit manifest: later exact
    # trunk merges cannot cause record reload to reinterpret the transition independently.
    record_authority_tsv=$(task_tsv_at_ref "$root" "$doc" "$rbase") || {
      echo "task-window: cannot reconstruct reviewed authority for $file." >&2; return 1; }
    record_tsv=$(task_tsv_at_commit "$root" "$doc" "$record_authority_tsv" "$rhead") || {
      echo "task-window: cannot reconstruct the recorded task boundary for $file." >&2; return 1; }
    task_state=$(printf '%s\n' "$record_tsv" | awk -F"$TASK_US" -v n="$rtask" '$1==n {print $2; exit}') || return 1
    boundary_record=$(task_history_record "$history" "$rcommit" "$rtask") || {
      echo "task-window: boundary task in $file is absent from validated task history." >&2; return 1; }
    IFS="$TASK_US" read -r _ _ boundary_owner _ <<EOF
$boundary_record
EOF
    [ "$task_state" = done ] && [ "$boundary_owner" = "$owner" ] || {
      echo "task-window: invalid choice record $file; boundary task does not match its recorded reviewed state." >&2
      return 1
    }
    case "$choice" in
      continue)
        expected_chosen="human — selected \"$TASK_CONTINUE_LABEL\" at the task-boundary checkpoint"
        case "$permitted" in ""|none|*[!0-9,]*)
          echo "task-window: invalid permitted task list in $file." >&2; return 1 ;; esac
        case "$permitted" in ,*|*,|*,,*)
          echo "task-window: malformed permitted task list in $file." >&2; return 1 ;; esac
        permitted_lines="${permitted//,/$'\n'}"
        while IFS= read -r permitted_task; do
          [ -n "$permitted_task" ] || return 1
          task_owner=$(printf '%s\n' "$record_tsv" | awk -F"$TASK_US" -v n="$permitted_task" '$1==n {print $3; exit}') || return 1
          [ "$task_owner" = "$owner" ] || {
            echo "task-window: permitted task $permitted_task in $file is absent or belongs to another track." >&2
            return 1
          }
        done <<EOF
$permitted_lines
EOF
        expected_permitted=$(task_project_ids "$record_tsv" "$owner" "$window") || return 1
        [ "$permitted" = "$expected_permitted" ] || {
          echo "task-window: permitted tasks do not match the exact bounded projection in $file." >&2
          return 1
        }
        ;;
      pr|stop)
        if [ "$choice" = pr ]; then expected_chosen="human — selected \"$TASK_PR_LABEL\" at the task-boundary checkpoint"
        else expected_chosen="human — selected \"$TASK_STOP_LABEL\" at the task-boundary checkpoint"; fi
        [ "$permitted" = none ] || {
          echo "task-window: terminal choice record $file unexpectedly permits tasks." >&2; return 1; }
        ;;
      *) echo "task-window: invalid choice '$choice' in $file." >&2; return 1 ;;
    esac
    [ "$chosen" = "$expected_chosen" ] || {
      echo "task-window: invalid human-choice provenance in $file." >&2; return 1; }
    [ -n "$choice_source" ] || { echo "task-window: missing human-choice source in $file." >&2; return 1; }
    expected_checksum=$(task_record_checksum "$file") || return 1
    [ "$checksum" = "$expected_checksum" ] || {
      echo "task-window: choice record checksum mismatch in $file." >&2; return 1; }
    TASK_HISTORY_FILES="${TASK_HISTORY_FILES}${TASK_HISTORY_FILES:+
}$file"
    [ "$choice" = pr ] && TASK_TERMINAL_PR="$file"
    if [ "$rcommit" = "$boundary_commit" ] && [ "$rtask" = "$boundary_task" ]; then
      TASK_LATEST_BOUNDARY_CHOICE="$choice"
    fi
    if [ "$choice" = continue ]; then
      case ",$permitted," in *",$candidate,"*) TASK_COVERING_RECORD="$file" ;; esac
    fi
  done
}

# task_gate_evaluate <root> <branch> <doc> <tsv> <candidate>
# Sets TASK_GATE_STATE: fresh | covered | checkpoint | stop | pr | error.
task_gate_evaluate() {
  local root="$1" branch="$2" doc="$3" tsv="$4" candidate="$5" boundary owner
  TASK_GATE_STATE=error; TASK_GATE_BOUNDARY_TASK=""; TASK_GATE_BOUNDARY_COMMIT=""
  TASK_GATE_BRANCH_POINT=""; TASK_GATE_INCARNATION=""; TASK_GATE_MESSAGE=""
  [ "${TASK_AUTHORITY_ROOT:-}" = "$root" ] \
    && [ "${TASK_AUTHORITY_BRANCH:-}" = "$branch" ] \
    && [ "${TASK_AUTHORITY_DOC:-}" = "$doc" ] \
    && [ "${TASK_AUTHORITY_CURRENT:-}" = "$tsv" ] || {
      echo "task-window: no matching validated authority context is loaded." >&2
      return 1
    }
  owner="$TASK_AUTHORITY_OWNER"
  boundary=$(task_boundary "$TASK_AUTHORITY_BASE" "$TASK_AUTHORITY_HISTORY") || return 1
  if [ -z "$boundary" ]; then
    if [ -n "${OH_HOME:-}" ]; then
      "$OH_HOME/oh" --root "$root" initial-check "$doc" "$candidate" || return 1
    fi
    TASK_GATE_STATE=fresh
    return 0
  fi
  TASK_GATE_BRANCH_POINT="${boundary%%"$TASK_US"*}"
  boundary="${boundary#*"$TASK_US"}"
  TASK_GATE_INCARNATION="${boundary%%"$TASK_US"*}"
  boundary="${boundary#*"$TASK_US"}"
  TASK_GATE_BOUNDARY_COMMIT="${boundary%%"$TASK_US"*}"
  TASK_GATE_BOUNDARY_TASK="${boundary#*"$TASK_US"}"
  task_records_load "$root" "$branch" "$doc" "$owner" "$TASK_AUTHORITY_TRUSTED_TSV" \
    "$TASK_GATE_BRANCH_POINT" "$TASK_GATE_INCARNATION" "$TASK_GATE_BOUNDARY_COMMIT" \
    "$TASK_GATE_BOUNDARY_TASK" "$candidate" "$TASK_AUTHORITY_HISTORY" || return 1
  if [ -n "$TASK_TERMINAL_PR" ]; then TASK_GATE_STATE=pr; return 0; fi
  if [ -n "$TASK_COVERING_RECORD" ]; then TASK_GATE_STATE=covered; return 0; fi
  if [ "$TASK_LATEST_BOUNDARY_CHOICE" = stop ]; then TASK_GATE_STATE=stop; return 0; fi
  if [ -n "${OH_HOME:-}" ]; then
    "$OH_HOME/oh" --root "$root" initial-check "$doc" "$candidate"
    case $? in 0) TASK_GATE_STATE=covered; return 0 ;; 3) ;; *) return 1 ;; esac
  fi
  TASK_GATE_STATE=checkpoint
}

task_choice_add() {
  local root="$1" branch="$2" doc="$3" tsv="$4" choice="$5" label="$6" owner
  local candidate_line candidate window policy_blob policy_source policy_sha permitted dir n tmp trusted_tsv file tree head checksum
  local choice_source="${7:-host-hook}" prior_choice
  case "$choice" in continue|pr|stop) ;; *) return 1 ;; esac
  # A checkpoint choice recorded over an uncommitted design-doc edit projects the grant
  # from the dirty tree, not from HEAD — the same hazard next.sh already refuses task
  # discovery on. Recovery's interrupted, still-uncommitted tick is exactly this shape, so
  # a human answering the checkpoint it presents must not mint a grant around the very task
  # in flight.
  file=$(task_design_file "$root" "$doc") || return 1
  "${OH_HOME:-$root}/core/scripts/tree-digest.sh" --check-index >/dev/null 2>&1 || return 1
  git -C "$root" diff --quiet HEAD -- "${file#"$root"/}" 2>/dev/null || return 1
  tree=$(CLAUDE_PROJECT_DIR="$root" "${OH_HOME:-$root}/core/scripts/tree-digest.sh" 2>/dev/null) || return 1
  head=$(git -C "$root" rev-parse HEAD 2>/dev/null) || return 1
  task_authority_load "$root" "$branch" "$doc" "$tsv" || return 1
  owner="$TASK_AUTHORITY_OWNER"
  trusted_tsv="$TASK_AUTHORITY_TRUSTED_TSV"
  candidate_line=$(task_first_runnable "$trusted_tsv" "$owner" "") || return 1
  candidate="${candidate_line%%"$TASK_US"*}"
  task_gate_evaluate "$root" "$branch" "$doc" "$tsv" "$candidate" || return 1
  case "$TASK_GATE_STATE" in checkpoint|stop) ;; *) return 1 ;; esac
  window=$(task_policy_window "$root") || return 1
  review_policy_load "$root" || return 1
  policy_source="$REVIEW_POLICY_SOURCE"
  policy_sha=$(if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$REVIEW_POLICY_FILE" | awk '{print $1}'; else sha256sum "$REVIEW_POLICY_FILE" | awk '{print $1}'; fi) || return 1
  if [ "$policy_source" = default ]; then
    policy_blob=$(git -C "$root" rev-parse origin/main:core/delivery-policy.json 2>/dev/null) || return 1
    task_full_blob_valid "$root" "$policy_blob" || return 1
  else
    policy_blob=-
  fi
  if [ "$choice" = continue ]; then
    permitted=$(task_project_ids "$trusted_tsv" "$owner" "$window") || return 1
    [ -n "$permitted" ] || return 1
  else
    permitted=none
  fi
  dir=$(task_ledger_dir "$root" "$branch" "$TASK_GATE_INCARNATION")
  mkdir -p "$dir" || return 1
  if [ "$choice_source" != host-hook ]; then
    for prior_choice in "$dir"/*.choice; do
      [ -f "$prior_choice" ] || continue
      [ "$(task_record_value "$prior_choice" choice-source)" != "$choice_source" ] || {
        echo 'task-window: this exact host answer was already recorded; inspect task-status.sh before continuing.' >&2
        return 1
      }
    done
  fi
  n=$((TASK_RECORD_COUNT + 1))
  tmp="$dir/.choice-$n.$$"
  {
    echo "choice-version: 4"
    echo "sequence: $n"
    echo "branch: $branch"
    echo "branch-point: $TASK_GATE_BRANCH_POINT"
    echo "incarnation: $TASK_GATE_INCARNATION"
    echo "boundary-commit: $TASK_GATE_BOUNDARY_COMMIT"
    echo "boundary-task: $TASK_GATE_BOUNDARY_TASK"
    echo "doc: $doc"
    echo "track: ${owner:-single}"
    echo "choice: $choice"
    echo "window-tasks: $window"
    echo "policy-source: $policy_source"
    echo "policy-blob: $policy_blob"
    echo "policy-sha256: $policy_sha"
    echo "permitted-tasks: $permitted"
    echo "tree: $tree"
    echo "head: $head"
    echo "at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "chosen-by: human — selected \"$label\" at the task-boundary checkpoint"
    echo "choice-source: $choice_source"
  } > "$tmp" || { rm -f "$tmp"; return 1; }
  checksum=$(if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$tmp" | awk '{print $1}'; else sha256sum "$tmp" | awk '{print $1}'; fi) \
    || { rm -f "$tmp"; return 1; }
  echo "record-sha256: $checksum" >> "$tmp" || { rm -f "$tmp"; return 1; }
  local final
  final=$(printf '%s/%06d.choice' "$dir" "$n")
  ln "$tmp" "$final" 2>/dev/null || { rm -f "$tmp"; return 1; }
  rm -f "$tmp" || { rm -f "$final"; return 1; }
}

task_history_render() {
  local root="$1" branch="$2" file boundary choice window permitted at
  echo "Task checkpoint history:"
  if [ -z "${TASK_HISTORY_FILES:-}" ]; then
    echo "- none (the run did not cross a completed-task boundary)"
    return 0
  fi
  while IFS= read -r file; do
    boundary=$(task_record_value "$file" boundary-task) || return 1
    choice=$(task_record_value "$file" choice) || return 1
    window=$(task_record_value "$file" window-tasks) || return 1
    permitted=$(task_record_value "$file" permitted-tasks) || return 1
    at=$(task_record_value "$file" at) || return 1
    echo "- after task $boundary: $choice; policy window $window; permitted tasks $permitted; $at"
  done <<EOF
$TASK_HISTORY_FILES
EOF
}
