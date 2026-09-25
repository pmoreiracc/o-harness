#!/usr/bin/env bash
# Shared review-readiness and review-series telemetry contract.
#
# A readiness manifest is written by the implementer and therefore proves nothing. Its value
# is inspectability: it records the coverage claims presented to invariant-reviewer before a
# round starts. The harness binds those claims to the exact task/tree and captures the review
# input, but no function here can mint review authority, grant a round, or satisfy complete.sh.
# Compatible with bash 3.2.

REVIEW_REQUEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$REVIEW_REQUEST_DIR/round-ledger.sh" || return 1 2>/dev/null || exit 1

REVIEW_REQUEST_HEADINGS='Requirements covered|Rules checked|Affected surfaces|Claims and proof|Adversarial self-review|Defect-family closure|Prior finding dispositions|Verification|Limits'

review_request_root() {
  if [ -n "${OH_STATE_ROOT:-}" ]; then printf '%s/requests' "$OH_STATE_ROOT";
  else printf '%s/.deliver/review-requests' "$1"; fi
}

review_request_key() {
  printf '%s-t%s' "$1" "$2"
}

review_finalize_key() {
  printf '%s-finalize' "$1"
}

# review_request_context <root> <branch> — print request-key<TAB>doc<TAB>task-or-finalize for
# every /deliver review phase. A task key comes from the same runnable-task derivation as the
# completion gate. With no task in flight, only next.sh's explicit Finalize/Recover states
# become a finalization key; unrelated and malformed delivery-branch states fail closed here.
review_request_context() {
  local root="$1" branch="$2" key doc status head trunk dirt
  # Refuse the absorbed-branch failure family before a readiness request can spend a review
  # round. At the fresh trunk SHA, dirty first-task work is reviewable only on the canonical
  # creation incarnation. start.sh is the supported writer of that fact; reset/reused refs
  # fail here as well as at next.sh and complete.sh.
  case "$branch" in
    deliver/*)
      head=$(git -C "$root" rev-parse HEAD 2>/dev/null) || return 1
      trunk=$(git -C "$root" rev-parse origin/main 2>/dev/null) || return 1
      if [ "$head" = "$trunk" ]; then
        dirt=$(git -C "$root" status --porcelain 2>/dev/null) || return 1
        if [ -n "$dirt" ]; then
          task_fresh_branch_resume_valid "$root" "$branch" || return 1
        fi
      fi
      ;;
  esac
  key=$(round_current_key "$root" "$branch" 2>/dev/null)
  status=$?
  case "$status" in
    0)
      doc="${key%-t*}"
      printf '%s\t%s\t%s' "$key" "$doc" "${key#*-t}"
      return 0 ;;
    1) ;;
    *) return 1 ;;
  esac
  key=$(round_finalization_key "$root" "$branch") || return 1
  doc="${key%-finalize}"
  printf '%s\t%s\tfinalize' "$key" "$doc"
}

review_request_dir() {
  printf '%s/%s/%s' "$(review_request_root "$1")" "$2" "$3"
}

review_request_path() {
  printf '%s/request.md' "$(review_request_dir "$1" "$2" "$3")"
}

review_request_pending_dir() {
  local used
  used=$(round_count "$1" "$2") || return 1
  # A completed attempt changes the required prior-finding dispositions even when the
  # code tree is unchanged. Keep each start's input immutable, but let the next round
  # retain its own current request. The allocator still owns admission and the ceiling.
  printf '%s/pending-inputs/%s/%s/after-%s' "$(review_series_state_root "$1")" "$2" "$3" "$used"
}

review_request_header() {
  awk -v key="$2" '
    /^---[[:space:]]*$/ { exit }
    index($0, key ": ") == 1 { count++; value=substr($0, length(key) + 3) }
    END { if (count != 1) exit 1; print value }
  ' "$1"
}

# review_manifest_check <file> — structural only. The implementer owns these claims; the
# reviewer judges their truth. Exact headings keep the request short and queryable while the
# body remains ordinary Markdown rather than a brittle model-generated serialization.
review_manifest_check() {
  local file="$1" root="${2:-}" key="${3:-}" reason expected actual prior_rounds
  [ -f "$file" ] && [ ! -L "$file" ] || {
    printf 'the readiness manifest is not a regular file\n'; return 1;
  }
  reason=$(awk -v expected="$REVIEW_REQUEST_HEADINGS" '
    BEGIN { n=split(expected, names, "[|]"); section=0 }
    /^## / {
      title=substr($0, 4)
      section++
      if (section > n || title != names[section]) bad="expected section " section " to be ## " names[section]
      next
    }
    section > 0 && /^- [^[:space:]]/ {
      entries[section]++
      if (section == 7 && $0 != "- none — first review" && $0 != "- none — no prior findings" && $0 != "- none — prior reviews clean" && $0 !~ /^- [^#[:space:]]+#[0-9]+ \| (fixed|routed|accepted|dismissed|still-open|disputed) \| [^[:space:]].*/) {
        bad="Prior finding dispositions must be a canonical none sentinel or <attempt-id>#<finding> | fixed/routed/accepted/dismissed/still-open/disputed | outcome"
      }
    }
    END {
      if (bad != "") print bad
      else if (section != n) print "expected " n " readiness sections, found " section
      else for (i=1; i<=n; i++) if (entries[i] < 1) { print "section ## " names[i] " needs at least one concrete list entry"; exit }
    }
  ' "$file")
  if [ -n "$reason" ]; then printf '%s\n' "$reason"; return 1; fi

  # Once an attempt has findings, the next request must account for every one exactly once.
  # The expected set comes from retained attempts and validated historical archives.
  if [ -n "$root" ] && [ -n "$key" ]; then
    expected=$(review_request_expected_dispositions "$root" "$key") || return 1
    prior_rounds=$(review_request_receipts "$root" "$key" | grep -c .)
    actual=$(awk '/^## Prior finding dispositions$/{insection=1;next} /^## /{insection=0} insection && /^- /{sub(/^- /, ""); split($0,p," [|] "); if (p[1] !~ /^none — /) print p[1]}' "$file" | LC_ALL=C sort)
    if [ "$prior_rounds" -eq 0 ]; then
      grep -qF -- '- none — first review' "$file" || {
        printf 'the first review must declare "- none — first review"\n'; return 1;
      }
      grep -qE -- '^- none — (no prior findings|prior reviews clean)$' "$file" && {
        printf 'the first review cannot claim prior attempts\n'; return 1;
      }
      [ -z "$actual" ] || { printf 'the first review cannot disposition unknown findings\n'; return 1; }
    elif [ -z "$expected" ]; then
      grep -qE -- '^- none — (no prior findings|prior reviews clean)$' "$file" || {
        printf 'a later review with no prior findings must declare "- none — no prior findings"\n'; return 1;
      }
      grep -qF -- '- none — first review' "$file" && {
        printf 'a later review cannot declare itself the first review\n'; return 1;
      }
      [ -z "$actual" ] || { printf 'a clean prior series has no findings to disposition\n'; return 1; }
    else
      grep -qE -- '^- none — (first review|no prior findings|prior reviews clean)$' "$file" && {
        printf 'a later review with prior findings cannot use a none sentinel\n'; return 1;
      }
      [ "$actual" = "$expected" ] || {
        printf 'Prior finding dispositions must account for every prior finding exactly once\n'; return 1;
      }
    fi
  fi
  return 0
}

review_request_validate_path() {
  local root="$1" key="$2" digest="$3" path="$4" version doc task tree head body
  [ -f "$path" ] && [ ! -L "$path" ] || return 1
  version=$(review_request_header "$path" request-version) || return 1
  doc=$(review_request_header "$path" doc) || return 1
  task=$(review_request_header "$path" task) || return 1
  tree=$(review_request_header "$path" tree) || return 1
  head=$(review_request_header "$path" head) || return 1
  [ "$version" = 1 ] || return 1
  if [ "$task" = finalize ]; then
    [ "$(review_finalize_key "$doc")" = "$key" ] || return 1
  else
    [ "$(review_request_key "$doc" "$task")" = "$key" ] || return 1
  fi
  [ "$tree" = "$digest" ] || return 1
  [ "$head" = "$(git -C "$root" rev-parse HEAD 2>/dev/null)" ] || return 1
  body=$(mktemp "${TMPDIR:-/tmp}/review-manifest.XXXXXX") || return 1
  sed '1,/^---[[:space:]]*$/d' "$path" > "$body" || { rm -f "$body"; return 1; }
  review_manifest_check "$body" "$root" "$key" >/dev/null
  local result=$?
  rm -f "$body"
  return "$result"
}

review_request_validate() {
  review_request_validate_path "$1" "$2" "$3" "$(review_request_path "$1" "$2" "$3")"
}

# _review_same_but_line <a> <b> <lineno> — byte-identical except one exempt line.
#
# Both retained inputs carry a wall-clock stamp their writer rewrites on every call:
# `review_tree_capture` restamps snapshot line 4, and `review-ready.sh stage` restamps
# request line 6. Comparing whole files therefore made a same-tree re-review impossible —
# a re-stage or re-capture after an interrupted or refused round that left the pending
# input in place saw a mismatch, fell through to publication's "already published" refusal,
# and every reviewer spawn after the first died in the readiness gate. Every other byte
# still has to match exactly — a mutated retained input is still a mismatch.
_review_same_but_line() {
  local a="$1" b="$2" skip="$3"
  [ -f "$a" ] && [ ! -L "$a" ] && [ -f "$b" ] && [ ! -L "$b" ] || return 1
  awk -v skip="$skip" '
    NR == FNR { if (FNR != skip) kept[++n] = $0; next }
    FNR != skip { m++; if (m > n || kept[m] != $0) { bad = 1; exit } }
    END { exit (bad || m != n) ? 1 : 0 }
  ' "$a" "$b"
}

# Same captured tree, ignoring the snapshot's wall-clock `at:` line.
review_snapshot_same() { _review_same_but_line "$1" "$2" 4; }

# Same staged request, ignoring the request header's wall-clock `at:` line (line 6, written
# by review-ready.sh in fixed order: request-version, doc, task, tree, head, at, authority).
review_request_same() { _review_same_but_line "$1" "$2" 6; }

review_request_publish_pending() {
  local root="$1" key="$2" digest="$3" branch="$4" live out parent tmp
  live=$(review_request_dir "$root" "$key" "$digest")
  out=$(review_request_pending_dir "$root" "$key" "$digest") || return 1
  parent="${out%/*}"
  tmp="$parent/.pending-$digest.$$"
  review_request_validate "$root" "$key" "$digest" || return 1
  [ -f "$live/snapshot.txt" ] && [ ! -L "$live/snapshot.txt" ] || return 1
  if [ -d "$out" ] && [ ! -L "$out" ] \
     && review_request_same "$live/request.md" "$out/request.md" \
     && review_snapshot_same "$live/snapshot.txt" "$out/snapshot.txt" \
     && [ "$(cat "$out/branch" 2>/dev/null)" = "$branch" ]; then
    return 0
  fi
  [ ! -e "$out" ] || return 1
  mkdir -p "$tmp" || return 1
  cp "$live/request.md" "$tmp/request.md" \
    && cp "$live/snapshot.txt" "$tmp/snapshot.txt" \
    && printf '%s\n' "$branch" > "$tmp/branch" \
    || { rm -rf "$tmp"; return 1; }
  mv "$tmp" "$out"
}

# review_request_current <root> — print key<TAB>digest<TAB>path for a delivery task with a
# valid request for the exact current tree. Non-delivery review has no readiness requirement.
review_request_current() {
  local root="$1" branch context key digest path
  branch=$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null) || return 1
  context=$(review_request_context "$root" "$branch") || return 1
  key="${context%%$'\t'*}"
  digest=$(CLAUDE_PROJECT_DIR="$root" "${OH_HOME:-$root}/core/scripts/tree-digest.sh" 2>/dev/null) || return 1
  path=$(review_request_path "$root" "$key" "$digest")
  review_request_validate "$root" "$key" "$digest" || return 1
  printf '%s\t%s\t%s' "$key" "$digest" "$path"
}

# review_tree_capture <root> <digest> <output> — retained telemetry for the exact input tree.
# It is evidence for later inspection, never a restore source; the human PR gate is authority.
review_tree_capture() {
  local root="$1" digest="$2" out="$3" dir tmp tracked entries paths f path_id path_hex
  local object_id mode target_hex current_digest head count
  current_digest=$(CLAUDE_PROJECT_DIR="$root" "${OH_HOME:-$root}/core/scripts/tree-digest.sh") || return 1
  [ "$current_digest" = "$digest" ] || return 1
  dir="${out%/*}"
  mkdir -p "$dir" || return 1
  tmp="$dir/.snapshot.$$"
  tracked="$dir/.tracked-diff.$$"
  entries="$dir/.untracked-entries.$$"
  paths="$dir/.untracked-paths.$$"
  git -C "$root" diff --binary --no-ext-diff HEAD > "$tracked" \
    || { rm -f "$tracked" "$entries" "$paths"; return 1; }
  git -C "$root" ls-files -z --others --exclude-standard -- . ':(exclude).deliver/**' > "$paths" \
    || { rm -f "$tracked" "$entries" "$paths"; return 1; }
  : > "$entries" || { rm -f "$tracked" "$entries" "$paths"; return 1; }
  while IFS= read -r -d '' f; do
    if [ -d "$root/$f" ] && [ -d "$root/${f%/}/.git" ]; then f=${f%/}; fi
    path_id=$(printf '%s' "$f" | git -C "$root" hash-object --stdin) || {
      rm -f "$tracked" "$entries" "$paths"; return 1; }
    path_hex=$(printf '%s' "$f" | od -An -v -tx1 | tr -d ' \n') || {
      rm -f "$tracked" "$entries" "$paths"; return 1; }
    if [ -L "$root/$f" ]; then
      object_id=$(perl -e 'defined($t=readlink $ARGV[0]) or exit 1; print $t' "$root/$f" \
        | git -C "$root" hash-object --stdin) || { rm -f "$tracked" "$entries" "$paths"; return 1; }
      target_hex=$(perl -e 'defined($t=readlink $ARGV[0]) or exit 1; print $t' "$root/$f" \
        | od -An -v -tx1 | tr -d ' \n') || { rm -f "$tracked" "$entries" "$paths"; return 1; }
      [ -n "$target_hex" ] || target_hex=-
      printf 'untracked: %s\t%s\tsymlink\t120000\t%s\t%s\n' \
        "$path_hex" "$path_id" "$object_id" "$target_hex" >> "$entries" || {
          rm -f "$tracked" "$entries" "$paths"; return 1; }
    elif [ -f "$root/$f" ]; then
      object_id=$(git -C "$root" hash-object --no-filters -- "$f") || {
        rm -f "$tracked" "$entries" "$paths"; return 1; }
      if [ -x "$root/$f" ]; then mode=100755; else mode=100644; fi
      printf 'untracked: %s\t%s\tregular\t%s\t%s\t' \
        "$path_hex" "$path_id" "$mode" "$object_id" >> "$entries" || {
          rm -f "$tracked" "$entries" "$paths"; return 1; }
      if [ -s "$root/$f" ]; then
        od -An -v -tx1 "$root/$f" | tr -d ' \n' >> "$entries" || {
          rm -f "$tracked" "$entries" "$paths"; return 1; }
      else
        printf '%s' - >> "$entries" || { rm -f "$tracked" "$entries" "$paths"; return 1; }
      fi
      printf '\n' >> "$entries" || { rm -f "$tracked" "$entries" "$paths"; return 1; }
    elif [ -d "$root/$f" ] && object_id=$(git -C "$root/$f" rev-parse --verify HEAD 2>/dev/null); then
      printf 'untracked: %s\t%s\tgitlink\t160000\t%s\t-\n' \
        "$path_hex" "$path_id" "$object_id" >> "$entries" || {
          rm -f "$tracked" "$entries" "$paths"; return 1; }
    else
      echo "review-request: unsupported untracked filesystem object: $f" >&2
      rm -f "$tracked" "$entries" "$paths"
      return 1
    fi
  done < "$paths"
  count=$(wc -l < "$entries" 2>/dev/null | tr -d '[:space:]') || {
    rm -f "$tracked" "$entries" "$paths"; return 1; }
  head=$(git -C "$root" rev-parse HEAD 2>/dev/null) || {
    rm -f "$tracked" "$entries" "$paths"; return 1; }
  {
    printf 'snapshot-version: 2\n'
    printf 'tree: %s\n' "$digest"
    printf 'head: %s\n' "$head"
    printf 'at: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '%s\n' '---'
    printf 'tracked-diff-hex: '
    od -An -v -tx1 "$tracked" | tr -d ' \n' || exit 1
    printf '\nuntracked-count: %s\n' "$count"
    cat "$entries" || exit 1
  } > "$tmp" || { rm -f "$tmp" "$tracked" "$entries" "$paths"; return 1; }
  rm -f "$tracked" "$entries" "$paths" || { rm -f "$tmp"; return 1; }
  accepted_snapshot_validate "$tmp" "$digest" "$head" || { rm -f "$tmp"; return 1; }
  mv -f "$tmp" "$out"
}

# Delivery readiness owns the staging path; all reviewer starts later retain this same shape.
review_request_capture() {
  local root="$1" key="$2" digest="$3" dir
  review_request_validate "$root" "$key" "$digest" || return 1
  dir=$(review_request_dir "$root" "$key" "$digest")
  review_tree_capture "$root" "$digest" "$dir/snapshot.txt"
}

review_request_receipts() {
  local root="$1" key="$2" archive round review rounds series attempts entry raw
  series=$(review_series_find_for_key "$root" "$key" 2>/dev/null) || series=""
  if [ -n "$series" ]; then
    attempts=$(review_attempts_dir "$root" "$series")
    if [ -e "$attempts" ] || [ -L "$attempts" ]; then
      [ -d "$attempts" ] && [ ! -L "$attempts" ] || return 1
      for entry in "$attempts"/*; do
        [ -e "$entry" ] || [ -L "$entry" ] || continue
        review_attempt_unadmitted_dir "$root" "$entry" && continue
        review_attempt_path_valid "$root" "$entry" || return 1
        review_attempt_validate_start "$root" "$entry" || return 1
        raw="$entry/raw.md"; [ -f "$raw" ] && [ ! -L "$raw" ] || raw="$entry/start.json"
        printf '%s\n' "${raw#"$root"/}"
      done
    fi
  fi
  archive="$(review_series_state_root "$root")/accepted/$key"
  rounds=$(accepted_rounds_list "$root" "$key") || return 1
  printf '%s\n' "$rounds" | while IFS= read -r round; do
    [ -n "$round" ] || continue
    review="$archive/$round/review.md"
    printf '%s\t%s\n' "$(review_request_header "$review" at 2>/dev/null)" "${review#"$root/"}"
  done | cut -f2-
}

review_request_expected_dispositions() {
  local root="$1" key="$2" archive review round_id rounds series attempts entry attempt_id
  type review_normalize >/dev/null 2>&1 || . "$REVIEW_REQUEST_DIR/review-receipt.sh" || return 1
  series=$(review_series_find_for_key "$root" "$key" 2>/dev/null) || series=""
  archive="$(review_series_state_root "$root")/accepted/$key"
  rounds=$(accepted_rounds_list "$root" "$key") || return 1
  {
    if [ -n "$series" ]; then
      attempts=$(review_attempts_dir "$root" "$series")
      if [ -e "$attempts" ] || [ -L "$attempts" ]; then
        [ -d "$attempts" ] && [ ! -L "$attempts" ] || return 1
        for entry in "$attempts"/*; do
          [ -e "$entry" ] || [ -L "$entry" ] || continue
          review_attempt_unadmitted_dir "$root" "$entry" && continue
          review_attempt_path_valid "$root" "$entry" || return 1
          review_attempt_validate_start "$root" "$entry" || return 1
          [ -f "$entry/completion.json" ] && [ ! -L "$entry/completion.json" ] || continue
          attempt_id=$(jq -er '.id' "$entry/start.json") || return 1
          jq -r --arg id "$attempt_id" '.findings | to_entries[] | "\($id)#\(.key + 1)"' \
            "$entry/completion.json" || return 1
        done
      fi
    fi
    printf '%s\n' "$rounds" | while IFS= read -r round_id; do
      [ -n "$round_id" ] || continue
      review="$archive/$round_id/review.md"
      review_normalize "$review" | awk -v round_id="$round_id" '/^\[(BLOCKING|CONCERN|SCOPE)\] / { n++; print round_id "#" n }'
    done
  } | LC_ALL=C sort
}
