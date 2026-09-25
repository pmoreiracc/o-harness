#!/usr/bin/env bash
# Semantic review outcomes, local policy, and explicit review-series state (ADR-0051).
# Sourced by both host adapters. Compatible with macOS Bash 3.2.

REVIEW_WORKFLOW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

review_workflow_hash() {
  if command -v shasum >/dev/null 2>&1; then
    printf '%s' "$1" | shasum -a 256 | awk '{print $1}'
  else
    printf '%s' "$1" | sha256sum | awk '{print $1}'
  fi
}

review_workflow_file_hash() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else sha256sum "$1" | awk '{print $1}'
  fi
}

review_workflow_nonce() {
  LC_ALL=C od -An -N12 -tx1 /dev/urandom 2>/dev/null | tr -d '[:space:]'
}

review_decimal_gt_small() {
  local value="$1" small="$2"
  while [ "${value#0}" != "$value" ]; do value="${value#0}"; done
  [ -n "$value" ] || value=0
  [ "${#value}" -gt "${#small}" ] && return 0
  [ "${#value}" -lt "${#small}" ] && return 1
  [[ "$value" > "$small" ]]
}

review_integer_literal_valid() {
  local literal="$1" integer fraction sign exponent digits scale remaining
  [[ "$literal" =~ ^([0-9]+)(\.([0-9]+))?([eE]([+-]?)([0-9]+))?$ ]] || return 1
  integer="${BASH_REMATCH[1]}"; fraction="${BASH_REMATCH[3]}"
  sign="${BASH_REMATCH[5]}"; exponent="${BASH_REMATCH[6]}"
  [ -n "$exponent" ] || exponent=0
  while [ "${exponent#0}" != "$exponent" ]; do exponent="${exponent#0}"; done
  [ -n "$exponent" ] || exponent=0
  digits="$integer$fraction"
  if [ "$sign" = - ]; then
    review_decimal_gt_small "$exponent" "${#digits}" && return 1
    scale=$(( ${#fraction} + exponent ))
  else
    if review_decimal_gt_small "$exponent" "${#fraction}"; then return 0; fi
    scale=$(( ${#fraction} - exponent ))
  fi
  [ "$scale" -eq 0 ] && return 0
  [ "$scale" -le "${#digits}" ] || return 1
  remaining="${digits:$((${#digits} - scale))}"
  case "$remaining" in *[!0]*) return 1 ;; *) return 0 ;; esac
}

review_policy_parse() {
  local payload compact first second continuation rounds
  command -v jq >/dev/null 2>&1 || return 1
  payload=$(cat)
  printf '%s' "$payload" | jq -e '
    type == "object" and (keys | sort) == ["continuation_window_tasks", "review_window_rounds"] and
    (.continuation_window_tasks | type == "number" and floor == . and . > 0) and
    (.review_window_rounds | type == "number" and floor == . and . > 0)
  ' >/dev/null 2>&1 || return 1
  compact="${payload//[[:space:]]/}"
  case "$compact" in
    '{"continuation_window_tasks":'*',"review_window_rounds":'*'}')
      first="${compact#*\"continuation_window_tasks\":}"; continuation="${first%%,\"review_window_rounds\":*}"
      rounds="${compact##*,\"review_window_rounds\":}"; rounds="${rounds%?}" ;;
    '{"review_window_rounds":'*',"continuation_window_tasks":'*'}')
      first="${compact#*\"review_window_rounds\":}"; rounds="${first%%,\"continuation_window_tasks\":*}"
      continuation="${compact##*,\"continuation_window_tasks\":}"; continuation="${continuation%?}" ;;
    *) return 1 ;;
  esac
  review_integer_literal_valid "$continuation" && review_integer_literal_valid "$rounds" || return 1
  printf '%s\t%s' "$continuation" "$rounds"
}

# Sets REVIEW_POLICY_CONTINUATION, REVIEW_POLICY_ROUNDS, REVIEW_POLICY_SOURCE and
# REVIEW_POLICY_FILE. A present invalid local file always fails closed.
review_policy_load() {
  local root="$1" file values
  REVIEW_POLICY_SOURCE=default
  if [ -n "${OH_HOME:-}" ]; then
    [ -n "${OH_POLICY_FILE:-}" ] && [ -f "$OH_POLICY_FILE" ] && [ ! -L "$OH_POLICY_FILE" ] || return 1
    values=$(review_policy_parse < "$OH_POLICY_FILE") || return 1
    IFS=$'\t' read -r REVIEW_POLICY_CONTINUATION REVIEW_POLICY_ROUNDS <<EOF
$values
EOF
    REVIEW_POLICY_FILE="$OH_POLICY_FILE"
    REVIEW_POLICY_SOURCE=local
    export REVIEW_POLICY_CONTINUATION REVIEW_POLICY_ROUNDS REVIEW_POLICY_SOURCE REVIEW_POLICY_FILE
    return 0
  fi
  file="${OH_HOME:-$root}/core/delivery-policy.json"
  if [ -e "${OH_HOME:-$root}/core/delivery-policy.local.json" ] || [ -L "${OH_HOME:-$root}/core/delivery-policy.local.json" ]; then
    [ -f "${OH_HOME:-$root}/core/delivery-policy.local.json" ] \
      && [ ! -L "${OH_HOME:-$root}/core/delivery-policy.local.json" ] || return 1
    REVIEW_POLICY_SOURCE=local
    file="${OH_HOME:-$root}/core/delivery-policy.local.json"
  fi
  [ -f "$file" ] && [ ! -L "$file" ] || return 1
  values=$(review_policy_parse < "$file") || return 1
  IFS=$'\t' read -r REVIEW_POLICY_CONTINUATION REVIEW_POLICY_ROUNDS <<EOF
$values
EOF
  case "$REVIEW_POLICY_CONTINUATION:$REVIEW_POLICY_ROUNDS" in
    *[!0-9:]*|:*|*:) return 1 ;;
  esac
  REVIEW_POLICY_FILE="$file"
  export REVIEW_POLICY_CONTINUATION REVIEW_POLICY_ROUNDS REVIEW_POLICY_SOURCE REVIEW_POLICY_FILE
}

review_policy_status() {
  review_policy_load "$1" || return 1
  printf 'continuation-window-tasks: %s\nreview-window-rounds: %s\npolicy-source: %s\n' \
    "$REVIEW_POLICY_CONTINUATION" "$REVIEW_POLICY_ROUNDS" "$REVIEW_POLICY_SOURCE"
}

# Produce the semantic result from recognizable severity headers. Presentation never rejects
# an attempt: declared counts, section order, duplicate headings and field shape are telemetry.
review_semantic_json() {
  local file="$1" rows meta blocking concern scope clean evidence verdicts nonempty outcome anomalous
  [ -f "$file" ] && [ ! -L "$file" ] || return 1
  rows=$(awk '
    function trim(s) { sub(/^[[:space:]]+/, "", s); sub(/[[:space:]]+$/, "", s); return s }
    function undecorate(s, old, upper, pos, tail, word, i) {
      s=trim(s)
      old=""
      while (s != old) {
        old=s
        sub(/^>[[:space:]]*/, "", s)
        sub(/^#+[[:space:]]+/, "", s)
        sub(/^[-+*][[:space:]]+/, "", s)
        sub(/^[0-9]+[.)][[:space:]]+/, "", s)
        gsub(/^[*_`]+/, "", s); gsub(/[*_`]+$/, "", s); s=trim(s)
        # Emphasis often wraps only the marker (`**[BLOCKING]** claim`) instead of the
        # complete line. Strip the matching presentation run immediately after a recognized
        # marker too; otherwise a visible blocker could be parsed as clean.
        upper=toupper(s)
        if (upper ~ /^\[(BLOCKING|CONCERN|SCOPE)\]/) {
          pos=index(s,"]"); tail=substr(s,pos+1); sub(/^[*_`]+/, "", tail)
          s=substr(s,1,pos) tail
        } else {
          for (i=1; i<=3; i++) {
            word=(i==1 ? "BLOCKING" : (i==2 ? "CONCERN" : "SCOPE"))
            if (substr(upper,1,length(word)) == word) {
              tail=substr(s,length(word)+1); sub(/^[*_`]+/, "", tail)
              s=substr(s,1,length(word)) tail
              break
            }
          }
        }
      }
      return s
    }
    {
      raw=$0; top=trim(raw); was_fenced=fenced
      fence_line=(top ~ /^```/ || top ~ /^~~~/)
      if (fence_line) fenced=!fenced
      s=undecorate(raw); upper=toupper(s)
      if (raw ~ /[^[:space:]]/) { nonempty++; last_nonempty=NR }
      if (upper == "EVIDENCE") evidence++
      if (upper ~ /^VERDICT[[:space:]]*:/) verdicts++
      # Clean is authority, so it must be the reviewer conclusion rather than quoted or
      # fenced example text. Keep harmless emphasis flexible, but do not undecorate Markdown
      # containers or inline-code fences into a verdict.
      clean_line=top
      if (raw !~ /^[[:space:]]/ && !was_fenced && !fence_line \
          && clean_line !~ /^(>|#+[[:space:]]|[-+*][[:space:]]|[0-9]+[.)][[:space:]]|`)/) {
        gsub(/^[*_]+/, "", clean_line); gsub(/[*_]+$/, "", clean_line); clean_line=trim(clean_line)
        clean_upper=toupper(clean_line)
        if (clean_upper ~ /^VERDICT[[:space:]]*:/) top_verdicts++
        if (clean_upper ~ /^VERDICT[[:space:]]*:[[:space:]]*CLEAN([[:space:]]*(—|:|-)[[:space:]]*.*|[[:space:]]*)$/) {
          clean_candidates++; clean_line_number=NR
        }
      }
      sev=""; claim=""
      if (upper ~ /^\[(BLOCKING|CONCERN|SCOPE)\]([[:space:]:-]|$)/) {
        pos=index(s,"]"); sev=toupper(substr(s,2,pos-2)); claim=trim(substr(s,pos+1)); sub(/^[: -]+/, "", claim)
      } else if (upper ~ /^(BLOCKING|CONCERN|SCOPE)[[:space:]]*:/) {
        split(upper, p, ":"); sev=trim(p[1]); claim=s; sub(/^[^:]+:[[:space:]]*/, "", claim)
      }
      if (sev != "") {
        if (claim == "") claim="(claim text missing; inspect retained raw output)"
        print sev "\t" NR "\t" claim
      }
    }
    END {
      clean=(clean_candidates==1 && clean_line_number==last_nonempty && top_verdicts==1)
      print "@META\t" nonempty+0 "\t" clean+0 "\t" evidence+0 "\t" verdicts+0
    }
  ' "$file") || return 1
  meta=$(printf '%s\n' "$rows" | awk -F '\t' '$1=="@META" {print; exit}')
  blocking=$(printf '%s\n' "$rows" | awk -F '\t' '$1=="BLOCKING" {n++} END{print n+0}')
  concern=$(printf '%s\n' "$rows" | awk -F '\t' '$1=="CONCERN" {n++} END{print n+0}')
  scope=$(printf '%s\n' "$rows" | awk -F '\t' '$1=="SCOPE" {n++} END{print n+0}')
  nonempty=$(printf '%s\n' "$meta" | cut -f2)
  clean=$(printf '%s\n' "$meta" | cut -f3)
  evidence=$(printf '%s\n' "$meta" | cut -f4)
  verdicts=$(printf '%s\n' "$meta" | cut -f5)
  if [ "$blocking" -gt 0 ]; then
    outcome=blocking
    [ "$concern" -gt 0 ] && outcome="$outcome+concern"
    [ "$scope" -gt 0 ] && outcome="$outcome+scope"
  elif [ "$concern" -gt 0 ]; then
    outcome=concern
    [ "$scope" -gt 0 ] && outcome="$outcome+scope"
  elif [ "$scope" -gt 0 ]; then
    outcome=scope
  elif [ "$clean" -gt 0 ] && [ "$nonempty" -gt 0 ]; then
    outcome=clean
  else
    outcome=ambiguous
  fi
  anomalous=false
  [ "$evidence" -eq 1 ] && [ "$verdicts" -eq 1 ] || anomalous=true
  [ "$clean" -eq 0 ] || [ $((blocking + concern + scope)) -eq 0 ] || anomalous=true
  printf '%s\n' "$rows" | awk -F '\t' '$1!="@META" {print}' \
    | jq -Rsc --arg outcome "$outcome" --argjson b "$blocking" --argjson c "$concern" \
      --argjson s "$scope" --argjson anomaly "$anomalous" '
        split("\n") | map(select(length > 0) | split("\t")
          | {severity:(.[0] | ascii_downcase), line:(.[1] | tonumber), claim:(.[2:] | join("\t"))})
        | {outcome:$outcome, counts:{blocking:$b, concern:$c, scope:$s},
           formatAnomalous:$anomaly, findings:.}
      '
}

review_required_transition() {
  case "$1" in
    clean) echo complete ;;
    blocking) echo fix-blockers-review ;;
    blocking+concern) echo fix-blockers-concerns-review ;;
    blocking+scope) echo fix-blockers-route-scope-review ;;
    blocking+concern+scope) echo fix-blockers-concerns-route-scope-review ;;
    concern) echo human-concern ;;
    scope) echo human-scope ;;
    concern+scope) echo human-concern-scope ;;
    ambiguous) echo human-ambiguous ;;
    *) return 1 ;;
  esac
}

# Public presentation; raw evidence remains linked, never replaced by this summary.
review_attempt_summary() {
  local attempt="$1"
  [ -f "$attempt/completion.json" ] && [ ! -L "$attempt/completion.json" ] || return 1
  jq -r '"Review: " + .outcome + ".",
    (.findings[] | "- " + .severity + ": " + .claim)' "$attempt/completion.json" || return 1
  printf 'Full findings and recovery context: %s/raw.md\n' "$attempt"
}

review_choice_parse() {
  local outcome="$1" answer="$2"
  case "$outcome:$answer" in
    'concern:fix concerns') echo fix-concerns ;;
    'concern:accept concerns') echo accept-concerns ;;
    'scope:route scope') echo route-scope ;;
    'scope:dismiss scope') echo dismiss-scope ;;
    'concern+scope:fix concerns and route scope') echo fix-concerns+route-scope ;;
    'concern+scope:fix concerns and dismiss scope') echo fix-concerns+dismiss-scope ;;
    'concern+scope:accept concerns and route scope') echo accept-concerns+route-scope ;;
    'concern+scope:accept concerns and dismiss scope') echo accept-concerns+dismiss-scope ;;
    'ambiguous:review again') echo review-again ;;
    'ambiguous:take over') echo take-over ;;
    *) return 1 ;;
  esac
}

review_choice_labels() {
  case "$1" in
    concern) printf 'Fix concerns\nAccept concerns\n' ;;
    scope) printf 'Route scope\nDismiss scope\n' ;;
    concern+scope) printf '%s\n' 'Fix concerns and route scope' 'Fix concerns and dismiss scope' \
      'Accept concerns and route scope' 'Accept concerns and dismiss scope' ;;
    ambiguous) printf 'Review again\nTake over\n' ;;
    *) return 1 ;;
  esac
}

review_choice_commands() {
  case "$1" in
    concern) printf 'fix concerns\naccept concerns\n' ;;
    scope) printf 'route scope\ndismiss scope\n' ;;
    concern+scope) printf '%s\n' 'fix concerns and route scope' 'fix concerns and dismiss scope' \
      'accept concerns and route scope' 'accept concerns and dismiss scope' ;;
    ambiguous) printf 'review again\ntake over\n' ;;
    *) return 1 ;;
  esac
}

# One presentation contract for every exact Codex human command. Authority remains in the
# host hooks; this function only ensures that what the human sees can be copied byte-for-byte.
codex_gate_present() {
  local family="${1:-}" detail="${2:-}"
  case "$family:$detail" in
    review:concern) echo 'Review concerns need a decision: fixing requires verification and review; accepting retains them for this tree.' ;;
    review:scope) echo 'Scope findings need a destination: route them for later work or explicitly dismiss them.' ;;
    review:concern+scope) echo 'Choose whether to fix or accept concerns and route or dismiss the scope findings.' ;;
    review:ambiguous) echo 'The review has no usable verdict. A fresh review consumes another allowed attempt; takeover hands the retained work to you.' ;;
    review-window:exceeded) echo 'Review ran beyond its allowance. Renewal cannot authorize past attempts; take over or request an unresolved PR handoff.' ;;
    review-window:*) echo 'The review allowance is spent. Renew it for another bounded window, take over the work, or request an unresolved PR handoff.' ;;
    task:*) echo 'The completed task is ready. Continue grants only the displayed next tasks; PR finishes for merge; stop pushes the completed branch without a PR.' ;;
    scope-destination:*) echo "Confirm the retained scope finding belongs in $detail, or stop routing and preserve the pending finding." ;;
    detached:*) echo "Resume retained detached review $detail in this session, or stop without changing its evidence." ;;
  esac
  printf 'Human gate. Send one exact unformatted plain-text line:\n'
  case "$family" in
    review) review_choice_commands "$detail" ;;
    review-window)
      [ -n "${ROUND_GRANT_COMMAND:-}" ] && [ -n "${ROUND_STOP_TAKE_OVER_COMMAND:-}" ] \
        && [ -n "${ROUND_STOP_ESCALATE_COMMAND:-}" ] || return 1
      [ "$detail" = exceeded ] || printf '%s\n' "$ROUND_GRANT_COMMAND"
      printf '%s\n' "$ROUND_STOP_TAKE_OVER_COMMAND" "$ROUND_STOP_ESCALATE_COMMAND"
      ;;
    task)
      [ -n "${TASK_CONTINUE_COMMAND:-}" ] && [ -n "${TASK_PR_COMMAND:-}" ] \
        && [ -n "${TASK_STOP_COMMAND:-}" ] || return 1
      printf '%s\n' "$TASK_CONTINUE_COMMAND" "$TASK_PR_COMMAND" "$TASK_STOP_COMMAND"
      ;;
    scope-destination)
      printf '%s' "$detail" | grep -Eq '^https://[^[:space:]]+/issues/[1-9][0-9]*$' || return 1
      printf 'route scope to %s\nstop scope routing\n' "$detail"
      ;;
    detached)
      printf '%s' "$detail" | grep -Eq '^d-[0-9]{10}-[0-9a-f]{24}$' || return 1
      printf 'resume detached review %s\nstop detached review\n' "$detail"
      ;;
    *) return 1 ;;
  esac
}

review_series_state_root() {
  if [ -n "${OH_STATE_ROOT:-}" ]; then printf '%s' "$OH_STATE_ROOT";
  else printf '%s/.deliver/reviews' "$1"; fi
}
review_series_dir() { printf '%s/series/%s' "$(review_series_state_root "$1")" "$2"; }

review_detached_context_record() {
  printf '%s/detached-contexts/%s.json' "$(review_series_state_root "$1")" "$2"
}

review_detached_context_validate() {
  local root="$1" id="$2" file common common_sha
  printf '%s' "$id" | grep -Eq '^d-[0-9]{10}-[0-9a-f]{24}$' || return 1
  file=$(review_detached_context_record "$root" "$id")
  [ -f "$file" ] && [ ! -L "$file" ] || return 1
  common=$(git -C "$root" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 1
  common_sha=$(review_workflow_hash "${OH_REPOSITORY_ID:-$common}") || return 1
  jq -e --arg id "$id" --arg repository "$common_sha" '
    .version == 1 and .id == $id and .repository == $repository and .status == "active"
  ' "$file" >/dev/null 2>&1
}

# Detached review identity is scoped to one live host session. A later host session must pass
# REVIEW_DETACHED_CONTEXT_ID explicitly, which prevents an unrelated detached checkout from
# silently resuming an open series.
review_detached_context_for_session() {
  local root="$1" session="$2" allow_create="${3:-0}" state session_sha binding id dir tmp nonce now
  local common common_sha series record
  [ -n "$session" ] || return 1
  if [ -n "${REVIEW_DETACHED_CONTEXT_ID:-}" ]; then
    review_detached_context_validate "$root" "$REVIEW_DETACHED_CONTEXT_ID" || return 1
    printf '%s' "$REVIEW_DETACHED_CONTEXT_ID"
    return
  fi
  state="$(review_series_state_root "$root")/detached-sessions"
  session_sha=$(review_workflow_hash "$session") || return 1
  binding="$state/$session_sha"
  if [ -e "$binding" ] || [ -L "$binding" ]; then
    [ -f "$binding" ] && [ ! -L "$binding" ] || return 1
    id=$(jq -er 'select(.version==1) | .contextId' "$binding" 2>/dev/null) || return 1
    review_detached_context_validate "$root" "$id" || return 1
    printf '%s' "$id"
    return
  fi
  [ "$allow_create" = 1 ] || return 1
  common=$(git -C "$root" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 1
  common_sha=$(review_workflow_hash "${OH_REPOSITORY_ID:-$common}") || return 1
  # An open detached series from another host context may only be resumed by its explicit ID.
  for series in "$(review_series_state_root "$root")/series"/s-*; do
    [ -f "$series/series.json" ] && [ ! -e "$series/closed.json" ] || continue
    [ "$(jq -r '.branch' "$series/series.json" 2>/dev/null)" = HEAD ] || continue
    id=$(jq -r '.detachedContextId // empty' "$series/series.json" 2>/dev/null) || return 1
    [ -n "$id" ] || return 1
    record=$(review_detached_context_record "$root" "$id")
    [ -f "$record" ] && [ "$(jq -r '.repository' "$record" 2>/dev/null)" = "$common_sha" ] || continue
    if [ -n "${CODEX_HOOK:-}" ]; then
      echo "A detached review context is already open." >&2
      codex_gate_present detached "$id" >&2 || return 1
    else
      echo "Detached review $id is already open. No reviewer started; existing work is retained." >&2
      echo "Present one single-select question: Resume detached review $id / Stop detached review." >&2
    fi
    return 2
  done
  dir="$(review_series_state_root "$root")/detached-contexts"
  mkdir -p "$dir" "$state" || return 1
  nonce=$(review_workflow_nonce); [ "${#nonce}" = 24 ] || return 1
  now=$(date +%s); id="d-$now-$nonce"
  tmp="$dir/.context.$$.$nonce"
  jq -cn --arg id "$id" --arg repository "$common_sha" --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{version:1,id:$id,repository:$repository,status:"active",createdAt:$at}' > "$tmp" \
    && ln "$tmp" "$(review_detached_context_record "$root" "$id")" 2>/dev/null \
    || { rm -f "$tmp"; return 1; }
  rm -f "$tmp"
  tmp="$state/.session.$$.$nonce"
  jq -cn --arg id "$id" --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{version:1,contextId:$id,source:"first-detached-start",recordedAt:$at}' > "$tmp" \
    && ln "$tmp" "$binding" 2>/dev/null \
    || { rm -f "$tmp"; return 1; }
  rm -f "$tmp"
  printf '%s' "$id"
}

review_detached_context_bind_session() {
  local root="$1" session="$2" id="$3" source="$4" state session_sha binding tmp series found=0
  [ -n "$session" ] && [ -n "$source" ] || return 1
  review_detached_context_validate "$root" "$id" || return 1
  for series in "$(review_series_state_root "$root")/series"/s-*; do
    [ -f "$series/series.json" ] && [ ! -e "$series/closed.json" ] || continue
    [ "$(jq -r '.branch' "$series/series.json" 2>/dev/null)" = HEAD ] || continue
    [ "$(jq -r '.detachedContextId // empty' "$series/series.json" 2>/dev/null)" = "$id" ] || continue
    found=$((found + 1))
  done
  [ "$found" = 1 ] || return 1
  state="$(review_series_state_root "$root")/detached-sessions"
  mkdir -p "$state" || return 1
  session_sha=$(review_workflow_hash "$session") || return 1
  binding="$state/$session_sha"
  if [ -e "$binding" ] || [ -L "$binding" ]; then
    [ -f "$binding" ] && [ ! -L "$binding" ] \
      && [ "$(jq -r '.contextId' "$binding" 2>/dev/null)" = "$id" ] || return 1
    return 0
  fi
  tmp="$state/.session.$$"
  jq -cn --arg id "$id" --arg source "$source" --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{version:1,contextId:$id,source:$source,recordedAt:$at}' > "$tmp" \
    && ln "$tmp" "$binding" 2>/dev/null || { rm -f "$tmp"; return 1; }
  rm -f "$tmp"
}

review_detached_context_activate_for_session() {
  local root="$1" branch="$2" session="$3" allow_create="${4:-0}" id
  [ "$branch" = HEAD ] || return 0
  id=$(review_detached_context_for_session "$root" "$session" "$allow_create") || return $?
  REVIEW_DETACHED_CONTEXT_ID="$id"
  export REVIEW_DETACHED_CONTEXT_ID
}

review_branch_incarnation_legacy() {
  local root="$1" branch="$2" common first
  [ "$branch" != HEAD ] || {
    [ -n "${REVIEW_DETACHED_CONTEXT_ID:-}" ] || return 1
    review_detached_context_validate "$root" "$REVIEW_DETACHED_CONTEXT_ID" || return 1
    printf 'detached:%s' "$REVIEW_DETACHED_CONTEXT_ID"
    return
  }
  git -C "$root" check-ref-format --branch "$branch" >/dev/null 2>&1 || return 1
  common=$(git -C "$root" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 1
  first=$(git -C "$root" reflog show --format='%H%x09%gs' "refs/heads/$branch" 2>/dev/null | tail -n 1)
  [ -n "$first" ] || first=$(git -C "$root" rev-parse "refs/heads/$branch" 2>/dev/null) || return 1
  review_workflow_hash "${OH_REPOSITORY_ID:-$common}|branch:$branch|created:$first"
}

review_branch_incarnation() {
  local root="$1" branch="$2" common log first identity
  [ "$branch" != HEAD ] || {
    [ -n "${REVIEW_DETACHED_CONTEXT_ID:-}" ] || return 1
    review_detached_context_validate "$root" "$REVIEW_DETACHED_CONTEXT_ID" || return 1
    printf 'detached:%s' "$REVIEW_DETACHED_CONTEXT_ID"
    return
  }
  git -C "$root" check-ref-format --branch "$branch" >/dev/null 2>&1 || return 1
  common=$(git -C "$root" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 1
  log=$(git -C "$root" rev-parse --path-format=absolute --git-path "logs/refs/heads/$branch" 2>/dev/null) || return 1
  [ -f "$log" ] && [ ! -L "$log" ] || return 1
  first=$(sed -n '1p' "$log")
  [ -n "$first" ] || return 1
  identity=$(review_stat_identity "$log") || return 1
  review_workflow_hash "${OH_REPOSITORY_ID:-$common}|branch:$branch|reflog:$identity|created:$first"
}

review_stat_identity() {
  local path="$1" value
  [ -f "$path" ] && [ ! -L "$path" ] || return 1
  if stat -f '%i:%FB' "$path" >/dev/null 2>&1; then
    value="bsd:$(stat -f '%i:%FB' "$path" 2>/dev/null)" || return 1
  elif stat -c '%i:%w' "$path" >/dev/null 2>&1; then
    value="gnu:$(stat -c '%i:%w' "$path" 2>/dev/null)" || return 1
  else
    return 1
  fi
  printf '%s' "$value" | grep -Eq '^(bsd|gnu):[0-9]+:.+$' || return 1
  case "$value" in *$'\n'*|*:-) return 1 ;; esac
  printf '%s' "$value"
}

review_series_context() {
  local root="$1" branch="$2" route="${3:-invariant-reviewer}" incarnation
  incarnation=$(review_branch_incarnation "$root" "$branch") || return 1
  review_workflow_hash "${OH_REPOSITORY_ID:-$(git -C "$root" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)}|$branch|$incarnation|$route"
}

review_series_context_legacy() {
  local root="$1" branch="$2" route="${3:-invariant-reviewer}" incarnation
  incarnation=$(review_branch_incarnation_legacy "$root" "$branch") || return 1
  review_workflow_hash "${OH_REPOSITORY_ID:-$(git -C "$root" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)}|$branch|$incarnation|$route"
}

review_series_incarnation_value() {
  local root="$1" series="$2" branch stored
  [ -f "$series/series.json" ] && [ ! -L "$series/series.json" ] || return 1
  branch=$(jq -er '.branch' "$series/series.json") || return 1
  stored=$(jq -r '.branchIncarnation // empty' "$series/series.json") || return 1
  if [ -n "$stored" ]; then printf '%s' "$stored"
  else review_branch_incarnation_legacy "$root" "$branch"
  fi
}

review_series_incarnation_matches() {
  local root="$1" series="$2" branch route stored current legacy
  [ -f "$series/series.json" ] && [ ! -L "$series/series.json" ] || return 1
  branch=$(jq -er '.branch' "$series/series.json") || return 1
  stored=$(jq -r '.branchIncarnation // empty' "$series/series.json") || return 1
  if [ -n "$stored" ]; then
    current=$(review_branch_incarnation "$root" "$branch") || return 1
    [ "$stored" = "$current" ]
    return
  fi
  route=$(jq -er '.route' "$series/series.json") || return 1
  legacy=$(review_series_context_legacy "$root" "$branch" "$route") || return 1
  [ "$(jq -r '.context' "$series/series.json")" = "$legacy" ]
}

review_series_current() {
  local root="$1" branch="$2" route="${3:-invariant-reviewer}" contexts context path id dir seen=""
  contexts=$(printf '%s\n%s\n' \
    "$(review_series_context "$root" "$branch" "$route" 2>/dev/null)" \
    "$(review_series_context_legacy "$root" "$branch" "$route" 2>/dev/null)" | awk 'NF && !seen[$0]++')
  [ -n "$contexts" ] || return 1
  while IFS= read -r context; do
    path="$(review_series_state_root "$root")/contexts/$context/current"
    [ -f "$path" ] && [ ! -L "$path" ] || continue
    id=$(cat "$path") || return 1
    printf '%s' "$id" | grep -Eq '^s-[0-9]{10}-[0-9a-f]{24}$' || {
      echo "review-series: corrupt current-series pointer: $path" >&2; return 1;
    }
    dir=$(review_series_dir "$root" "$id")
    [ -f "$dir/series.json" ] && [ ! -e "$dir/closed.json" ] || continue
    [ "$(jq -r '.context' "$dir/series.json")" = "$context" ] || {
      echo "review-series: invalid context binding: $dir/series.json" >&2; return 1;
    }
    [ -z "$seen" ] || {
      echo "review-series: ambiguous open series $seen and $id; preserve both records and resolve the current context." >&2; return 1;
    }
    seen="$id"
  done < <(printf '%s\n' "$contexts")
  [ -n "$seen" ] || return 1
  printf '%s' "$seen"
}

review_context_lock_guard() {
  exec 9>&-
  perl -MFcntl=:flock -e '
    use strict;
    my ($lock, $status, $fifo) = @ARGV;
    open(my $fh, ">>", $lock) or exit 1;
    my $state = flock($fh, LOCK_EX | LOCK_NB) ? "held" : "busy";
    open(my $sf, ">", $status) or exit 1;
    print {$sf} $state;
    close($sf) or exit 1;
    exit 2 if $state ne "held";
    open(my $pipe, "<", $fifo) or exit 1;
    1 while <$pipe>;
  ' "$1" "$2" "$3"
}

review_context_lock_candidate_cleanup() {
  local fifo="$1" status="$2" helper="$3"
  exec 9>&-
  wait "$helper" 2>/dev/null || true
  rm -f "$fifo" "$status"
}

review_context_lock_acquire() {
  local root="$1" context="$2" cdir nonce lock legacy fifo status helper state tries=0
  printf '%s' "$context" | grep -Eq '^[0-9a-f]{64}$' || return 1
  cdir="$(review_series_state_root "$root")/contexts/$context"
  mkdir -p "$cdir" || return 1
  [ -d "$cdir" ] && [ ! -L "$cdir" ] || return 1
  nonce=$(review_workflow_nonce); [ "${#nonce}" = 24 ] || return 1
  lock="$cdir/.context.flock"; legacy="$cdir/.context.lock"
  if [ -e "$legacy" ] || [ -L "$legacy" ]; then
    [ -f "$legacy" ] && [ ! -L "$legacy" ] || return 1
    rm -f "$legacy" || return 1
  fi
  [ ! -e "$lock" ] && [ ! -L "$lock" ] || { [ -f "$lock" ] && [ ! -L "$lock" ] || return 1; }
  fifo="$cdir/.context-fifo.$$.$nonce"; status="$cdir/.context-status.$$.$nonce"
  mkfifo "$fifo" || return 1
  exec 9<>"$fifo" || { rm -f "$fifo"; return 1; }
  review_context_lock_guard "$lock" "$status" "$fifo" &
  helper=$!
  while [ ! -f "$status" ] && [ "$tries" -lt 40 ]; do
    kill -0 "$helper" 2>/dev/null || break
    sleep 0.05
    tries=$((tries + 1))
  done
  [ -f "$status" ] && [ ! -L "$status" ] || {
    review_context_lock_candidate_cleanup "$fifo" "$status" "$helper"; return 1;
  }
  state=$(cat "$status" 2>/dev/null) || {
    review_context_lock_candidate_cleanup "$fifo" "$status" "$helper"; return 1;
  }
  if [ "$state" = held ]; then
    REVIEW_CONTEXT_LOCK_PATH="$lock"
    REVIEW_CONTEXT_LOCK_FIFO="$fifo"
    REVIEW_CONTEXT_LOCK_STATUS="$status"
    REVIEW_CONTEXT_LOCK_HELPER="$helper"
    return 0
  fi
  review_context_lock_candidate_cleanup "$fifo" "$status" "$helper"
  [ "$state" = busy ] && return 2
  return 1
}

review_context_lock_release() {
  [ -n "${REVIEW_CONTEXT_LOCK_HELPER:-}" ] && [ -n "${REVIEW_CONTEXT_LOCK_PATH:-}" ] || return 0
  exec 9>&-
  [ -z "${REVIEW_CONTEXT_LOCK_HELPER:-}" ] || wait "$REVIEW_CONTEXT_LOCK_HELPER" 2>/dev/null || true
  rm -f "${REVIEW_CONTEXT_LOCK_FIFO:-}" "${REVIEW_CONTEXT_LOCK_STATUS:-}"
  REVIEW_CONTEXT_LOCK_PATH=""; REVIEW_CONTEXT_LOCK_FIFO=""; REVIEW_CONTEXT_LOCK_STATUS=""
  REVIEW_CONTEXT_LOCK_HELPER=""
}

review_series_ensure() (
  local root="$1" branch="$2" window="$3" route="${4:-invariant-reviewer}"
  local round_key="${5:--}" context contexts pointer existing id dir tmp head now nonce existing_key policy_source
  local subject design_path design_status branch_incarnation
  case "$window" in ''|*[!0-9]*|0) return 1 ;; esac
  context=$(review_series_context "$root" "$branch" "$route") || return 1
  branch_incarnation=$(review_branch_incarnation "$root" "$branch") || return 1
  contexts="$(review_series_state_root "$root")/contexts/$context"
  mkdir -p "$contexts" "$(review_series_state_root "$root")/series" || return 1
  review_context_lock_acquire "$root" "$context" || return $?
  trap 'review_context_lock_release >/dev/null 2>&1 || true' EXIT
  existing=$(review_series_current "$root" "$branch" "$route" 2>/dev/null) && {
    existing_key=$(jq -r '.roundKey // "-"' "$(review_series_dir "$root" "$existing")/series.json") || return 1
    [ "$round_key" = - ] || [ "$existing_key" = "$round_key" ] || return 1
    review_series_subject_reconcile "$root" "$existing" "$existing_key" >/dev/null || return 1
    printf '%s' "$existing"; return 0;
  }
  pointer="$contexts/current"
  if [ -e "$pointer" ] || [ -L "$pointer" ]; then
    # Closing publishes the immutable marker before removing this pointer. A process that
    # dies between those operations must not wedge the context forever.
    [ -f "$pointer" ] && [ ! -L "$pointer" ] || return 1
    existing=$(cat "$pointer" 2>/dev/null) || return 1
    printf '%s' "$existing" | grep -Eq '^s-[0-9]{10}-[0-9a-f]{24}$' || return 1
    dir=$(review_series_dir "$root" "$existing")
    [ -f "$dir/series.json" ] && [ ! -L "$dir/series.json" ] \
      && [ -f "$dir/closed.json" ] && [ ! -L "$dir/closed.json" ] \
      && [ "$(jq -r '.context' "$dir/series.json" 2>/dev/null)" = "$context" ] \
      && [ "$(jq -r '.status' "$dir/closed.json" 2>/dev/null)" = closed ] || return 1
    rm -f "$pointer" || return 1
  fi
  nonce=$(review_workflow_nonce); [ "${#nonce}" = 24 ] || return 1
  policy_source="${REVIEW_POLICY_SOURCE:-default}"
  now=$(date +%s); id="s-$now-$nonce"; dir=$(review_series_dir "$root" "$id")
  case "$round_key" in nd/context-*) round_key="nd/$id" ;; esac
  IFS=$'\t' read -r subject design_path design_status <<EOF
$(review_subject_resolve "$root" "$round_key")
EOF
  case "$subject" in harness|product) ;; *) return 1 ;; esac
  [ -n "$design_path" ] || design_path=-
  [ -n "$design_status" ] || design_status=-
  mkdir "$dir" 2>/dev/null || return 1
  head=$(git -C "$root" rev-parse HEAD 2>/dev/null) || { rmdir "$dir"; return 1; }
  jq -cn --arg id "$id" --arg context "$context" --arg branch "$branch" --arg head "$head" \
    --arg route "$route" --arg roundKey "$round_key" --arg policySource "$policy_source" --argjson window "$window" --argjson epoch "$now" \
    --arg detached "${REVIEW_DETACHED_CONTEXT_ID:-}" --arg subject "$subject" --arg incarnation "$branch_incarnation" \
    --arg designPath "$design_path" --arg designStatus "$design_status" \
    --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{version:1,id:$id,context:$context,branch:$branch,startingHead:$head,route:$route,
      roundKey:$roundKey,reviewWindowRounds:$window,policySource:$policySource,
      subjectKind:$subject,subjectClassifierVersion:2,branchIncarnation:$incarnation,
      designPath:(if $designPath=="-" then null else $designPath end),
      designStatus:(if $designStatus=="-" then null else $designStatus end),
      detachedContextId:(if $detached=="" then null else $detached end),
      startedAt:$at,startedEpoch:$epoch,status:"open"}' > "$dir/.series.$$" \
    && mv "$dir/.series.$$" "$dir/series.json" || { rm -rf "$dir"; return 1; }
  tmp="$contexts/.current.$$"
  printf '%s\n' "$id" > "$tmp" && ln "$tmp" "$pointer" 2>/dev/null
  if [ $? -ne 0 ]; then
    rm -f "$tmp"; rm -rf "$dir"
    existing=$(review_series_current "$root" "$branch" "$route" 2>/dev/null) || return 1
    printf '%s' "$existing"; return 0
  fi
  rm -f "$tmp"
  printf '%s' "$id"
)

review_series_find_for_key() {
  local root="$1" key="$2" base dir found="" found_epoch=-1 value epoch
  case "$key" in
    nd/s-*)
      value="${key#nd/}"; dir=$(review_series_dir "$root" "$value")
      [ -f "$dir/series.json" ] || return 1
      printf '%s' "$value"; return ;;
  esac
  base="$(review_series_state_root "$root")/series"
  [ -d "$base" ] || return 1
  for dir in "$base"/s-*; do
    [ -f "$dir/series.json" ] && [ ! -L "$dir/series.json" ] || continue
    value=$(jq -r '.roundKey // "-"' "$dir/series.json" 2>/dev/null) || continue
    [ "$value" = "$key" ] || continue
    epoch=$(jq -r '.startedEpoch // 0' "$dir/series.json" 2>/dev/null) || continue
    if [ "$epoch" -ge "$found_epoch" ]; then found="${dir##*/}"; found_epoch="$epoch"; fi
  done
  [ -n "$found" ] || return 1
  printf '%s' "$found"
}

review_series_window() {
  local file
  file="$(review_series_dir "$1" "$2")/series.json"
  [ -f "$file" ] && [ ! -L "$file" ] || return 1
  jq -er '.reviewWindowRounds | select(type=="number" and floor==. and .>0)' "$file"
}

review_series_close() (
  local root="$1" id="$2" reason="$3" dir context pointer tmp existing_reason
  case "$reason" in clean|resolved|take-over|escalated|abandoned) ;; *) return 1 ;; esac
  dir=$(review_series_dir "$root" "$id")
  [ -f "$dir/series.json" ] && [ ! -L "$dir/series.json" ] || return 1
  context=$(jq -er '.context' "$dir/series.json") || return 1
  pointer="$(review_series_state_root "$root")/contexts/$context/current"
  review_context_lock_acquire "$root" "$context" || return $?
  trap 'review_context_lock_release >/dev/null 2>&1 || true' EXIT
  if [ -e "$dir/closed.json" ] || [ -L "$dir/closed.json" ]; then
    [ -f "$dir/closed.json" ] && [ ! -L "$dir/closed.json" ] || return 1
    existing_reason=$(jq -er 'select(.version==1 and .status=="closed") | .reason' "$dir/closed.json") || return 1
    [ "$existing_reason" = "$reason" ] || return 1
    if [ -e "$pointer" ] || [ -L "$pointer" ]; then
      [ -f "$pointer" ] && [ ! -L "$pointer" ] || return 1
      if [ "$(cat "$pointer" 2>/dev/null)" = "$id" ]; then rm -f "$pointer" || return 1; fi
    fi
    return 0
  fi
  [ -f "$pointer" ] && [ ! -L "$pointer" ] && [ "$(cat "$pointer" 2>/dev/null)" = "$id" ] || return 1
  tmp="$dir/.closed.$$"
  jq -cn --arg reason "$reason" --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{version:1,status:"closed",reason:$reason,closedAt:$at}' > "$tmp" \
    && ln "$tmp" "$dir/closed.json" 2>/dev/null || { rm -f "$tmp"; return 1; }
  rm -f "$tmp"
  rm -f "$pointer" || return 1
)

review_series_handoff_record() {
  local root="$1" key="$2" choice="$3" source="$4" tree="$5" series dir tmp reason branch route current
  case "$choice" in take-over) reason=take-over ;; escalate-pr) reason=escalated ;; *) return 1 ;; esac
  series=$(review_series_find_for_key "$root" "$key") || return 1
  dir=$(review_series_dir "$root" "$series")
  [ -f "$dir/series.json" ] && [ ! -L "$dir/series.json" ] || return 1
  branch=$(jq -er '.branch' "$dir/series.json") || return 1
  route=$(jq -er '.route' "$dir/series.json") || return 1
  printf '%s' "$tree" | grep -Eq '^[0-9a-f]{16}$' || return 1
  current=$(CLAUDE_PROJECT_DIR="$root" "${OH_HOME:-$root}/core/scripts/tree-digest.sh" 2>/dev/null) || return 1
  [ "$current" = "$tree" ] || return 1
  if [ -e "$dir/handoff.json" ] || [ -L "$dir/handoff.json" ]; then
    [ -f "$dir/handoff.json" ] && [ ! -L "$dir/handoff.json" ] || return 1
    jq -e --arg choice "$choice" --arg source "$source" --arg tree "$tree" '
      .version == 1 and .choice == $choice and .source == $source and .tree == $tree and
      .authorizesCompletion == false
    ' "$dir/handoff.json" >/dev/null 2>&1 || return 1
    review_series_close "$root" "$series" "$reason"
    return
  fi
  [ ! -e "$dir/closed.json" ] && [ ! -L "$dir/closed.json" ] || return 1
  [ "$(review_series_current "$root" "$branch" "$route" 2>/dev/null)" = "$series" ] || return 1
  review_window_ready "$root" "$series" "$tree" || return 1
  tmp="$dir/.handoff.$$"
  jq -cn --arg choice "$choice" --arg source "$source" --arg tree "$tree" \
    --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{version:1,choice:$choice,source:$source,tree:$tree,authorizesCompletion:false,recordedAt:$at}' > "$tmp" \
    && ln "$tmp" "$dir/handoff.json" 2>/dev/null || { rm -f "$tmp"; return 1; }
  rm -f "$tmp"
  review_series_close "$root" "$series" "$reason"
}

review_series_key_for() {
  local root="$1" branch="$2" series context head legacy rounds key
  series=$(review_series_current "$root" "$branch" 2>/dev/null) && {
    key=$(jq -er '.roundKey | select(type=="string" and length>0 and .!="-")' \
      "$(review_series_dir "$root" "$series")/series.json") || return 1
    printf '%s' "$key"
    return
  }
  # Preserve a pre-ADR-0051 non-delivery window long enough to migrate it into an explicit
  # series. Once the next start creates that series, amended HEAD no longer participates.
  head=$(git -C "$root" rev-parse HEAD 2>/dev/null) || return 1
  legacy="nd/$branch/$head"
  if type accepted_rounds_list >/dev/null 2>&1; then
    rounds=$(accepted_rounds_list "$root" "$legacy" 2>/dev/null) || return 1
    [ -z "$(printf '%s\n' "$rounds" | awk 'NF{print;exit}')" ] || { printf '%s' "$legacy"; return; }
  fi
  context=$(review_series_context "$root" "$branch") || return 1
  printf 'nd/context-%s' "$context"
}

review_attempts_dir() { printf '%s/attempts' "$(review_series_dir "$1" "$2")"; }

review_attempt_path_valid() {
  local root="$1" path="$2" prefix
  prefix="$(review_series_state_root "$root")/series/"
  case "$path" in "$prefix"*/attempts/a-[0-9][0-9][0-9][0-9][0-9][0-9]) ;; *) return 1 ;; esac
  [ -d "$path" ] && [ ! -L "$path" ] && [ -f "$path/start.json" ] && [ ! -L "$path/start.json" ]
}

# A process can die after atomically claiming the directory but before publishing start.json.
# That directory was never an admitted reviewer start, so readers ignore it and later starts
# move to the next ordinal instead of recreating a permanent stale lock.
review_attempt_unadmitted_dir() {
  [ -d "$2" ] && [ ! -L "$2" ] && [ ! -e "$2/start.json" ] && [ ! -L "$2/start.json" ]
}

review_attempt_count() {
  local root="$1" series="$2" dir entry count=0
  dir=$(review_attempts_dir "$root" "$series")
  [ -e "$dir" ] || { printf '0'; return 0; }
  [ -d "$dir" ] && [ ! -L "$dir" ] || return 1
  for entry in "$dir"/*; do
    [ -e "$entry" ] || [ -L "$entry" ] || continue
    review_attempt_unadmitted_dir "$root" "$entry" && continue
    review_attempt_path_valid "$root" "$entry" || return 1
    review_attempt_validate_start "$root" "$entry" || return 1
    count=$((count + 1))
  done
  printf '%s' "$count"
}

review_attempt_pending_for() {
  local root="$1" series="$2" host="$3" owner="${4:-}" dir entry eh eo found=""
  dir=$(review_attempts_dir "$root" "$series")
  [ -d "$dir" ] || return 1
  for entry in "$dir"/*; do
    [ -e "$entry" ] || continue
    review_attempt_unadmitted_dir "$root" "$entry" && continue
    review_attempt_path_valid "$root" "$entry" || {
      echo "review-attempt: invalid attempt path: $entry" >&2; return 2;
    }
    review_attempt_validate_start "$root" "$entry" || {
      echo "review-attempt: corrupt start or bound snapshot/request: $entry/start.json" >&2; return 2;
    }
    [ ! -e "$entry/completion.json" ] && [ ! -L "$entry/completion.json" ] || continue
    eh=$(jq -r '.host' "$entry/start.json" 2>/dev/null) || return 2
    eo=$(jq -r '.owner' "$entry/start.json" 2>/dev/null) || return 2
    [ "$eh" = "$host" ] || continue
    [ -z "$owner" ] || [ "$eo" = "$owner" ] || continue
    [ -z "$found" ] || {
      echo "review-attempt: ambiguous pending attempts: $found and $entry; preserve both and resolve their host ownership." >&2; return 2;
    }
    found="$entry"
  done
  [ -n "$found" ] || return 1
  printf '%s' "$found"
}

review_attempt_owner_used() {
  local root="$1" series="$2" host="$3" owner="$4" dir entry
  dir=$(review_attempts_dir "$root" "$series")
  [ -d "$dir" ] || return 1
  for entry in "$dir"/*; do
    [ -e "$entry" ] || continue
    review_attempt_unadmitted_dir "$root" "$entry" && continue
    review_attempt_path_valid "$root" "$entry" || return 0
    review_attempt_validate_start "$root" "$entry" || return 0
    if [ "$(jq -r '.host' "$entry/start.json" 2>/dev/null)" = "$host" ] \
       && [ "$(jq -r '.owner' "$entry/start.json" 2>/dev/null)" = "$owner" ]; then
      return 0
    fi
  done
  return 1
}

review_scope_terminal() {
  local attempt="$1" transition status destination original
  transition="$attempt/scope-transition.json"
  [ -f "$transition" ] && [ ! -L "$transition" ] || return 1
  status=$(jq -r '.status' "$transition" 2>/dev/null) || return 1
  if [ "$status" = applied ]; then
    jq -er '.resultTree | select(test("^[0-9a-f]{16}$"))' "$transition"
    return
  fi
  if [ "$status" = pr-required ]; then
    jq -er 'select(.prResolutionId|test("^[0-9a-f]{64}$")) |
      .originalTree | select(test("^[0-9a-f]{16}$"))' "$transition"
    return
  fi
  [ "$status" = human-route-required ] || return 1
  destination="$attempt/scope-destination.json"
  [ -f "$destination" ] && [ ! -L "$destination" ] || return 1
  original=$(jq -r '.originalTree' "$transition" 2>/dev/null) || return 1
  jq -er --arg original "$original" '
    select(.version==1 and .status=="applied" and .kind=="github-issue" and
      .originalTree==$original and (.resultTree|test("^[0-9a-f]{16}$")) and
      (.issueUrl|type=="string" and test("^https://[^/]+/.+/issues/[1-9][0-9]*$")) and
      (.prResolutionId|test("^[0-9a-f]{64}$"))) | .resultTree
  ' "$destination"
}

review_attempt_latest() {
  local root="$1" series="$2" attempts entry found="" ordinal best=0
  attempts=$(review_attempts_dir "$root" "$series")
  [ -d "$attempts" ] && [ ! -L "$attempts" ] || return 1
  for entry in "$attempts"/*; do
    [ -e "$entry" ] || continue
    review_attempt_unadmitted_dir "$root" "$entry" && continue
    review_attempt_path_valid "$root" "$entry" || return 1
    review_attempt_validate_start "$root" "$entry" || return 1
    ordinal=$(jq -er '.ordinal' "$entry/start.json") || return 1
    if [ "$ordinal" -gt "$best" ]; then found="$entry"; best="$ordinal"; fi
  done
  [ -n "$found" ] || return 1
  printf '%s' "$found"
}

# Validate the semantic transition between one retained attempt and a proposed next tree.
# This is shared by the allocator and by receipt readers, so pre-ADR bad local chains cannot
# hide an unresolved blocker behind a later clean attempt.
# Only an attributable ended reviewer with zero response bytes permits an automatic
# replacement. The allocator still checks current context, readiness and the same window.
review_attempt_no_result() {
  local root="$1" attempt="$2" tree="$3"
  review_attempt_validate_start "$root" "$attempt" || return 1
  [ -f "$attempt/raw.md" ] && [ ! -L "$attempt/raw.md" ] && [ ! -s "$attempt/raw.md" ] || return 1
  [ ! -e "$attempt/resolution.json" ] && [ ! -L "$attempt/resolution.json" ] || return 1
  [ "$(jq -r '.tree' "$attempt/start.json")" = "$tree" ] || return 1
  jq -e '(.status=="empty" or .status=="interrupted") and .noResult==true and
    .outcome=="ambiguous" and .counts=={blocking:0,concern:0,scope:0} and .findings==[] and
    .rawSha256==null' "$attempt/completion.json" >/dev/null 2>&1
}

review_attempt_allows_next() {
  local root="$1" attempt="$2" next_tree="$3" retained="${4:-false}" status outcome start_tree choice result
  [ -f "$attempt/completion.json" ] && [ ! -L "$attempt/completion.json" ] || return 1
  status=$(jq -r '.status' "$attempt/completion.json" 2>/dev/null) || return 1
  start_tree=$(jq -r '.tree' "$attempt/start.json" 2>/dev/null) || return 1
  case "$status" in
    binding-failed) return 0 ;;
    empty|interrupted)
      review_attempt_no_result "$root" "$attempt" "$next_tree" && return 0
      # Preserve chains already admitted under the old interrupted-start rule. This cannot
      # admit a new attempt: the allocator never sets retained, and new completions always
      # carry an explicit noResult boolean.
      if [ "$retained" = true ] && [ "$status" = interrupted ] &&
         jq -e 'has("noResult") | not' "$attempt/completion.json" >/dev/null; then return 0; fi
      ;;
    completed) ;;
    *) return 1 ;;
  esac
  outcome=$(jq -r '.outcome' "$attempt/completion.json" 2>/dev/null) || return 1
  case "$outcome" in
    blocking|blocking+concern)
      [ "$next_tree" != "$start_tree" ] ;;
    blocking+scope|blocking+concern+scope)
      result=$(review_scope_terminal "$attempt" 2>/dev/null) || return 1
      [ "$next_tree" != "$result" ] ;;
    concern|scope|concern+scope|ambiguous)
      [ -f "$attempt/resolution.json" ] && [ ! -L "$attempt/resolution.json" ] || return 1
      choice=$(jq -r '.choice' "$attempt/resolution.json" 2>/dev/null) || return 1
      case "$outcome:$choice" in
        concern:fix-concerns) [ "$next_tree" != "$start_tree" ] ;;
        concern:accept-concerns) [ "$next_tree" != "$start_tree" ] ;;
        scope:route-scope|scope:dismiss-scope)
          result=$(review_scope_terminal "$attempt" 2>/dev/null) || return 1
          [ "$next_tree" != "$result" ] ;;
        concern+scope:fix-concerns+route-scope|concern+scope:fix-concerns+dismiss-scope)
          result=$(review_scope_terminal "$attempt" 2>/dev/null) || return 1
          [ "$next_tree" != "$result" ] ;;
        concern+scope:accept-concerns+route-scope|concern+scope:accept-concerns+dismiss-scope)
          result=$(review_scope_terminal "$attempt" 2>/dev/null) || return 1
          [ "$next_tree" != "$result" ] ;;
        ambiguous:review-again) return 0 ;;
        *) return 1 ;;
      esac ;;
    clean)
      [ "$next_tree" != "$start_tree" ] ;;
    *) return 1 ;;
  esac
}

# Window renewal/handoff follows semantic disposition; spending the allowance must not
# hide findings. Reuse the allocator's transition rule, including historical no-attempt
# series, instead of maintaining a second outcome matrix in each host adapter.
review_window_ready() {
  local root="$1" series="$2" tree="$3" count attempt outcome
  count=$(review_attempt_count "$root" "$series") || {
    echo 'Review evidence is unreadable. Preserve it and repair the named series before presenting window choices.' >&2
    return 1
  }
  [ "$count" != 0 ] || return 0
  attempt=$(review_attempt_latest "$root" "$series") &&
    review_attempt_chain_valid_through "$root" "$attempt" || {
      echo 'Review history has an invalid transition. Inspect round-status.sh and the retained attempts; repair the evidence before presenting window choices.' >&2
      return 1
    }
  review_attempt_allows_next "$root" "$attempt" "$tree" && return 0
  echo 'Handle the current review result before requesting another window or a window handoff. No window choice was recorded.' >&2
  review_attempt_summary "$attempt" >&2 || {
    echo "Retain the ended review with review-retain.sh, or await the live reviewer. Pending attempt: $attempt" >&2
    return 1
  }
  outcome=$(jq -r .outcome "$attempt/completion.json") || return 1
  case "$outcome" in
    blocking*) echo 'Route any scope findings with review-route-scope.sh; fix the blockers and accompanying concerns, then verify before requesting another review.' >&2 ;;
    clean) echo 'This tree is already reviewed. Continue its supported completion step; another review needs an actual changed tree.' >&2 ;;
    *)
      if [ -f "$attempt/resolution.json" ]; then
        echo "Follow the saved choice at $attempt/resolution.json: finish its fix or pending routing/publication with review-route-scope.sh. Do not ask for the same choice again." >&2
      elif [ -n "${CODEX_HOOK:-}${CODEX_SESSION_ID:-}" ]; then codex_gate_present review "$outcome" >&2
      else
        echo 'Present one single-select question with these options:' >&2
        review_choice_labels "$outcome" >&2
      fi ;;
  esac
  return 1
}

review_attempt_chain_valid_through() {
  local root="$1" target="$2" series attempts entry prior="" target_ordinal ordinal
  review_attempt_path_valid "$root" "$target" || return 1
  series=$(jq -er '.seriesId' "$target/start.json") || return 1
  target_ordinal=$(jq -er '.ordinal' "$target/start.json") || return 1
  attempts=$(review_attempts_dir "$root" "$series")
  ordinal=1
  while [ "$ordinal" -le "$target_ordinal" ]; do
    entry=$(printf '%s/a-%06d' "$attempts" "$ordinal")
    if review_attempt_unadmitted_dir "$root" "$entry"; then ordinal=$((ordinal + 1)); continue; fi
    review_attempt_path_valid "$root" "$entry" || return 1
    review_attempt_validate_start "$root" "$entry" || return 1
    if [ -n "$prior" ]; then
      review_attempt_allows_next "$root" "$prior" "$(jq -r '.tree' "$entry/start.json")" true || return 1
    fi
    prior="$entry"
    ordinal=$((ordinal + 1))
  done
  [ "$prior" = "$target" ]
}

review_attempt_complete() {
  local root="$1" attempt="$2" status="$3" raw="${4:--}" input_tokens="${5:-}" output_tokens="${6:-}"
  local tmp raw_tmp semantic now started elapsed raw_sha=null no_result="${7:-false}"
  review_attempt_path_valid "$root" "$attempt" || return 1
  review_attempt_validate_start "$root" "$attempt" || return 1
  case "$status" in completed|interrupted|binding-failed|empty|unattributed) ;; *) return 1 ;; esac
  case "$no_result:$status" in false:*) ;; true:empty|true:interrupted) ;; *) return 1 ;; esac
  # Never discard partial prose or findings by classifying them as empty/interrupted.
  if [ "$status" != completed ] && [ "$status" != binding-failed ] && [ "$raw" != - ]; then
    [ -f "$raw" ] && [ ! -L "$raw" ] && [ ! -s "$raw" ] || return 1
  fi
  if [ -e "$attempt/completion.json" ] || [ -L "$attempt/completion.json" ]; then
    [ -f "$attempt/completion.json" ] && [ ! -L "$attempt/completion.json" ] || return 1
    [ "$(jq -r '.status' "$attempt/completion.json" 2>/dev/null)" = "$status" ] || return 1
    [ "$(jq -r '.noResult // false' "$attempt/completion.json")" = "$no_result" ] || return 1
    if [ "$status" = completed ] || [ "$status" = binding-failed ]; then
      [ -f "$raw" ] && [ ! -L "$raw" ] && [ -f "$attempt/raw.md" ] && [ ! -L "$attempt/raw.md" ] \
        && cmp -s "$raw" "$attempt/raw.md" || return 1
    fi
    return 0
  fi
  raw_tmp="$attempt/.raw.$$"
  if [ "$status" = completed ] || [ "$status" = binding-failed ]; then
    [ -f "$raw" ] && [ ! -L "$raw" ] || return 1
    cp "$raw" "$raw_tmp" || return 1
  else
    : > "$raw_tmp" || return 1
  fi
  if ! ln "$raw_tmp" "$attempt/raw.md" 2>/dev/null; then
    [ -f "$attempt/raw.md" ] && [ ! -L "$attempt/raw.md" ] \
      && [ ! -e "$attempt/completion.json" ] && [ ! -L "$attempt/completion.json" ] \
      && cmp -s "$raw_tmp" "$attempt/raw.md" || { rm -f "$raw_tmp"; return 1; }
  fi
  rm -f "$raw_tmp"
  if [ "$status" = completed ] || [ "$status" = binding-failed ]; then
    semantic=$(review_semantic_json "$attempt/raw.md") || return 1
    raw_sha=$(review_workflow_file_hash "$attempt/raw.md") || return 1
  else
    semantic='{"outcome":"ambiguous","counts":{"blocking":0,"concern":0,"scope":0},"formatAnomalous":false,"findings":[]}'
  fi
  case "$input_tokens" in ''|*[!0-9]*) input_tokens=null ;; esac
  case "$output_tokens" in ''|*[!0-9]*) output_tokens=null ;; esac
  now=$(date +%s)
  started=$(jq -er '.startedEpoch | select(type=="number")' "$attempt/start.json") || return 1
  [ "$now" -ge "$started" ] || return 1
  elapsed=$((now - started))
  tmp="$attempt/.completion.$$"
  printf '%s' "$semantic" | jq -c \
    --arg status "$status" --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg rawSha "$raw_sha" --argjson elapsed "$elapsed" --argjson noResult "$no_result" \
    --argjson inputTokens "$input_tokens" --argjson outputTokens "$output_tokens" '
      . + {version:1,status:$status,noResult:$noResult,completedAt:$at,elapsedSeconds:$elapsed,
        rawSha256:(if $rawSha=="null" then null else $rawSha end),
        hostTokenUsage:{input:$inputTokens,output:$outputTokens}}
    ' > "$tmp" || { rm -f "$tmp"; return 1; }
  ln "$tmp" "$attempt/completion.json" 2>/dev/null || { rm -f "$tmp"; return 1; }
  rm -f "$tmp"
}

review_unattributed_retain() {
  local root="$1" host="$2" owner="$3" session="$4" raw="$5" reason="$6" attributed="${7:-}"
  local dir nonce base tmp attempt_id="" series_id=""
  [ -f "$raw" ] && [ ! -L "$raw" ] || return 1
  if [ -n "$attributed" ]; then
    review_attempt_path_valid "$root" "$attributed" || return 1
    attempt_id="${attributed##*/}"
    series_id=$(jq -er '.seriesId' "$attributed/start.json") || return 1
  fi
  dir="$(review_series_state_root "$root")/unattributed"; mkdir -p "$dir" || return 1
  nonce=$(review_workflow_nonce) || return 1
  base="$dir/$(date +%s)-$nonce"
  cp "$raw" "$base.raw.md" || return 1
  tmp="$base.json.$$"
  jq -cn --arg host "$host" --arg owner "$owner" --arg session "$session" --arg reason "$reason" \
    --arg attempt "$attempt_id" --arg series "$series_id" \
    --arg raw "${base##*/}.raw.md" --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{version:1,status:"unattributed",host:$host,owner:$owner,session:$session,reason:$reason,
      attemptId:(if $attempt=="" then null else $attempt end),
      seriesId:(if $series=="" then null else $series end),raw:$raw,recordedAt:$at}' \
    > "$tmp" && mv "$tmp" "$base.json" || { rm -f "$tmp" "$base.raw.md"; return 1; }
  printf '%s' "$base.json"
}

review_attempt_start() (
  local root="$1" series="$2" host="$3" owner="$4" session="$5" tree="$6"
  local branch="$7" key="$8" snapshot="$9" request="${10:--}"
  local sdir attempts pending old_session ordinal dir head snapsha reqsha=null tmp latest used window context current
  case "$host" in codex|claude) ;; *) return 1 ;; esac
  [ -n "$owner" ] && [ -n "$session" ] || return 1
  printf '%s' "$tree" | grep -Eq '^[0-9a-f]{16}$' || return 1
  sdir=$(review_series_dir "$root" "$series")
  [ -f "$sdir/series.json" ] && [ ! -L "$sdir/series.json" ] || return 1
  context=$(jq -er '.context | select(test("^[0-9a-f]{64}$"))' "$sdir/series.json") || return 1
  [ -f "$snapshot" ] && [ ! -L "$snapshot" ] || return 1
  if [ "$request" != - ]; then [ -f "$request" ] && [ ! -L "$request" ] || return 1; fi
  review_context_lock_acquire "$root" "$context" || return $?
  trap 'review_context_lock_release >/dev/null 2>&1 || true' EXIT
  # Close, current-series selection, and attempt publication share this lock. Revalidate
  # after acquiring it so no attempt can be appended to a series closed concurrently.
  [ ! -e "$sdir/closed.json" ] && [ ! -L "$sdir/closed.json" ] || return 1
  [ "$(jq -r '.branch' "$sdir/series.json" 2>/dev/null)" = "$branch" ] || return 1
  current=$(review_series_current "$root" "$branch" "$(jq -r '.route' "$sdir/series.json")" 2>/dev/null) || return 1
  [ "$current" = "$series" ] || return 1
  attempts=$(review_attempts_dir "$root" "$series"); mkdir -p "$attempts" || return 1
  # SubagentStart remains a second check after the blocking pre-tool hook. This check and
  # publication share the context lifecycle lock, so two starts at window-1 cannot both consume it.
  type round_count >/dev/null 2>&1 && type round_window >/dev/null 2>&1 || return 1
  used=$(round_count "$root" "$key") || return 1
  window=$(round_window "$root" "$key") || return 1
  [ "$used" -lt "$window" ] || {
    echo "review-start: review window spent ($used used / $window granted)." >&2
    return 2
  }
  if [ "$host" = codex ]; then
    review_attempt_owner_used "$root" "$series" "$host" "$owner" && {
      echo "missing fresh-reviewer admission: spawn a new invariant reviewer in this session." >&2
      return 2
    }
    pending=$(review_attempt_pending_for "$root" "$series" codex 2>/dev/null)
    case $? in
      0)
        echo "review-start: retain the pending Codex reviewer output before starting another reviewer." >&2
        return 2
        ;;
      1) ;;
      *) return 1 ;;
    esac
  else
    pending=$(review_attempt_pending_for "$root" "$series" claude 2>/dev/null)
    case $? in
      0)
        old_session=$(jq -r '.session' "$pending/start.json" 2>/dev/null) || return 1
        if [ "$old_session" = "$session" ]; then
          echo "review-start: this Claude session already has an active attempt for the context." >&2
          return 2
        fi
        if [ -f "$pending/raw.md" ] && [ ! -L "$pending/raw.md" ] && [ -s "$pending/raw.md" ]; then
          # The old stop reached immutable raw publication but died before its completion
          # marker. Finish semantic extraction from those already-attributed bytes.
          review_attempt_complete "$root" "$pending" completed "$pending/raw.md" || return 1
        else
          # ADR-0051 §6: a different Claude host session supersedes this abandoned
          # zero-byte attempt. Preserve that automatic recovery inside the same window.
          review_attempt_complete "$root" "$pending" interrupted - "" "" true || return 1
        fi
        ;;
      1) ;;
      *) return 1 ;;
    esac
  fi
  latest=$(review_attempt_latest "$root" "$series" 2>/dev/null)
  case $? in
    0) review_attempt_allows_next "$root" "$latest" "$tree" || {
      echo "review-start: the previous attempt still requires its semantic transition before another review." >&2
      return 2
    } ;;
    1) ;;
    *) return 1 ;;
  esac
  ordinal=1
  while :; do
    [ "$ordinal" -le 999999 ] || return 1
    dir=$(printf '%s/a-%06d' "$attempts" "$ordinal")
    mkdir "$dir" 2>/dev/null && break
    [ -e "$dir" ] || [ -L "$dir" ] || return 1
    ordinal=$((ordinal + 1))
  done
  cp "$snapshot" "$dir/snapshot.txt" || { rmdir "$dir"; return 1; }
  snapsha=$(review_workflow_file_hash "$dir/snapshot.txt") || { rm -rf "$dir"; return 1; }
  if [ "$request" != - ]; then
    cp "$request" "$dir/request.md" || { rm -rf "$dir"; return 1; }
    reqsha=$(review_workflow_file_hash "$dir/request.md") || { rm -rf "$dir"; return 1; }
  fi
  head=$(git -C "$root" rev-parse HEAD 2>/dev/null) || { rm -rf "$dir"; return 1; }
  tmp="$dir/.start.$$"
  jq -cn --arg id "${dir##*/}" --arg series "$series" --argjson ordinal "$ordinal" \
    --arg host "$host" --arg owner "$owner" --arg session "$session" --arg tree "$tree" \
    --arg branch "$branch" --arg key "$key" --arg head "$head" --arg snapshot "$snapsha" \
    --arg harness "${OH_HARNESS_VERSION:-legacy}" --arg config "${OH_CONFIG_HASH:-legacy}" --arg repository "${OH_REPOSITORY_ID:-legacy}" \
    --arg request "$reqsha" --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --argjson epoch "$(date +%s)" '
      {version:1,id:$id,seriesId:$series,ordinal:$ordinal,host:$host,owner:$owner,session:$session,
       tree:$tree,branch:$branch,roundKey:$key,head:$head,snapshotSha256:$snapshot,
       requestSha256:(if $request=="null" then null else $request end),startedAt:$at,startedEpoch:$epoch,
       harnessVersion:$harness,configHash:$config,repositoryId:$repository}
  ' > "$tmp" && mv "$tmp" "$dir/start.json" || { rm -rf "$dir"; return 1; }
  printf '%s' "$dir"
)

review_resolution_record() {
  local root="$1" attempt="$2" choice="$3" source="$4" tree="$5" outcome status tmp
  review_attempt_path_valid "$root" "$attempt" || return 1
  review_attempt_validate_start "$root" "$attempt" || return 1
  [ -f "$attempt/completion.json" ] && [ ! -L "$attempt/completion.json" ] || return 1
  [ "$(jq -r '.tree' "$attempt/start.json")" = "$tree" ] || return 1
  status=$(jq -r '.status' "$attempt/completion.json") || return 1
  case "$status" in completed|empty|interrupted) ;; *) return 1 ;; esac
  outcome=$(jq -r '.outcome' "$attempt/completion.json") || return 1
  # Callers use semantic choices; verify them against the outcome directly.
  case "$outcome:$choice" in
    concern:fix-concerns|concern:accept-concerns|scope:route-scope|scope:dismiss-scope|\
    concern+scope:fix-concerns+route-scope|concern+scope:fix-concerns+dismiss-scope|\
    concern+scope:accept-concerns+route-scope|concern+scope:accept-concerns+dismiss-scope|\
    ambiguous:review-again|ambiguous:take-over) ;;
    *) return 1 ;;
  esac
  if [ -e "$attempt/resolution.json" ] || [ -L "$attempt/resolution.json" ]; then
    [ -f "$attempt/resolution.json" ] && [ ! -L "$attempt/resolution.json" ] || return 1
    jq -e --arg choice "$choice" --arg tree "$tree" '
      .version==1 and .choice==$choice and .tree==$tree and
      (.source|type=="string" and length>0)
    ' "$attempt/resolution.json" >/dev/null 2>&1 || return 1
  else
    tmp="$attempt/.resolution.$$"
    jq -cn --arg choice "$choice" --arg source "$source" --arg tree "$tree" \
      --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      '{version:1,choice:$choice,source:$source,tree:$tree,recordedAt:$at}' > "$tmp" \
      && ln "$tmp" "$attempt/resolution.json" 2>/dev/null || { rm -f "$tmp"; return 1; }
    rm -f "$tmp"
  fi
  if [ "$outcome:$choice" = concern:accept-concerns ]; then
    review_pr_resolution_publish "$root" "$attempt" accept-concerns "$choice" reviewed-tree "$tree" >/dev/null
  fi
}

review_attempt_authorizes() {
  local root="$1" attempt="$2" tree="$3" outcome choice expected_tree result latest series
  review_attempt_path_valid "$root" "$attempt" || return 1
  review_attempt_validate_start "$root" "$attempt" || return 1
  review_attempt_chain_valid_through "$root" "$attempt" || return 1
  series=$(jq -er '.seriesId' "$attempt/start.json") || return 1
  latest=$(review_attempt_latest "$root" "$series") || return 1
  [ "$latest" = "$attempt" ] || return 1
  [ "$(jq -r '.status' "$attempt/completion.json" 2>/dev/null)" = completed ] || return 1
  outcome=$(jq -r '.outcome' "$attempt/completion.json") || return 1
  expected_tree=$(jq -r '.tree' "$attempt/start.json") || return 1
  [ "$outcome" = clean ] && { [ "$expected_tree" = "$tree" ]; return; }
  [ -f "$attempt/resolution.json" ] && [ ! -L "$attempt/resolution.json" ] || return 1
  [ "$(jq -r '.tree' "$attempt/resolution.json")" = "$expected_tree" ] || return 1
  review_pr_resolution_validate "$root" "$attempt" || return 1
  choice=$(jq -r '.choice' "$attempt/resolution.json") || return 1
  case "$outcome:$choice" in
    concern:accept-concerns) [ "$expected_tree" = "$tree" ] ;;
    scope:route-scope|scope:dismiss-scope|\
    concern+scope:accept-concerns+route-scope|concern+scope:accept-concerns+dismiss-scope)
      result=$(review_scope_terminal "$attempt") \
        && [ "$(jq -r '.originalTree' "$attempt/scope-transition.json")" = "$expected_tree" ] \
        && [ "$result" = "$tree" ] ;;
    *) return 1 ;;
  esac
}

review_attempt_latest_for_tree() {
  local root="$1" key="$2" tree="$3" series attempts entry found="" ordinal best=0
  series=$(review_series_find_for_key "$root" "$key") || return 1
  attempts=$(review_attempts_dir "$root" "$series")
  [ -d "$attempts" ] || return 1
  for entry in "$attempts"/*; do
    [ -e "$entry" ] || continue
    review_attempt_unadmitted_dir "$root" "$entry" && continue
    review_attempt_path_valid "$root" "$entry" || return 1
    review_attempt_validate_start "$root" "$entry" || return 1
    [ "$(jq -r '.roundKey' "$entry/start.json" 2>/dev/null)" = "$key" ] || continue
    if [ "$(jq -r '.tree' "$entry/start.json" 2>/dev/null)" != "$tree" ]; then
      [ -f "$entry/scope-transition.json" ] \
        && [ "$(jq -r '.resultTree' "$entry/scope-transition.json" 2>/dev/null)" = "$tree" ] || continue
    fi
    [ -f "$entry/completion.json" ] && [ ! -L "$entry/completion.json" ] || continue
    review_attempt_chain_valid_through "$root" "$entry" || continue
    ordinal=$(jq -r '.ordinal' "$entry/start.json" 2>/dev/null) || return 1
    if [ "$ordinal" -ge "$best" ]; then found="$entry"; best="$ordinal"; fi
  done
  [ -n "$found" ] || return 1
  series=$(jq -er '.seriesId' "$found/start.json") || return 1
  [ "$(review_attempt_latest "$root" "$series")" = "$found" ] || return 1
  printf '%s' "$found"
}

review_tracked_target_relative() {
  local root="$1" target="$2" rel
  case "$target" in "$root"/*) rel="${target#"$root"/}" ;; *) return 1 ;; esac
  case "$rel" in ""|/*|../*|*/../*|*/..|.deliver|.deliver/*|*$'\n'*) return 1 ;; esac
  [ -f "$target" ] && [ ! -L "$target" ] || return 1
  git -C "$root" ls-files --error-unmatch -- "$rel" >/dev/null 2>&1 || return 1
  printf '%s' "$rel"
}

review_tree_without_path() {
  CLAUDE_PROJECT_DIR="$1" "${OH_HOME:-$1}/core/scripts/tree-digest.sh" --exclude-path "$2" 2>/dev/null
}

# Publish everything needed to recover a reviewed tracked-file transition before changing it.
review_consumption_intent_start() {
  local root="$1" attempt="$2" action="$3" target="$4" after="$5" output="$6"
  local rel original current other before_sha after_sha dir tmp branch series
  review_attempt_path_valid "$root" "$attempt" || return 1
  review_attempt_validate_start "$root" "$attempt" || return 1
  case "$action" in ""|*[!A-Za-z0-9:_-]*) return 1 ;; esac
  rel=$(review_tracked_target_relative "$root" "$target") || return 1
  [ -f "$after" ] && [ ! -L "$after" ] || return 1
  original=$(jq -er '.tree' "$attempt/start.json") || return 1
  current=$(CLAUDE_PROJECT_DIR="$root" "${OH_HOME:-$root}/core/scripts/tree-digest.sh" 2>/dev/null) || return 1
  [ "$current" = "$original" ] || return 1
  review_attempt_authorizes "$root" "$attempt" "$original" || return 1
  branch=$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null) || return 1
  [ "$branch" = "$(jq -r '.branch' "$attempt/start.json")" ] || return 1
  other=$(review_tree_without_path "$root" "$rel") || return 1
  before_sha=$(review_workflow_file_hash "$target") || return 1
  after_sha=$(review_workflow_file_hash "$after") || return 1
  dir="$attempt/consumption-intent"
  if [ -e "$dir/intent.json" ] || [ -L "$dir/intent.json" ]; then
    [ -f "$dir/intent.json" ] && [ ! -L "$dir/intent.json" ] \
      && [ -f "$dir/before" ] && [ ! -L "$dir/before" ] \
      && [ -f "$dir/after" ] && [ ! -L "$dir/after" ] || return 1
    jq -e --arg action "$action" --arg target "$rel" --arg original "$original" \
      --arg other "$other" --arg before "$before_sha" --arg after "$after_sha" \
      --arg output "$output" --arg branch "$branch" '
        .version==1 and .action==$action and .target==$target and .originalTree==$original and
        .otherTree==$other and .beforeSha256==$before and .afterSha256==$after and
        .output==$output and .branch==$branch
      ' "$dir/intent.json" >/dev/null 2>&1 \
      && cmp -s "$target" "$dir/before" && cmp -s "$after" "$dir/after"
    return
  fi
  mkdir -p "$dir" || return 1
  [ ! -L "$dir" ] || return 1
  tmp="$dir/.before.$$"; cp -p "$target" "$tmp" && mv "$tmp" "$dir/before" \
    || { rm -f "$tmp"; return 1; }
  tmp="$dir/.after.$$"; cp -p "$after" "$tmp" && mv "$tmp" "$dir/after" \
    || { rm -f "$tmp"; return 1; }
  series=$(jq -er '.seriesId' "$attempt/start.json") || return 1
  tmp="$dir/.intent.$$"
  jq -cn --arg action "$action" --arg target "$rel" --arg original "$original" \
    --arg other "$other" --arg before "$before_sha" --arg after "$after_sha" \
    --arg output "$output" --arg branch "$branch" --arg series "$series" \
    --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '
      {version:1,action:$action,target:$target,originalTree:$original,otherTree:$other,
       beforeSha256:$before,afterSha256:$after,output:$output,branch:$branch,seriesId:$series,
       recordedAt:$at}
    ' > "$tmp" && ln "$tmp" "$dir/intent.json" 2>/dev/null \
    || { rm -f "$tmp"; return 1; }
  rm -f "$tmp"
}

review_consumption_matches_current() {
  local root="$1" attempt="$2" action="$3" target="$4" rel dir branch other
  rel=$(review_tracked_target_relative "$root" "$target") || return 1
  dir="$attempt/consumption-intent"
  [ -f "$dir/intent.json" ] && [ ! -L "$dir/intent.json" ] \
    && [ -f "$dir/after" ] && [ ! -L "$dir/after" ] || return 1
  branch=$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null) || return 1
  other=$(review_tree_without_path "$root" "$rel") || return 1
  jq -e --arg action "$action" --arg target "$rel" --arg branch "$branch" --arg other "$other" '
    .version==1 and .action==$action and .target==$target and .branch==$branch and
    .otherTree==$other and (.output|type=="string") and
    (.seriesId|test("^s-[0-9]{10}-[0-9a-f]{24}$"))
  ' "$dir/intent.json" >/dev/null 2>&1 \
    && cmp -s "$target" "$dir/after" \
    && [ "$(review_workflow_file_hash "$target")" = "$(jq -r '.afterSha256' "$dir/intent.json")" ]
}

review_consumption_recover() {
  local root="$1" attempt="$2" action="$3" target="$4" dir series output outcome reason=resolved
  review_attempt_path_valid "$root" "$attempt" || return 1
  review_consumption_matches_current "$root" "$attempt" "$action" "$target" || return 1
  dir="$attempt/consumption-intent"
  series=$(jq -er '.seriesId' "$dir/intent.json") || return 1
  [ "$series" = "$(jq -r '.seriesId' "$attempt/start.json")" ] || return 1
  outcome=$(jq -er '.outcome' "$attempt/completion.json") || return 1
  [ "$outcome" = clean ] && reason=clean
  review_series_close "$root" "$series" "$reason" || return 1
  output=$(jq -r '.output' "$dir/intent.json") || return 1
  printf '%s' "$output"
}

review_consumption_recover_current() {
  local root="$1" action="$2" target="$3" base series attempt found="" count=0
  base="$(review_series_state_root "$root")/series"
  [ -d "$base" ] || return 1
  for series in "$base"/s-*; do
    [ -d "$series/attempts" ] || continue
    for attempt in "$series/attempts"/a-*; do
      [ -d "$attempt" ] || continue
      if review_consumption_matches_current "$root" "$attempt" "$action" "$target" 2>/dev/null; then
        found="$attempt"; count=$((count + 1))
      fi
    done
  done
  [ "$count" = 1 ] || return 1
  review_consumption_recover "$root" "$found" "$action" "$target"
}

review_consumption_required_resolution_ids() {
  local root="$1" action="$2" target="$3" base series attempt dir found=0 ids
  base="$(review_series_state_root "$root")/series"; [ -d "$base" ] || return 0
  for series in "$base"/s-*; do
    [ -d "$series/attempts" ] || continue
    for attempt in "$series/attempts"/a-*; do
      dir="$attempt/consumption-intent"
      [ -f "$dir/intent.json" ] && [ ! -L "$dir/intent.json" ] || continue
      [ "$(jq -r '.action' "$dir/intent.json" 2>/dev/null)" = "$action" ] || continue
      review_consumption_matches_current "$root" "$attempt" "$action" "$target" 2>/dev/null || continue
      ids=$(jq -r '.output' "$dir/intent.json" | sed -n 's/^Review-Resolution: \([0-9a-f]\{64\}\)$/\1/p') \
        || return 1
      [ -n "$ids" ] || continue
      printf '%s\n' "$ids"
      found=$((found + 1))
    done
  done
  [ "$found" -le 1 ]
}

review_design_status() {
  [ -f "$1" ] && [ ! -L "$1" ] || return 1
  awk '/^---[[:space:]]*$/{n++;next} n==1 && /^status:[[:space:]]*/{
    sub(/^status:[[:space:]]*/,""); print; exit
  }' "$1"
}

review_decision_subject() {
  [ -f "$1" ] && [ ! -L "$1" ] || return 1
  awk '/^---[[:space:]]*$/{n++;next} n==1 && /^subject:[[:space:]]*/{
    sub(/^subject:[[:space:]]*/,""); sub(/[[:space:]]*$/,""); print; exit
  } n>1 {exit}' "$1"
}

# Resolve routing identity once, when the series is created. The lifecycle design is not
# part of the reviewed subject: complete/freeze may have changed it before a recovery starts.
review_subject_resolve() {
  local root="$1" key="$2" doc candidate design_rel=- design_status=- status
  local matches="" changed="" count=0 paths path declared subject=product harness_seen=0 product_seen=0
  case "$key" in
    [0-9][0-9][0-9][0-9]-t*|[0-9][0-9][0-9][0-9]-finalize)
      doc="${key%%-*}"
      for candidate in "$root/docs/design/$doc"-*.md; do
        [ -f "$candidate" ] && [ ! -L "$candidate" ] || continue
        matches="$matches${matches:+$'\n'}${candidate#"$root"/}"
      done
      [ "$(printf '%s\n' "$matches" | awk 'NF{n++} END{print n+0}')" = 1 ] || return 1
      design_rel="$matches"
      ;;
    *)
      changed=$( {
        git -C "$root" diff --name-only HEAD -- 'docs/design/[0-9][0-9][0-9][0-9]-*.md' 2>/dev/null
        git -C "$root" ls-files --others --exclude-standard -- 'docs/design/[0-9][0-9][0-9][0-9]-*.md' 2>/dev/null
      } | awk 'NF && !seen[$0]++') || return 1
      count=$(printf '%s\n' "$changed" | awk 'NF{n++} END{print n+0}')
      if [ "$count" = 1 ]; then
        design_rel="$changed"
      fi
      ;;
  esac
  if [ "$design_rel" != - ]; then
    case "$design_rel" in docs/design/[0-9][0-9][0-9][0-9]-*.md) ;; *) return 1 ;; esac
    design_status=$(review_design_status "$root/$design_rel") || return 1
    case "$design_status" in draft|approved|frozen|abandoned) ;; *) return 1 ;; esac
  fi
  paths=$( {
    git -C "$root" diff --no-renames --name-only HEAD 2>/dev/null
    git -C "$root" ls-files --others --exclude-standard 2>/dev/null
  } | awk 'NF && !seen[$0]++') || return 1
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    [ "$path" = "$design_rel" ] && continue
    case "$path" in
      docs/reference/testing.md) ;;
      docs/decisions/README.md) ;;
      docs/decisions/[0-9][0-9][0-9][0-9]-*.md)
        declared=$(review_decision_subject "$root/$path") || return 1
        case "$declared" in
          harness) harness_seen=1 ;;
          "") product_seen=1 ;;
          *) return 1 ;;
        esac ;;
      core/*|.codex/*|.agents/*|.githooks/*|.github/*|.gitignore|CLAUDE.md)
        harness_seen=1 ;;
      *) product_seen=1 ;;
    esac
  done <<EOF
$paths
EOF
  if [ "$product_seen" = 0 ] && [ "$harness_seen" = 1 ]; then
    subject=harness
  fi
  printf '%s\t%s\t%s' "$subject" "$design_rel" "$design_status"
}

review_subject_kind() {
  review_subject_resolve "$1" "${2:--}" | cut -f1
}

# Series identity is immutable, but classifier v1 incorrectly treated mixed harness/testing
# changes as product work. Reusing an affected open series appends one narrow correction rather
# than rewriting its evidence or resetting its review window.
review_series_subject_effective() {
  local root="$1" series="$2" dir sjson stored correction
  dir=$(review_series_dir "$root" "$series") || return 1
  sjson="$dir/series.json"
  [ -f "$sjson" ] && [ ! -L "$sjson" ] || return 1
  stored=$(jq -er '.subjectKind | select(.=="harness" or .=="product")' "$sjson") || return 1
  correction="$dir/subject-correction.json"
  if [ -e "$correction" ] || [ -L "$correction" ]; then
    [ -f "$correction" ] && [ ! -L "$correction" ] || return 1
    jq -e --arg from "$stored" '
      .version==1 and .from==$from and .to=="harness" and
      .reason=="subject-classifier-v2"
    ' "$correction" >/dev/null 2>&1 || return 1
    printf 'harness'
    return
  fi
  printf '%s' "$stored"
}

review_series_subject_reconcile() {
  local root="$1" series="$2" key="$3" dir sjson stored version
  local candidate design_rel design_status stored_design stored_status correction tmp
  dir=$(review_series_dir "$root" "$series") || return 1
  sjson="$dir/series.json"
  [ -f "$sjson" ] && [ ! -L "$sjson" ] || return 1
  correction="$dir/subject-correction.json"
  if [ -e "$correction" ] || [ -L "$correction" ]; then
    review_series_subject_effective "$root" "$series"
    return
  fi
  stored=$(jq -er '.subjectKind | select(.=="harness" or .=="product")' "$sjson") || return 1
  version=$(jq -r '.subjectClassifierVersion // 1' "$sjson") || return 1
  case "$version" in
    1) ;;
    2) printf '%s' "$stored"; return ;;
    *) return 1 ;;
  esac
  [ "$stored" = product ] || { printf '%s' "$stored"; return; }
  IFS=$'\t' read -r candidate design_rel design_status <<EOF
$(review_subject_resolve "$root" "$key")
EOF
  [ "$candidate" = harness ] || { printf '%s' "$stored"; return; }
  stored_design=$(jq -r '.designPath // "-"' "$sjson") || return 1
  stored_status=$(jq -r '.designStatus // "-"' "$sjson") || return 1
  [ "$design_rel" = "$stored_design" ] && [ "$design_status" = "$stored_status" ] || return 1
  tmp="$dir/.subject-correction.$$"
  jq -cn --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '
    {version:1,from:"product",to:"harness",reason:"subject-classifier-v2",recordedAt:$at}
  ' > "$tmp" && ln "$tmp" "$correction" 2>/dev/null
  if [ $? -ne 0 ]; then
    rm -f "$tmp"
    [ -f "$correction" ] && [ ! -L "$correction" ] || return 1
  else
    rm -f "$tmp"
  fi
  review_series_subject_effective "$root" "$series"
}

review_finding_blocks() {
  local attempt="$1" severity="${2:-}" selected_lines finding_lines
  [ -f "$attempt/raw.md" ] && [ ! -L "$attempt/raw.md" ] \
    && [ -f "$attempt/completion.json" ] && [ ! -L "$attempt/completion.json" ] || return 1
  case "$severity" in ''|blocking|concern|scope) ;; *) return 1 ;; esac
  selected_lines=$(jq -r --arg severity "$severity" \
    '[.findings[] | select($severity=="" or .severity==$severity) | .line] | join(",")' \
    "$attempt/completion.json") || return 1
  finding_lines=$(jq -r '[.findings[].line] | join(",")' "$attempt/completion.json") || return 1
  [ -n "$selected_lines" ] || return 1
  awk -v selected_csv="$selected_lines" -v finding_csv="$finding_lines" '
    BEGIN {
      n=split(selected_csv,a,","); for (i=1;i<=n;i++) selected[a[i]]=1
      n=split(finding_csv,a,","); for (i=1;i<=n;i++) finding[a[i]]=1
    }
    {
      if (selected[NR]) { if (printed) print ""; active=1; printed=1; print; next }
      if (active && (finding[NR] || $0 ~ /^[[:space:]]*##[[:space:]]/ \
          || toupper($0) ~ /^[[:space:]]*VERDICT[[:space:]]*:/)) active=0
      if (active) print
    }
  ' "$attempt/raw.md"
}

review_scope_blocks() { review_finding_blocks "$1" scope; }

# Append one generated entry inside a Markdown section without multiplying section headings.
review_section_append_file() {
  local file="$1" heading="$2" addition="$3" tmp
  [ -f "$file" ] && [ ! -L "$file" ] && [ -f "$addition" ] && [ ! -L "$addition" ] || return 1
  tmp="$file.section.$$"
  cp -p "$file" "$tmp" || return 1
  awk -v heading="$heading" -v addition="$addition" '
    function add(line) {
      if (added) return
      print ""
      while ((getline line < addition) > 0) print line
      close(addition)
      print ""
      added=1
    }
    $0 == heading && !seen { seen=1; print; next }
    seen && !added && /^## / { add(); seen=0; print; next }
    { print }
    END {
      if (seen && !added) add()
      else if (!seen && !added) { print ""; print heading; add() }
    }
  ' "$file" > "$tmp" || { rm -f "$tmp"; return 1; }
  mv "$tmp" "$file"
}

review_scope_intent_prepare() {
  local root="$1" attempt="$2" action="$3" destination="$4" after="$5" source="$6" original="$7"
  local rel current other before_sha after_sha dir tmp
  rel=$(review_tracked_target_relative "$root" "$destination") || return 1
  [ -f "$after" ] && [ ! -L "$after" ] || return 1
  current=$(CLAUDE_PROJECT_DIR="$root" "${OH_HOME:-$root}/core/scripts/tree-digest.sh" 2>/dev/null) || return 1
  [ "$current" = "$original" ] || return 1
  other=$(review_tree_without_path "$root" "$rel") || return 1
  before_sha=$(review_workflow_file_hash "$destination") || return 1
  after_sha=$(review_workflow_file_hash "$after") || return 1
  dir="$attempt/scope-intent"; mkdir -p "$dir" || return 1
  [ ! -L "$dir" ] || return 1
  tmp="$dir/.before.$$"; cp -p "$destination" "$tmp" && mv "$tmp" "$dir/before" \
    || { rm -f "$tmp"; return 1; }
  tmp="$dir/.after.$$"; cp -p "$after" "$tmp" && mv "$tmp" "$dir/after" \
    || { rm -f "$tmp"; return 1; }
  tmp="$dir/.intent.$$"
  jq -cn --arg action "$action" --arg destination "$rel" --arg source "$source" \
    --arg original "$original" --arg other "$other" --arg before "$before_sha" --arg after "$after_sha" \
    --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '
      {version:1,action:$action,destination:$destination,source:$source,originalTree:$original,
       otherTree:$other,beforeSha256:$before,afterSha256:$after,recordedAt:$at}
    ' > "$tmp" && ln "$tmp" "$dir/intent.json" 2>/dev/null \
    || { rm -f "$tmp"; return 1; }
  rm -f "$tmp"
}

review_scope_intent_apply() {
  local root="$1" attempt="$2" action="$3" destination="$4" source="$5" original="$6"
  local rel dir other current tmp
  rel=$(review_tracked_target_relative "$root" "$destination") || return 1
  dir="$attempt/scope-intent"
  [ -f "$dir/intent.json" ] && [ ! -L "$dir/intent.json" ] \
    && [ -f "$dir/before" ] && [ ! -L "$dir/before" ] \
    && [ -f "$dir/after" ] && [ ! -L "$dir/after" ] || return 1
  jq -e --arg action "$action" --arg destination "$rel" --arg source "$source" --arg original "$original" '
    .version==1 and .action==$action and .destination==$destination and
    .source==$source and .originalTree==$original
  ' "$dir/intent.json" >/dev/null 2>&1 || return 1
  [ "$(review_workflow_file_hash "$dir/before")" = "$(jq -r '.beforeSha256' "$dir/intent.json")" ] \
    && [ "$(review_workflow_file_hash "$dir/after")" = "$(jq -r '.afterSha256' "$dir/intent.json")" ] \
    || return 1
  current=$(CLAUDE_PROJECT_DIR="$root" "${OH_HOME:-$root}/core/scripts/tree-digest.sh" 2>/dev/null) || return 1
  if [ "$current" = "$original" ] && cmp -s "$destination" "$dir/before"; then
    tmp="$dir/.publish.$$"
    cp -p "$dir/after" "$tmp" && mv "$tmp" "$destination" || { rm -f "$tmp"; return 1; }
  elif cmp -s "$destination" "$dir/after"; then
    other=$(review_tree_without_path "$root" "$rel") || return 1
    [ "$other" = "$(jq -r '.otherTree' "$dir/intent.json")" ] || return 1
  else
    return 1
  fi
  CLAUDE_PROJECT_DIR="$root" "${OH_HOME:-$root}/core/scripts/tree-digest.sh" 2>/dev/null
}

review_pr_resolution_publish() {
  local root="$1" attempt="$2" action="$3" choice="$4" destination="$5" result="$6"
  local series id findings original tmp file
  review_attempt_path_valid "$root" "$attempt" || return 1
  review_attempt_validate_start "$root" "$attempt" || return 1
  case "$action" in accept-concerns|route-scope|dismiss-scope) ;; *) return 1 ;; esac
  [ -n "$choice" ] && [ -n "$destination" ] || return 1
  printf '%s' "$result" | grep -Eq '^[0-9a-f]{16}$' || return 1
  findings=$(review_finding_blocks "$attempt") || return 1
  [ -n "$findings" ] || return 1
  series=$(jq -er '.seriesId' "$attempt/start.json") || return 1
  original=$(jq -er '.tree' "$attempt/start.json") || return 1
  id=$(review_workflow_hash "$series"$'\n'"${attempt##*/}"$'\n'"$findings"$'\n'"$action"$'\n'"$choice"$'\n'"$destination") || return 1
  file="$attempt/pr-resolution.json"
  if [ -e "$file" ] || [ -L "$file" ]; then
    [ -f "$file" ] && [ ! -L "$file" ] || return 1
    jq -e --arg id "$id" --arg action "$action" --arg choice "$choice" \
      --arg destination "$destination" --arg original "$original" --arg result "$result" \
      --arg findings "$findings" '
        .version==1 and .id==$id and .action==$action and .choice==$choice and
        .destination==$destination and .originalTree==$original and .resultTree==$result and
        .findingText==$findings
      ' "$file" >/dev/null 2>&1 || return 1
    printf '%s' "$id"
    return
  fi
  tmp="$attempt/.pr-resolution.$$"
  jq -cn --arg id "$id" --arg action "$action" --arg choice "$choice" \
    --arg destination "$destination" --arg original "$original" --arg result "$result" \
    --arg findings "$findings" --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '
      {version:1,id:$id,action:$action,choice:$choice,destination:$destination,
       originalTree:$original,resultTree:$result,findingText:$findings,recordedAt:$at}
    ' > "$tmp" && ln "$tmp" "$file" 2>/dev/null || { rm -f "$tmp"; return 1; }
  rm -f "$tmp"
  printf '%s' "$id"
}

review_pr_resolution_validate() {
  local root="$1" attempt="$2" file findings series expected
  file="$attempt/pr-resolution.json"
  [ -f "$file" ] && [ ! -L "$file" ] || return 1
  review_attempt_validate_start "$root" "$attempt" || return 1
  jq -e '
    .version==1 and (.id|test("^[0-9a-f]{64}$")) and
    (.action=="accept-concerns" or .action=="route-scope" or .action=="dismiss-scope") and
    (.choice|type=="string" and length>0) and (.destination|type=="string" and length>0) and
    (.originalTree|test("^[0-9a-f]{16}$")) and (.resultTree|test("^[0-9a-f]{16}$")) and
    (.findingText|type=="string" and length>0)
  ' "$file" >/dev/null 2>&1 || return 1
  [ "$(jq -r '.originalTree' "$file")" = "$(jq -r '.tree' "$attempt/start.json")" ] || return 1
  findings=$(review_finding_blocks "$attempt") || return 1
  [ "$findings" = "$(jq -r '.findingText' "$file")" ] || return 1
  series=$(jq -er '.seriesId' "$attempt/start.json") || return 1
  expected=$(review_workflow_hash "$series"$'\n'"${attempt##*/}"$'\n'"$findings"$'\n'"$(jq -r '.action' "$file")"$'\n'"$(jq -r '.choice' "$file")"$'\n'"$(jq -r '.destination' "$file")") || return 1
  [ "$expected" = "$(jq -r '.id' "$file")" ]
}

review_scope_pr_resolution_ensure() {
  local root="$1" attempt="$2" transition status action choice destination result id linked
  transition="$attempt/scope-transition.json"
  [ -f "$attempt/resolution.json" ] && [ ! -L "$attempt/resolution.json" ] || return 1
  [ -f "$transition" ] && [ ! -L "$transition" ] || return 1
  status=$(jq -er '.status' "$transition") || return 1
  action=$(jq -er '.action' "$transition") || return 1
  choice=$(jq -er '.choice' "$attempt/resolution.json") || return 1
  result=$(jq -er '.resultTree | select(test("^[0-9a-f]{16}$"))' "$transition") || return 1
  case "$status" in
    applied)
      destination="repository:$(jq -er '.destination | select(type=="string" and length>0)' "$transition")" ;;
    pr-required) destination=pr ;;
    human-route-required)
      [ -f "$attempt/scope-destination.json" ] && [ ! -L "$attempt/scope-destination.json" ] || return 1
      destination=$(jq -er 'select(.version==1 and .status=="applied" and .kind=="github-issue") |
        .issueUrl | select(type=="string" and length>0)' "$attempt/scope-destination.json") || return 1 ;;
    *) return 1 ;;
  esac
  id=$(review_pr_resolution_publish "$root" "$attempt" "$action" "$choice" "$destination" "$result") || return 1
  linked=$(jq -r '.prResolutionId // empty' "$transition") || return 1
  [ -z "$linked" ] || [ "$linked" = "$id" ] || return 1
  if [ "$status" = human-route-required ]; then
    [ "$(jq -r '.prResolutionId // empty' "$attempt/scope-destination.json")" = "$id" ] || return 1
  fi
  printf '%s' "$id"
}

review_scope_apply() {
  local root="$1" attempt="$2" action="$3" original destination status key status_value subject
  local tmp transition result blocks heading outcome source choice entry disposition_source series sjson design_rel
  local pr_id existing_status pr_destination
  review_attempt_path_valid "$root" "$attempt" || return 1
  review_attempt_validate_start "$root" "$attempt" || return 1
  case "$action" in route-scope|dismiss-scope) ;; *) return 1 ;; esac
  outcome=$(jq -r '.outcome' "$attempt/completion.json" 2>/dev/null) || return 1
  [ "$(jq -r '.status' "$attempt/completion.json" 2>/dev/null)" = completed ] || return 1
  source=human
  if [ -f "$attempt/resolution.json" ] && [ ! -L "$attempt/resolution.json" ]; then
    choice=$(jq -r '.choice' "$attempt/resolution.json" 2>/dev/null) || return 1
    case "$choice:$action" in
      *route-scope:route-scope|*dismiss-scope:dismiss-scope) ;;
      *) return 1 ;;
    esac
  else
    case "$outcome:$action" in
      blocking+scope:route-scope|blocking+concern+scope:route-scope) source=required-by-policy ;;
      *) return 1 ;;
    esac
  fi
  original=$(jq -r '.tree' "$attempt/start.json") || return 1
  if [ -e "$attempt/scope-transition.json" ] || [ -L "$attempt/scope-transition.json" ]; then
    [ -f "$attempt/scope-transition.json" ] && [ ! -L "$attempt/scope-transition.json" ] || return 1
    [ "$(jq -r '.action' "$attempt/scope-transition.json" 2>/dev/null)" = "$action" ] || return 1
    existing_status=$(jq -r '.status' "$attempt/scope-transition.json" 2>/dev/null) || return 1
    case "$existing_status" in
      applied|pr-required)
        review_scope_terminal "$attempt" >/dev/null || return 1
        if [ -f "$attempt/resolution.json" ]; then
          review_scope_pr_resolution_ensure "$root" "$attempt" >/dev/null || return 1
        fi
        ;;
      *) return 1 ;;
    esac
    return
  fi
  key=$(jq -r '.roundKey' "$attempt/start.json") || return 1
  series=$(jq -er '.seriesId' "$attempt/start.json") || return 1
  sjson="$(review_series_dir "$root" "$series")/series.json"
  [ -f "$sjson" ] && [ ! -L "$sjson" ] || return 1
  subject=$(review_series_subject_effective "$root" "$series") || return 1
  design_rel=$(jq -r '.designPath // "-"' "$sjson") || return 1
  status_value=$(jq -r '.designStatus // "-"' "$sjson") || return 1
  if [ -z "$subject" ]; then
    IFS=$'\t' read -r subject design_rel status_value <<EOF
$(review_subject_resolve "$root" "$key")
EOF
  fi
  case "$subject" in harness|product) ;; *) return 1 ;; esac
  if [ "$design_rel" != - ]; then
    case "$design_rel" in docs/design/[0-9][0-9][0-9][0-9]-*.md) ;; *) return 1 ;; esac
    [ "$(review_design_status "$root/$design_rel")" = "$status_value" ] || return 1
  fi
  destination=""; status=blocked
  case "$status_value" in
    draft|approved)
      [ "$design_rel" != - ] || return 1
      destination="$root/$design_rel"; status=applied ;;
    frozen|abandoned|-)
      if [ "$subject" = harness ]; then
        if [ -f "$root/.oh/project.json" ]; then
          if [ "$action" = dismiss-scope ]; then status=pr-required; else status=human-route-required; fi
        else destination="$root/core/BACKLOG.md"; status=applied
        fi
      elif [ "$action" = dismiss-scope ]; then status=pr-required
      else status=human-route-required
      fi ;;
    *) return 1 ;;
  esac
  if [ "$status" = applied ]; then
    if [ ! -f "$attempt/scope-intent/intent.json" ]; then
      [ "$(CLAUDE_PROJECT_DIR="$root" "${OH_HOME:-$root}/core/scripts/tree-digest.sh" 2>/dev/null)" = "$original" ] || return 1
      blocks=$(review_scope_blocks "$attempt") || return 1
      [ -n "$blocks" ] || return 1
      heading='## Open review scope'
      [ "$action" = dismiss-scope ] && heading='## Scope decisions'
      case "$destination" in */core/BACKLOG.md)
        [ "$action" = route-scope ] && heading='## Open' || heading='## Dismissed' ;;
      esac
      entry="$attempt/.scope-entry.$$"
      disposition_source='human choice'
      [ "$source" = required-by-policy ] && disposition_source='required by blocker-plus-scope policy'
      {
        printf '%s\n' "$blocks"
        printf '\nReview attempt: `%s`\nDisposition: `%s` (%s)\n' \
          "$(jq -r '.id' "$attempt/start.json")" "$action" "$disposition_source"
      } > "$entry" || { rm -f "$entry"; return 1; }
      tmp="$attempt/.scope-after.$$"
      cp -p "$destination" "$tmp" \
        && review_section_append_file "$tmp" "$heading" "$entry" \
        && review_scope_intent_prepare "$root" "$attempt" "$action" "$destination" "$tmp" "$source" "$original" \
        || { rm -f "$entry" "$tmp"; return 1; }
      rm -f "$entry" "$tmp"
    fi
    result=$(review_scope_intent_apply "$root" "$attempt" "$action" "$destination" "$source" "$original") || return 1
  else
    [ "$(CLAUDE_PROJECT_DIR="$root" "${OH_HOME:-$root}/core/scripts/tree-digest.sh" 2>/dev/null)" = "$original" ] || return 1
    result="$original"
  fi
  pr_id=""
  if [ -f "$attempt/resolution.json" ] && [ ! -L "$attempt/resolution.json" ]; then
    [ -n "$choice" ] || choice=$(jq -er '.choice' "$attempt/resolution.json") || return 1
    case "$status" in
      applied) pr_destination="repository:${destination#"$root"/}" ;;
      pr-required) pr_destination=pr ;;
      human-route-required) pr_destination="" ;;
      *) return 1 ;;
    esac
    if [ -n "$pr_destination" ]; then
      pr_id=$(review_pr_resolution_publish "$root" "$attempt" "$action" "$choice" "$pr_destination" "$result") || return 1
    fi
  fi
  transition="$attempt/.scope-transition.$$"
  jq -cn --arg action "$action" --arg source "$source" --arg status "$status" --arg destination "${destination#"$root"/}" \
    --arg original "$original" --arg result "$result" --arg prId "$pr_id" --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{version:1,action:$action,source:$source,status:$status,destination:(if $destination=="" then null else $destination end),
      originalTree:$original,resultTree:$result,
      prResolutionId:(if $prId=="" then null else $prId end),recordedAt:$at}' > "$transition" \
    && ln "$transition" "$attempt/scope-transition.json" 2>/dev/null || { rm -f "$transition"; return 1; }
  rm -f "$transition"
  case "$status" in
    applied|pr-required)
      if [ -f "$attempt/resolution.json" ]; then
        review_scope_pr_resolution_ensure "$root" "$attempt" >/dev/null || return 1
      fi
      return 0 ;;
    *) return 1 ;;
  esac
}

review_attempt_disposition() {
  local attempt="$1" final="$2" status outcome choice
  [ -f "$attempt/completion.json" ] && [ ! -L "$attempt/completion.json" ] || return 1
  status=$(jq -er '.status' "$attempt/completion.json") || return 1
  outcome=$(jq -er '.outcome' "$attempt/completion.json") || return 1
  if [ "$attempt" = "$final" ]; then
    printf 'authorized-final'
    return
  fi
  if [ -f "$attempt/resolution.json" ] && [ ! -L "$attempt/resolution.json" ]; then
    choice=$(jq -er '.choice' "$attempt/resolution.json") || return 1
    case "$choice" in
      fix-concerns|fix-concerns+route-scope|fix-concerns+dismiss-scope)
        printf 'corrected-before-next-review' ;;
      accept-concerns|accept-concerns+route-scope|accept-concerns+dismiss-scope)
        printf 'accepted-by-human' ;;
      route-scope|dismiss-scope|review-again) printf '%s' "$choice" ;;
      *) return 1 ;;
    esac
    return
  fi
  case "$status:$outcome" in
    completed:blocking|completed:blocking+concern|completed:blocking+scope|completed:blocking+concern+scope)
      printf 'corrected-before-next-review' ;;
    completed:clean) printf 'superseded-by-later-review' ;;
    binding-failed:*|interrupted:*|empty:*) printf '%s' "$status" ;;
    *) return 1 ;;
  esac
}

review_series_history_render() {
  local root="$1" series="$2" final="$3" attempts entry status outcome elapsed raw_sha disposition findings count=0
  review_attempt_path_valid "$root" "$final" || return 1
  [ "$(jq -er '.seriesId' "$final/start.json")" = "$series" ] || return 1
  attempts=$(review_attempts_dir "$root" "$series")
  [ -d "$attempts" ] && [ ! -L "$attempts" ] || return 1
  printf '%s\n' '## Review history'
  for entry in "$attempts"/a-*; do
    [ -d "$entry" ] || continue
    review_attempt_unadmitted_dir "$root" "$entry" && continue
    review_attempt_path_valid "$root" "$entry" || return 1
    review_attempt_validate_start "$root" "$entry" || return 1
    [ -f "$entry/completion.json" ] && [ ! -L "$entry/completion.json" ] || return 1
    status=$(jq -er '.status' "$entry/completion.json") || return 1
    outcome=$(jq -er '.outcome' "$entry/completion.json") || return 1
    elapsed=$(jq -er '.elapsedSeconds | select(type=="number" and .>=0 and floor==.)' "$entry/completion.json") || return 1
    raw_sha=$(jq -r '.rawSha256 // "none"' "$entry/completion.json") || return 1
    case "$raw_sha" in none) ;; *) printf '%s' "$raw_sha" | grep -Eq '^[0-9a-f]{64}$' || return 1 ;; esac
    disposition=$(review_attempt_disposition "$entry" "$final") || return 1
    findings=$(review_finding_blocks "$entry" 2>/dev/null || true)
    printf '\n<!-- review-attempt:%s:start -->\n### %s\n\n' "${entry##*/}" "${entry##*/}"
    printf 'Status: %s\nSemantic outcome: %s\nElapsed seconds: %s\nDisposition: %s\nRaw output SHA-256: %s\n\n' \
      "$status" "$outcome" "$elapsed" "$disposition" "$raw_sha"
    if [ -n "$findings" ]; then
      printf '%s\n\n' 'Raw findings:'
      printf '%s\n' "$findings" | sed 's/^/> /'
    else
      printf '%s\n' 'Raw findings: none.'
    fi
    printf '<!-- review-attempt:%s:end -->\n' "${entry##*/}"
    count=$((count + 1))
    [ "$entry" != "$final" ] || break
  done
  [ "$count" -gt 0 ] && [ "$entry" = "$final" ]
}

review_history_section_extract() {
  local file="$1"
  [ -f "$file" ] && [ ! -L "$file" ] || return 1
  [ "$(grep -cFx '<!-- review-history:start -->' "$file" 2>/dev/null)" = 1 ] || return 1
  [ "$(grep -cFx '<!-- review-history:end -->' "$file" 2>/dev/null)" = 1 ] || return 1
  awk '
    $0=="<!-- review-history:start -->" {active=1; next}
    $0=="<!-- review-history:end -->" {if (!active) exit 1; active=0; done=1; next}
    active {print}
    END {if (!done || active) exit 1}
  ' "$file"
}

review_pr_resolutions_render() {
  local root="$1" branch="$2" only_series="${3:-}" only_attempt="${4:-}"
  local base series attempt blocks id action choice destination count=0
  base="$(review_series_state_root "$root")/series"; [ -d "$base" ] || return 1
  for series in "$base"/s-*; do
    [ -z "$only_series" ] || [ "${series##*/}" = "$only_series" ] || continue
    [ -f "$series/series.json" ] && [ "$(jq -r '.branch' "$series/series.json" 2>/dev/null)" = "$branch" ] || continue
    review_series_incarnation_matches "$root" "$series" || continue
    for attempt in "$series/attempts"/a-*; do
      [ -z "$only_attempt" ] || [ "${attempt##*/}" = "$only_attempt" ] || continue
      [ -f "$attempt/pr-resolution.json" ] && [ ! -L "$attempt/pr-resolution.json" ] || continue
      review_pr_resolution_validate "$root" "$attempt" || return 1
      id=$(jq -er '.id' "$attempt/pr-resolution.json") || return 1
      blocks=$(jq -er '.findingText' "$attempt/pr-resolution.json") || return 1
      action=$(jq -er '.action' "$attempt/pr-resolution.json") || return 1
      choice=$(jq -er '.choice' "$attempt/pr-resolution.json") || return 1
      destination=$(jq -er '.destination' "$attempt/pr-resolution.json") || return 1
      if [ "$count" = 0 ]; then printf '%s\n' '## Review resolutions'; fi
      printf '\n### %s / %s\n\n<!-- review-resolution:%s:finding:start -->\n%s\n<!-- review-resolution:%s:finding:end -->\n\nReview-Series: %s\nReview-Attempt: %s\nReview-Action: %s\nReview-Choice: %s\nReview-Destination: %s\nReview-Resolution: %s\n' \
        "${series##*/}" "${attempt##*/}" "$id" "$blocks" "$id" \
        "${series##*/}" "${attempt##*/}" "$action" "$choice" "$destination" "$id"
      count=$((count + 1))
    done
  done
  return 0
}

review_pr_resolution_section_validate() {
  local body="$1" id count finding series attempt action choice destination expected
  [ -f "$body" ] && [ ! -L "$body" ] || return 1
  [ "$(grep -c '^## Review resolutions$' "$body" 2>/dev/null)" = 1 ] || return 1
  shift
  [ "$#" -gt 0 ] || return 1
  for id in "$@"; do
    printf '%s' "$id" | grep -Eq '^[0-9a-f]{64}$' || return 1
    count=$(grep -cFx "Review-Resolution: $id" "$body" 2>/dev/null) || return 1
    [ "$count" = 1 ] || return 1
    [ "$(grep -cFx "<!-- review-resolution:$id:finding:start -->" "$body")" = 1 ] \
      && [ "$(grep -cFx "<!-- review-resolution:$id:finding:end -->" "$body")" = 1 ] || return 1
    finding=$(awk -v start="<!-- review-resolution:$id:finding:start -->" \
      -v end="<!-- review-resolution:$id:finding:end -->" '
        $0==start {active=1; next} $0==end {active=0; done=1; next} active {print}
        END {if (!done) exit 1}
      ' "$body") || return 1
    series=$(awk -v end="<!-- review-resolution:$id:finding:end -->" '
      $0==end {seen=1; next} seen && /^Review-Series: / {sub(/^Review-Series: /,""); print; exit}
    ' "$body") || return 1
    attempt=$(awk -v end="<!-- review-resolution:$id:finding:end -->" '
      $0==end {seen=1; next} seen && /^Review-Attempt: / {sub(/^Review-Attempt: /,""); print; exit}
    ' "$body") || return 1
    action=$(awk -v end="<!-- review-resolution:$id:finding:end -->" '
      $0==end {seen=1; next} seen && /^Review-Action: / {sub(/^Review-Action: /,""); print; exit}
    ' "$body") || return 1
    choice=$(awk -v end="<!-- review-resolution:$id:finding:end -->" '
      $0==end {seen=1; next} seen && /^Review-Choice: / {sub(/^Review-Choice: /,""); print; exit}
    ' "$body") || return 1
    destination=$(awk -v end="<!-- review-resolution:$id:finding:end -->" '
      $0==end {seen=1; next} seen && /^Review-Destination: / {sub(/^Review-Destination: /,""); print; exit}
    ' "$body") || return 1
    case "$action" in accept-concerns|route-scope|dismiss-scope) ;; *) return 1 ;; esac
    printf '%s' "$series" | grep -Eq '^s-[0-9]{10}-[0-9a-f]{24}$' || return 1
    printf '%s' "$attempt" | grep -Eq '^a-[0-9]{6}$' || return 1
    [ -n "$choice" ] || return 1
    case "$destination" in
      reviewed-tree|pr|repository:docs/design/[0-9][0-9][0-9][0-9]-*.md|repository:core/BACKLOG.md) ;;
      https://*/*/issues/[1-9]*) ;;
      *) return 1 ;;
    esac
    expected=$(review_workflow_hash "$series"$'\n'"$attempt"$'\n'"$finding"$'\n'"$action"$'\n'"$choice"$'\n'"$destination") || return 1
    [ "$expected" = "$id" ] || return 1
  done
}

review_pr_resolution_ids_match() {
  local body="$1" body_ids expected_ids all_count valid_count id
  shift
  [ -f "$body" ] && [ ! -L "$body" ] || return 1
  all_count=$(grep -c '^Review-Resolution:' "$body" 2>/dev/null || true)
  valid_count=$(grep -cE '^Review-Resolution: [0-9a-f]{64}$' "$body" 2>/dev/null || true)
  [ "$all_count" = "$valid_count" ] || return 1
  body_ids=$(sed -n 's/^Review-Resolution: \([0-9a-f]\{64\}\)$/\1/p' "$body" | sort -u) || return 1
  expected_ids=$(for id in "$@"; do
    printf '%s' "$id" | grep -Eq '^[0-9a-f]{64}$' || exit 1
    printf '%s\n' "$id"
  done | sort -u) || return 1
  [ "$body_ids" = "$expected_ids" ] || return 1
  if [ -n "$body_ids" ]; then
    # Deliberately split the newline-separated hexadecimal IDs.
    review_pr_resolution_section_validate "$body" $body_ids
  fi
}

review_attempt_pr_resolution_id() {
  local root="$1" attempt="$2" file
  file="$attempt/pr-resolution.json"
  review_pr_resolution_validate "$root" "$attempt" || return 1
  jq -er '.id | select(test("^[0-9a-f]{64}$"))' "$file"
}

review_branch_pending_resolution_ids() {
  local root="$1" branch="$2" base series attempt id history
  base="$(review_series_state_root "$root")/series"; [ -d "$base" ] || return 0
  history=$(git -C "$root" log --format=%B HEAD 2>/dev/null || true)
  for series in "$base"/s-*; do
    [ -f "$series/series.json" ] && [ "$(jq -r '.branch' "$series/series.json" 2>/dev/null)" = "$branch" ] || continue
    review_series_incarnation_matches "$root" "$series" || continue
    for attempt in "$series/attempts"/a-*; do
      [ -d "$attempt" ] || continue
      id=$(review_attempt_pr_resolution_id "$root" "$attempt" 2>/dev/null) || continue
      printf '%s\n' "$history" | grep -qFx "Review-Resolution: $id" && continue
      printf '%s\n' "$id"
    done
  done
}

review_pr_handoff_validate() {
  local body="$1" expected_branch="${2:-}" expected_incarnation="${3:-}" expected_head="${4:-}"
  local series attempt branch incarnation tree result_tree parent git_tree head outcome preparation handoff
  local ids expected expected_preparation valid_count all_count history history_sha
  [ -f "$body" ] && [ ! -L "$body" ] || return 1
  [ "$(grep -c '^## Review resolutions$' "$body" 2>/dev/null)" = 1 ] || return 1
  for label in Review-Handoff-Series Review-Handoff-Attempt Review-Branch Review-Incarnation \
    Review-Tree Review-Result-Tree Review-Parent Review-Git-Tree Review-Head Review-Outcome \
    Review-History-SHA256 Review-Preparation Review-Handoff; do
    [ "$(grep -c "^$label: " "$body" 2>/dev/null)" = 1 ] || return 1
  done
  series=$(sed -n 's/^Review-Handoff-Series: //p' "$body")
  attempt=$(sed -n 's/^Review-Handoff-Attempt: //p' "$body")
  branch=$(sed -n 's/^Review-Branch: //p' "$body")
  incarnation=$(sed -n 's/^Review-Incarnation: //p' "$body")
  tree=$(sed -n 's/^Review-Tree: //p' "$body")
  result_tree=$(sed -n 's/^Review-Result-Tree: //p' "$body")
  parent=$(sed -n 's/^Review-Parent: //p' "$body")
  git_tree=$(sed -n 's/^Review-Git-Tree: //p' "$body")
  head=$(sed -n 's/^Review-Head: //p' "$body")
  outcome=$(sed -n 's/^Review-Outcome: //p' "$body")
  history_sha=$(sed -n 's/^Review-History-SHA256: //p' "$body")
  preparation=$(sed -n 's/^Review-Preparation: //p' "$body")
  handoff=$(sed -n 's/^Review-Handoff: //p' "$body")
  printf '%s' "$series" | grep -Eq '^s-[0-9]{10}-[0-9a-f]{24}$' || return 1
  printf '%s' "$attempt" | grep -Eq '^a-[0-9]{6}$' || return 1
  git check-ref-format --branch "$branch" >/dev/null 2>&1 || return 1
  printf '%s' "$incarnation" | grep -Eq '^[0-9a-f]{64}$' || return 1
  [ -z "$expected_branch" ] || [ "$branch" = "$expected_branch" ] || return 1
  [ -z "$expected_incarnation" ] || [ "$incarnation" = "$expected_incarnation" ] || return 1
  [ -z "$expected_head" ] || [ "$head" = "$expected_head" ] || return 1
  printf '%s' "$tree" | grep -Eq '^[0-9a-f]{16}$' || return 1
  printf '%s' "$result_tree" | grep -Eq '^[0-9a-f]{16}$' || return 1
  printf '%s' "$parent" | grep -Eq '^[0-9a-f]{40}([0-9a-f]{24})?$' || return 1
  printf '%s' "$git_tree" | grep -Eq '^[0-9a-f]{40}([0-9a-f]{24})?$' || return 1
  printf '%s' "$head" | grep -Eq '^[0-9a-f]{40}([0-9a-f]{24})?$' || return 1
  case "$outcome" in clean|concern|scope|concern+scope) ;; *) return 1 ;; esac
  printf '%s' "$history_sha" | grep -Eq '^[0-9a-f]{64}$' || return 1
  printf '%s' "$preparation" | grep -Eq '^[0-9a-f]{64}$' || return 1
  printf '%s' "$handoff" | grep -Eq '^[0-9a-f]{64}$' || return 1
  history=$(review_history_section_extract "$body") || return 1
  [ "$(review_workflow_hash "$history")" = "$history_sha" ] || return 1
  if grep -q '^Review-Resolution:' "$body"; then
    all_count=$(grep -c '^Review-Resolution:' "$body" 2>/dev/null) || return 1
    valid_count=$(grep -cE '^Review-Resolution: [0-9a-f]{64}$' "$body" 2>/dev/null) || return 1
    [ "$all_count" = "$valid_count" ] || return 1
    ids=$(sed -n 's/^Review-Resolution: \([0-9a-f]\{64\}\)$/\1/p' "$body" | awk '!seen[$0]++') || return 1
    [ "$(printf '%s\n' "$ids" | awk 'NF{n++} END{print n+0}')" = "$valid_count" ] || return 1
    # Deliberately split the newline-separated hexadecimal IDs.
    review_pr_resolution_section_validate "$body" $ids || return 1
  else
    [ "$(grep -cFx 'No human review resolution was required.' "$body" 2>/dev/null)" = 1 ] || return 1
    ids=""
  fi
  expected_preparation=$(review_workflow_hash "$series"$'\n'"$attempt"$'\n'"$branch"$'\n'"$incarnation"$'\n' \
    "$tree"$'\n'"$result_tree"$'\n'"$parent"$'\n'"$git_tree"$'\n'"$outcome"$'\n'"$history_sha"$'\n'"$ids") || return 1
  [ "$expected_preparation" = "$preparation" ] || return 1
  expected=$(review_workflow_hash "$preparation"$'\n'"$head") || return 1
  [ "$expected" = "$handoff" ]
}

review_index_tree_ready() {
  local root="$1" untracked git_tree
  git -C "$root" diff --quiet --no-ext-diff -- . || return 1
  untracked=$(git -C "$root" ls-files --others --exclude-standard -- . 2>/dev/null) || return 1
  [ -z "$untracked" ] || return 1
  git_tree=$(git -C "$root" write-tree 2>/dev/null) || return 1
  printf '%s' "$git_tree" | grep -Eq '^[0-9a-f]{40}([0-9a-f]{24})?$' || return 1
  printf '%s' "$git_tree"
}

review_non_delivery_candidate() {
  local root="$1" branch="$2" current="$3" base series attempt outcome original action target
  local epoch ordinal best_epoch=-1 best_ordinal=-1 found=""
  base="$(review_series_state_root "$root")/series"; [ -d "$base" ] || return 1
  for series in "$base"/s-*; do
    [ -f "$series/series.json" ] && [ ! -L "$series/series.json" ] || continue
    [ "$(jq -r '.branch' "$series/series.json" 2>/dev/null)" = "$branch" ] || continue
    review_series_incarnation_matches "$root" "$series" || continue
    epoch=$(jq -er '.startedEpoch' "$series/series.json") || return 1
    for attempt in "$series/attempts"/a-*; do
      [ -d "$attempt" ] || continue
      review_attempt_path_valid "$root" "$attempt" || return 1
      review_attempt_validate_start "$root" "$attempt" || return 1
      [ -f "$attempt/completion.json" ] && [ ! -L "$attempt/completion.json" ] || continue
      outcome=$(jq -er '.outcome' "$attempt/completion.json") || return 1
      case "$outcome" in clean|concern|scope|concern+scope) ;; *) continue ;; esac
      if review_attempt_authorizes "$root" "$attempt" "$current" 2>/dev/null; then
        :
      elif [ -f "$attempt/consumption-intent/intent.json" ] \
        && [ -f "$series/closed.json" ] && [ ! -L "$series/closed.json" ]; then
        action=$(jq -er '.action' "$attempt/consumption-intent/intent.json") || return 1
        target=$(jq -er '.target' "$attempt/consumption-intent/intent.json") || return 1
        case "$target" in ""|/*|../*|*/../*|*/..) return 1 ;; esac
        original=$(jq -er '.originalTree' "$attempt/consumption-intent/intent.json") || return 1
        review_attempt_authorizes "$root" "$attempt" "$original" 2>/dev/null || continue
        review_consumption_matches_current "$root" "$attempt" "$action" "$root/$target" 2>/dev/null || continue
      else
        continue
      fi
      ordinal=$(jq -er '.ordinal' "$attempt/start.json") || return 1
      if [ "$epoch" -gt "$best_epoch" ] || { [ "$epoch" = "$best_epoch" ] && [ "$ordinal" -gt "$best_ordinal" ]; }; then
        found="$attempt"; best_epoch="$epoch"; best_ordinal="$ordinal"
      fi
    done
  done
  [ -n "$found" ] || return 1
  printf '%s' "$found"
}

review_non_delivery_preparation_validate() {
  local root="$1" file="$2" expected_branch="${3:-}" expected_parent="${4:-}" expected_git_tree="${5:-}"
  local series attempt branch incarnation reviewed result parent git_tree outcome id ids expected sdir attempt_dir rendered
  local history history_sha expected_history
  [ -f "$file" ] && [ ! -L "$file" ] || return 1
  jq -e '
    .version==3 and (.id|test("^[0-9a-f]{64}$")) and
    (.seriesId|test("^s-[0-9]{10}-[0-9a-f]{24}$")) and (.attemptId|test("^a-[0-9]{6}$")) and
    (.branch|type=="string" and length>0) and (.branchIncarnation|test("^[0-9a-f]{64}$")) and
    (.reviewedTree|test("^[0-9a-f]{16}$")) and (.resultTree|test("^[0-9a-f]{16}$")) and
    (.expectedParent|test("^[0-9a-f]{40}([0-9a-f]{24})?$")) and
    (.gitTree|test("^[0-9a-f]{40}([0-9a-f]{24})?$")) and
    (.outcome=="clean" or .outcome=="concern" or .outcome=="scope" or .outcome=="concern+scope") and
    (.historySha256|test("^[0-9a-f]{64}$")) and
    (.resolutionIds|type=="array" and all(.[]; test("^[0-9a-f]{64}$")))
  ' "$file" >/dev/null 2>&1 || return 1
  series=$(jq -er '.seriesId' "$file") || return 1
  attempt=$(jq -er '.attemptId' "$file") || return 1
  branch=$(jq -er '.branch' "$file") || return 1
  incarnation=$(jq -er '.branchIncarnation' "$file") || return 1
  reviewed=$(jq -er '.reviewedTree' "$file") || return 1
  result=$(jq -er '.resultTree' "$file") || return 1
  parent=$(jq -er '.expectedParent' "$file") || return 1
  git_tree=$(jq -er '.gitTree' "$file") || return 1
  outcome=$(jq -er '.outcome' "$file") || return 1
  history_sha=$(jq -er '.historySha256' "$file") || return 1
  id=$(jq -er '.id' "$file") || return 1
  ids=$(jq -r '.resolutionIds[]' "$file") || return 1
  [ -z "$expected_branch" ] || [ "$branch" = "$expected_branch" ] || return 1
  [ -z "$expected_parent" ] || [ "$parent" = "$expected_parent" ] || return 1
  [ -z "$expected_git_tree" ] || [ "$git_tree" = "$expected_git_tree" ] || return 1
  sdir=$(review_series_dir "$root" "$series")
  attempt_dir="$sdir/attempts/$attempt"
  review_attempt_path_valid "$root" "$attempt_dir" || return 1
  review_series_incarnation_matches "$root" "$sdir" || return 1
  [ "$(jq -r '.branch' "$sdir/series.json" 2>/dev/null)" = "$branch" ] || return 1
  [ "$(review_series_incarnation_value "$root" "$sdir")" = "$incarnation" ] || return 1
  [ "$(jq -r '.tree' "$attempt_dir/start.json" 2>/dev/null)" = "$reviewed" ] || return 1
  [ "$(jq -r '.outcome' "$attempt_dir/completion.json" 2>/dev/null)" = "$outcome" ] || return 1
  rendered="${file%/preparation.json}/rendered.md"
  [ -f "$rendered" ] && [ ! -L "$rendered" ] || return 1
  history=$(review_history_section_extract "$rendered") || return 1
  [ "$(review_workflow_hash "$history")" = "$history_sha" ] || return 1
  expected_history=$(review_series_history_render "$root" "$series" "$attempt_dir") || return 1
  [ "$history" = "$expected_history" ] || return 1
  if [ -n "$ids" ]; then
    # Deliberately split newline-separated hexadecimal IDs.
    review_pr_resolution_ids_match "$rendered" $ids || return 1
  else
    review_pr_resolution_ids_match "$rendered" || return 1
    [ "$(grep -cFx 'No human review resolution was required.' "$rendered" 2>/dev/null)" = 1 ] || return 1
  fi
  expected=$(review_workflow_hash "$series"$'\n'"$attempt"$'\n'"$branch"$'\n'"$incarnation"$'\n' \
    "$reviewed"$'\n'"$result"$'\n'"$parent"$'\n'"$git_tree"$'\n'"$outcome"$'\n'"$history_sha"$'\n'"$ids") || return 1
  [ "$expected" = "$id" ]
}

review_non_delivery_finish() {
  local root="$1" branch current git_tree attempt series sdir incarnation reviewed outcome parent rendered ids id stage reason
  local history history_sha resolutions
  branch=$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null) || return 1
  case "$branch" in HEAD|main|deliver/*) return 1 ;; esac
  git_tree=$(review_index_tree_ready "$root") || return 1
  current=$(CLAUDE_PROJECT_DIR="$root" "${OH_HOME:-$root}/core/scripts/tree-digest.sh" 2>/dev/null) || return 1
  attempt=$(review_non_delivery_candidate "$root" "$branch" "$current") || return 1
  review_attempt_path_valid "$root" "$attempt" || return 1
  series=$(jq -er '.seriesId' "$attempt/start.json") || return 1
  sdir=$(review_series_dir "$root" "$series")
  incarnation=$(review_series_incarnation_value "$root" "$sdir") || return 1
  reviewed=$(jq -er '.tree' "$attempt/start.json") || return 1
  outcome=$(jq -er '.outcome' "$attempt/completion.json") || return 1
  case "$outcome" in clean|concern|scope|concern+scope) ;; *) return 1 ;; esac
  parent=$(git -C "$root" rev-parse HEAD 2>/dev/null) || return 1
  history=$(review_series_history_render "$root" "$series" "$attempt") || return 1
  history_sha=$(review_workflow_hash "$history") || return 1
  resolutions=$(review_pr_resolutions_render "$root" "$branch") || return 1
  if [ -z "$resolutions" ]; then
    resolutions='## Review resolutions

No human review resolution was required.'
  fi
  rendered=$(printf '<!-- review-history:start -->\n%s\n<!-- review-history:end -->\n\n%s' "$history" "$resolutions") || return 1
  ids=$(printf '%s\n' "$rendered" | sed -n 's/^Review-Resolution: \([0-9a-f]\{64\}\)$/\1/p' | awk '!seen[$0]++') || return 1
  id=$(review_workflow_hash "$series"$'\n'"${attempt##*/}"$'\n'"$branch"$'\n'"$incarnation"$'\n' \
    "$reviewed"$'\n'"$current"$'\n'"$parent"$'\n'"$git_tree"$'\n'"$outcome"$'\n'"$history_sha"$'\n'"$ids") || return 1
  if [ -f "$sdir/pr-handoff/preparation.json" ] && [ ! -L "$sdir/pr-handoff/preparation.json" ]; then
    review_non_delivery_preparation_validate "$root" "$sdir/pr-handoff/preparation.json" "$branch" "$parent" "$git_tree" || return 1
    [ "$(jq -r '.id' "$sdir/pr-handoff/preparation.json")" = "$id" ] || return 1
  else
    [ ! -e "$sdir/pr-handoff" ] && [ ! -L "$sdir/pr-handoff" ] || return 1
    stage="$sdir/.pr-handoff.$$.$(review_workflow_nonce)"
    mkdir "$stage" || return 1
    printf '%s\n' "$rendered" > "$stage/rendered.md" || { rm -rf "$stage"; return 1; }
    jq -cn --arg id "$id" --arg series "$series" --arg attempt "${attempt##*/}" --arg branch "$branch" \
    --arg incarnation "$incarnation" --arg reviewed "$reviewed" --arg result "$current" \
    --arg parent "$parent" --arg gitTree "$git_tree" --arg outcome "$outcome" --arg history "$history_sha" --arg ids "$ids" \
    --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      '{version:3,id:$id,seriesId:$series,attemptId:$attempt,branch:$branch,branchIncarnation:$incarnation,
        reviewedTree:$reviewed,resultTree:$result,expectedParent:$parent,gitTree:$gitTree,outcome:$outcome,
        historySha256:$history,resolutionIds:($ids|split("\n")|map(select(length>0))),recordedAt:$at}' > "$stage/preparation.json" \
      || { rm -rf "$stage"; return 1; }
    review_non_delivery_preparation_validate "$root" "$stage/preparation.json" "$branch" "$parent" "$git_tree" \
      || { rm -rf "$stage"; return 1; }
    mv "$stage" "$sdir/pr-handoff" || { rm -rf "$stage"; return 1; }
  fi
  reason=resolved; [ "$outcome" = clean ] && reason=clean
  review_series_close "$root" "$series" "$reason" || return 1
  printf 'Review-Preparation: %s\n' "$id"
  [ -z "$ids" ] || printf '%s\n' "$ids" | sed 's/^/Review-Resolution: /'
}

review_non_delivery_preparation_find() {
  local root="$1" id="$2" branch="${3:-}" parent="${4:-}" git_tree="${5:-}" base file found=""
  printf '%s' "$id" | grep -Eq '^[0-9a-f]{64}$' || return 1
  base="$(review_series_state_root "$root")/series"; [ -d "$base" ] || return 1
  for file in "$base"/s-*/pr-handoff/preparation.json; do
    [ -f "$file" ] || continue
    [ "$(jq -r '.id // empty' "$file" 2>/dev/null)" = "$id" ] || continue
    [ -z "$found" ] || return 1
    review_non_delivery_preparation_validate "$root" "$file" "$branch" "$parent" "$git_tree" || return 1
    found="$file"
  done
  [ -n "$found" ] || return 1
  printf '%s' "$found"
}

review_branch_pending_preparation_id() {
  local root="$1" branch="$2" parent git_tree base file epoch best=-1 found=""
  parent=$(git -C "$root" rev-parse HEAD 2>/dev/null) || return 1
  git_tree=$(git -C "$root" write-tree 2>/dev/null) || return 1
  base="$(review_series_state_root "$root")/series"; [ -d "$base" ] || return 0
  for file in "$base"/s-*/pr-handoff/preparation.json; do
    [ -f "$file" ] || continue
    review_non_delivery_preparation_validate "$root" "$file" "$branch" "$parent" "$git_tree" 2>/dev/null || continue
    epoch=$(jq -er '.recordedAt | fromdateiso8601' "$file") || return 1
    if [ "$epoch" -ge "$best" ]; then found=$(jq -er '.id' "$file") || return 1; best="$epoch"; fi
  done
  [ -z "$found" ] || printf '%s' "$found"
}

review_non_delivery_handoff_seal() {
  local root="$1" expected_branch="${2:-}" branch head parent git_tree message prep_id prep_file
  local series attempt incarnation reviewed result outcome ids rendered handoff sdir dir stage history_sha
  branch=$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null) || return 1
  case "$branch" in HEAD|main|deliver/*) return 1 ;; esac
  [ -z "$expected_branch" ] || [ "$branch" = "$expected_branch" ] || return 1
  [ -z "$(git -C "$root" status --porcelain=v1 --untracked-files=all 2>/dev/null)" ] || return 1
  head=$(git -C "$root" rev-parse HEAD 2>/dev/null) || return 1
  parent=$(git -C "$root" rev-parse HEAD^ 2>/dev/null) || return 1
  git_tree=$(git -C "$root" rev-parse HEAD^{tree} 2>/dev/null) || return 1
  message=$(git -C "$root" show -s --format=%B HEAD 2>/dev/null) || return 1
  [ "$(printf '%s\n' "$message" | grep -cE '^Review-Preparation: [0-9a-f]{64}$')" = 1 ] || return 1
  prep_id=$(printf '%s\n' "$message" | sed -n 's/^Review-Preparation: \([0-9a-f]\{64\}\)$/\1/p')
  prep_file=$(review_non_delivery_preparation_find "$root" "$prep_id" "$branch" "$parent" "$git_tree") || return 1
  series=$(jq -er '.seriesId' "$prep_file") || return 1
  attempt=$(jq -er '.attemptId' "$prep_file") || return 1
  incarnation=$(jq -er '.branchIncarnation' "$prep_file") || return 1
  reviewed=$(jq -er '.reviewedTree' "$prep_file") || return 1
  result=$(jq -er '.resultTree' "$prep_file") || return 1
  outcome=$(jq -er '.outcome' "$prep_file") || return 1
  history_sha=$(jq -er '.historySha256' "$prep_file") || return 1
  ids=$(jq -r '.resolutionIds[]' "$prep_file") || return 1
  if [ -n "$ids" ]; then
    [ "$(printf '%s\n' "$message" | sed -n 's/^Review-Resolution: \([0-9a-f]\{64\}\)$/\1/p' | sort -u)" = "$(printf '%s\n' "$ids" | sort -u)" ] || return 1
  else
    [ -z "$(printf '%s\n' "$message" | sed -n 's/^Review-Resolution: //p')" ] || return 1
  fi
  handoff=$(review_workflow_hash "$prep_id"$'\n'"$head") || return 1
  sdir=$(review_series_dir "$root" "$series")
  rendered="${prep_file%/preparation.json}/rendered.md"
  dir="$sdir/pr-handoff/seals/$head"
  if [ -f "$dir/body.md" ] && [ ! -L "$dir/body.md" ]; then
    review_pr_handoff_validate "$dir/body.md" "$branch" "$incarnation" "$head" || return 1
    cat "$dir/body.md"; return
  fi
  [ ! -e "$dir" ] && [ ! -L "$dir" ] || return 1
  mkdir -p "$sdir/pr-handoff/seals" || return 1
  stage="$sdir/pr-handoff/seals/.seal.$$.$(review_workflow_nonce)"
  mkdir "$stage" || return 1
  {
    cat "$rendered"
    printf '\nReview-Handoff-Series: %s\nReview-Handoff-Attempt: %s\nReview-Branch: %s\nReview-Incarnation: %s\n' \
      "$series" "$attempt" "$branch" "$incarnation"
    printf 'Review-Tree: %s\nReview-Result-Tree: %s\nReview-Parent: %s\nReview-Git-Tree: %s\nReview-Head: %s\n' \
      "$reviewed" "$result" "$parent" "$git_tree" "$head"
    printf 'Review-Outcome: %s\nReview-History-SHA256: %s\nReview-Preparation: %s\nReview-Handoff: %s\n' \
      "$outcome" "$history_sha" "$prep_id" "$handoff"
  } > "$stage/body.md" || { rm -rf "$stage"; return 1; }
  review_pr_handoff_validate "$stage/body.md" "$branch" "$incarnation" "$head" \
    || { rm -rf "$stage"; return 1; }
  mv "$stage" "$dir" || { rm -rf "$stage"; return 1; }
  cat "$dir/body.md"
}

review_github_issue_url_valid() {
  local root="$1" url="$2" remote host repo
  remote=$(git -C "$root" remote get-url origin 2>/dev/null) || return 1
  case "$remote" in
    git@*:* ) host="${remote#git@}"; host="${host%%:*}"; repo="${remote#*:}" ;;
    ssh://git@*/* ) host="${remote#ssh://git@}"; host="${host%%/*}"; repo="${remote#ssh://git@*/}" ;;
    https://*/*|http://*/* ) host="${remote#*://}"; host="${host%%/*}"; repo="${remote#*://*/}" ;;
    *) return 1 ;;
  esac
  repo="${repo%.git}"
  [ -n "$host" ] && [ -n "$repo" ] || return 1
  printf '%s\n' "$url" | grep -Eq "^https://$(printf '%s' "$host" | sed 's/[][\\.^$*+?(){}|]/\\&/g')/$(printf '%s' "$repo" | sed 's/[][\\.^$*+?(){}|]/\\&/g')/issues/[1-9][0-9]*$"
}

# Complete a product/frozen-design scope route only from an exact host-owned human choice.
# Creating an issue is external work; this record binds its URL back to the retained finding.
review_scope_issue_record() {
  local root="$1" attempt="$2" url="$3" source="$4" transition original current choice="" tmp outcome
  local series pr_id existing
  review_attempt_path_valid "$root" "$attempt" || return 1
  review_attempt_validate_start "$root" "$attempt" || return 1
  transition="$attempt/scope-transition.json"
  [ -f "$transition" ] && [ ! -L "$transition" ] || return 1
  [ "$(jq -r '.status' "$transition" 2>/dev/null)" = human-route-required ] || return 1
  [ "$(jq -r '.action' "$transition" 2>/dev/null)" = route-scope ] || return 1
  if [ -f "$attempt/resolution.json" ] && [ ! -L "$attempt/resolution.json" ]; then
    choice=$(jq -r '.choice' "$attempt/resolution.json" 2>/dev/null) || return 1
    case "$choice" in route-scope|fix-concerns+route-scope|accept-concerns+route-scope) ;; *) return 1 ;; esac
  else
    outcome=$(jq -r '.outcome' "$attempt/completion.json" 2>/dev/null) || return 1
    case "$outcome" in blocking+scope|blocking+concern+scope) ;; *) return 1 ;; esac
  fi
  review_github_issue_url_valid "$root" "$url" || return 1
  original=$(jq -r '.originalTree' "$transition") || return 1
  current=$(CLAUDE_PROJECT_DIR="$root" "${OH_HOME:-$root}/core/scripts/tree-digest.sh" 2>/dev/null) || return 1
  [ "$current" = "$original" ] || return 1
  [ -n "$choice" ] || choice=policy-required
  series=$(jq -er '.seriesId' "$attempt/start.json") || return 1
  pr_id=$(review_pr_resolution_publish "$root" "$attempt" route-scope "$choice" "$url" "$current") || return 1
  if [ -e "$attempt/scope-destination.json" ] || [ -L "$attempt/scope-destination.json" ]; then
    [ -f "$attempt/scope-destination.json" ] && [ ! -L "$attempt/scope-destination.json" ] || return 1
    jq -e --arg url "$url" --arg source "$source" --arg original "$original" --arg id "$pr_id" '
      .version==1 and .status=="applied" and .kind=="github-issue" and .issueUrl==$url and
      .source==$source and .originalTree==$original and .resultTree==$original and .prResolutionId==$id
    ' "$attempt/scope-destination.json" >/dev/null 2>&1
    return
  fi
  tmp="$attempt/.scope-destination.$$"
  jq -cn --arg url "$url" --arg source "$source" --arg original "$original" --arg result "$current" --arg id "$pr_id" \
    --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '
      {version:1,status:"applied",kind:"github-issue",issueUrl:$url,source:$source,
       originalTree:$original,resultTree:$result,prResolutionId:$id,recordedAt:$at}
    ' > "$tmp" && ln "$tmp" "$attempt/scope-destination.json" 2>/dev/null \
    || { rm -f "$tmp"; return 1; }
  rm -f "$tmp"
  if [ -f "$attempt/resolution.json" ]; then
    review_scope_pr_resolution_ensure "$root" "$attempt" >/dev/null || return 1
  fi
}

review_attempt_find_owner() {
  local root="$1" host="$2" owner="$3" base series entry found=""
  base="$(review_series_state_root "$root")/series"
  [ -d "$base" ] || return 1
  for series in "$base"/s-*; do
    [ -f "$series/series.json" ] || continue
    for entry in "$series/attempts"/*; do
      [ -e "$entry" ] || continue
      review_attempt_unadmitted_dir "$root" "$entry" && continue
      review_attempt_path_valid "$root" "$entry" || return 2
      review_attempt_validate_start "$root" "$entry" || return 2
      [ "$(jq -r '.host' "$entry/start.json" 2>/dev/null)" = "$host" ] || continue
      [ "$(jq -r '.owner' "$entry/start.json" 2>/dev/null)" = "$owner" ] || continue
      [ -z "$found" ] || return 2
      found="$entry"
    done
  done
  [ -n "$found" ] || return 1
  printf '%s' "$found"
}

review_attempt_validate_start() {
  local root="$1" attempt="$2" file snapshot request snapsha reqsha id series ordinal
  review_attempt_path_valid "$root" "$attempt" || return 1
  file="$attempt/start.json"
  id="${attempt##*/}"
  series="${attempt%/attempts/*}"; series="${series##*/}"
  ordinal="${id#a-}"; while [ "${ordinal#0}" != "$ordinal" ]; do ordinal="${ordinal#0}"; done
  [ -n "$ordinal" ] || ordinal=0
  jq -e --arg id "$id" --arg series "$series" --argjson ordinal "$ordinal" '
    .version==1 and .id==$id and .seriesId==$series and .ordinal==$ordinal and
    (.ordinal|type=="number" and floor==. and .>0) and
    (.host=="claude" or .host=="codex") and (.owner|type=="string" and length>0) and
    (.session|type=="string" and length>0) and (.tree|test("^[0-9a-f]{16}$")) and
    (.branch|type=="string" and length>0) and (.roundKey|type=="string" and length>0) and
    (.head|test("^[0-9a-f]{40,64}$"))
  ' "$file" >/dev/null || return 1
  snapshot="$attempt/snapshot.txt"; [ -f "$snapshot" ] && [ ! -L "$snapshot" ] || return 1
  snapsha=$(if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$snapshot" | awk '{print $1}'; else sha256sum "$snapshot" | awk '{print $1}'; fi) || return 1
  [ "$snapsha" = "$(jq -r '.snapshotSha256' "$file")" ] || return 1
  reqsha=$(jq -r '.requestSha256 // "null"' "$file") || return 1
  if [ "$reqsha" != null ]; then
    request="$attempt/request.md"; [ -f "$request" ] && [ ! -L "$request" ] || return 1
    [ "$(if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$request" | awk '{print $1}'; else sha256sum "$request" | awk '{print $1}'; fi)" = "$reqsha" ] || return 1
  fi
}
