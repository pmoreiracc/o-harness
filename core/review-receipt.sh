#!/usr/bin/env bash
# Shared review evidence contract (ADR-0047).

REVIEW_RECEIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

review_header() {
  awk -v key="$2" '
    /^---[[:space:]]*$/ { exit }
    index($0, key ": ") == 1 { count++; value=substr($0, length(key) + 3) }
    END { if (count != 1) exit 1; print value }
  ' "$1"
}

review_sha256_file() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else sha256sum "$1" | awk '{print $1}'
  fi
}

# review_normalize <file> — the reviewer's output with markdown decoration removed.
#
# The workflow-evidence contract (ADR-0047) is about what a review names: anchors, scope, concrete
# attacks with outcomes, limits, and a verdict whose counts match its findings. It is not
# about how the reviewer emphasises a label. Matching decorated prose byte-for-byte made
# `**Attack:**` and a backticked verdict line indistinguishable from a review that did no
# work, which discarded four consecutive complete reviews.
#
# So decoration is stripped here, once, and every check below runs on the result. Nothing
# in the manifest's substance is relaxed by this — and one thing tightens, because a
# `**[BLOCKING] …**` line hidden under a clean verdict is now counted as the finding it is.
review_normalize() {
  awk '
    function unwrap(s,   inner) {
      while (1) {
        if (length(s) >= 4 && substr(s, 1, 2) == "**" && substr(s, length(s) - 1) == "**") {
          inner = substr(s, 3, length(s) - 4)
          if (index(inner, "**") > 0) return s
          s = inner
          continue
        }
        if (length(s) >= 2 && substr(s, 1, 1) == "`" && substr(s, length(s)) == "`") {
          inner = substr(s, 2, length(s) - 2)
          if (index(inner, "`") > 0) return s
          s = inner
          continue
        }
        return s
      }
    }
    # untoken1 <s> — strip one layer of emphasis delimiters hugging a leading severity token,
    # in either the token-only form (**[BLOCKING]** rest, `[BLOCKING]` rest) or the
    # whole-remainder form (*[BLOCKING] rest*, _[BLOCKING] rest_). unwrap() only removes a
    # delimiter pair around the *entire* line, so neither form reaches it, and single "*"/"_"
    # emphasis it does not handle at all — the severity token would then read as ordinary prose
    # and a blocking finding would mint a receipt under a clean verdict.
    function severity_prefix(s,   u) {
      u = toupper(s)
      return u ~ /^(\[(BLOCKING|CONCERN|SCOPE)\]|(BLOCKING|CONCERN|SCOPE)(:|[ \t]|$))/
    }
    function untoken1(s,   c, d, dl, rest, u, te, word, wi) {
      c = substr(s, 1, 1)
      if (c != "*" && c != "_" && c != "`") return s
      dl = 1
      while (substr(s, dl + 1, 1) == c) dl++
      d = substr(s, 1, dl)
      rest = substr(s, dl + 1)
      u = toupper(rest)
      if (!severity_prefix(rest) \
          && u !~ /^\[(BLOCKING|CONCERN|SCOPE)\]/ \
          && u !~ /^(BLOCKING|CONCERN|SCOPE)/) return s
      # Whole-remainder emphasis: **BLOCKING: explanation** and **[BLOCKING] explanation**.
      if (length(rest) >= dl && substr(rest, length(rest) - dl + 1) == d)
        return substr(rest, 1, length(rest) - dl)
      # Token-only emphasis. Try the bracketed token, then each bare severity word, with the
      # colon inside or outside the emphasis: **BLOCKING:** / **BLOCKING**:.
      if (substr(rest, 1, 1) == "[") {
        te = index(rest, "]")
        if (te > 0 && substr(rest, te + 1, 1) == ":" && substr(rest, te + 2, dl) == d)
          return substr(rest, 1, te + 1) substr(rest, te + dl + 2)
        if (te > 0 && substr(rest, te + 1, dl) == d)
          return substr(rest, 1, te) substr(rest, te + dl + 1)
      } else {
        u = toupper(rest)
        for (wi = 1; wi <= 3; wi++) {
          word = (wi == 1 ? "BLOCKING" : (wi == 2 ? "CONCERN" : "SCOPE"))
          if (substr(u, 1, length(word)) != word) continue
          te = length(word)
          if (substr(rest, te + 1, 1) == ":" && substr(rest, te + 2, dl) == d)
            return substr(rest, 1, te + 1) substr(rest, te + dl + 2)
          if (substr(rest, te + 1, dl) == d)
            return substr(rest, 1, te) substr(rest, te + dl + 1)
        }
      }
      return s
    }
    function untoken(s,   prev) {
      prev = ""
      while (s != prev) { prev = s; s = untoken1(s) }
      return s
    }
    # strip_field_labels <s> — undecorate every occurrence of a manifest field-label keyword
    # (Attack, Outcome, Anchor, Where, Why, Resolve), whatever emphasis wrapped it and wherever
    # the colon that follows it landed. A reviewer can render the same label as `**Attack:**`,
    # `**Attack**:`, `` `Attack`: ``, `_Attack_:`, or `*Attack:*` — visually near-identical, all
    # meaning the same field — and byte-for-byte matching only one shape is what let two
    # complete "Attack: ... Outcome: ..." entries be silently seen as one, discarding an
    # otherwise-valid review over which delimiter the model happened to pick. Two passes per
    # keyword, order-independent: the first collapses the colon-inside-decoration form
    # (`**Attack:**`) by matching the colon as part of the run; the second collapses the
    # colon-outside form (`**Attack**:`), which the first pattern cannot match because a colon
    # sits where it requires a decoration character.
    function strip_field_labels(s,   kw, i, n, k, prev) {
      n = split("Attack Outcome Anchor Where Why Resolve", kw, " ")
      prev = ""
      while (s != prev) {
        prev = s
        for (i = 1; i <= n; i++) {
          k = kw[i]
          gsub("[*_`]{1,2}" k ":[*_`]{0,2}", k ":", s)
          gsub("[*_`]{1,2}" k "[*_`]{1,2}", k, s)
        }
      }
      return s
    }
    # One conservative classifier for substantive severity-like text that is close enough to
    # the canonical finding grammar that treating it as ordinary prose would be unsafe.
    function finding_like(s,   u) {
      u = toupper(s)
      if (u ~ /^\[(BLOCKING|CONCERN|SCOPE)\]/) {
        # Harmless whitespace and an optional presentational colon are normalized by the main
        # record rule below. Anything left here is ambiguous and must not become ordinary prose.
        close_at = index(u, "]")
        rest = substr(s, close_at + 1)
        if (substr(rest, 1, 1) == ":") rest = substr(rest, 2)
        if (rest ~ /^[ \t]+[^ \t]/) return 0
        return 1
      }
      if (u ~ /^(BLOCKING|CONCERN|SCOPE)(:|[[:space:]]*[-—]|$)/) return 1
      return 0
    }
    {
      line = $0
      sub(/\r$/, "", line)
      # Indentation is preserved exactly for the lines recognised by it — the
      # Anchor/Where/Why/Resolve fields of a finding and the evidence entries.
      indent = ""
      if (match(line, /^[ \t]+/)) { indent = substr(line, 1, RLENGTH); line = substr(line, RLENGTH + 1) }
      sub(/[ \t]+$/, "", line)
      # Any run of leading ">" blockquote markers and ordinary list markers (CommonMark 5.2:
      # "-", "*", "+", or digits then "." or ")"), each with its own spacing, is decoration the
      # reviewer chose and this check does not. Capture the whole run so a finding or verdict
      # rendered behind "> ", "  - ", or "> - " is exposed exactly like a top-level one.
      quote = ""
      while (match(line, /^(>[ \t]*|(-|\*|\+|[0-9]+[.)])[ \t]+)/)) {
        quote = quote substr(line, 1, RLENGTH); line = substr(line, RLENGTH + 1)
      }
      out = strip_field_labels(untoken(unwrap(line)))
      # Required finding fields are substantive by label, order, uniqueness, and value, not
      # by a presentational choice between spaces and tabs or by whether a value wraps. Expose
      # every unambiguous key here, including one whose value begins on a following continuation
      # line. List/quote decoration was removed into `quote` above; strip a one-to-six-marker
      # heading too. Canonicalizing decorated standalone or duplicate keys is intentional: the
      # structural pass must reject them instead of letting their Markdown hide the ambiguity.
      field_candidate = out
      field_previous = ""
      while (field_candidate != field_previous) {
        field_previous = field_candidate
        # Prefixes can be stacked in any presentation order. For example, after the outer
        # list marker is removed, `- [ ] ### ***Anchor***:` still has a task marker in front
        # of a heading. Peel every recognised layer, then repeat so no later layer conceals
        # an earlier kind from the semantic-key classifier.
        while (match(field_candidate, /^(>[ \t]*|(-|\*|\+|[0-9]+[.)])[ \t]+)/))
          field_candidate = substr(field_candidate, RLENGTH + 1)
        if (field_candidate ~ /^\[[ xX]\][ \t]+/)
          sub(/^\[[ xX]\][ \t]+/, "", field_candidate)
        field_heading = field_candidate
        field_hashes = 0
        while (substr(field_heading, 1, 1) == "#") {
          field_hashes++; field_heading = substr(field_heading, 2)
        }
        if (field_hashes >= 1 && field_hashes <= 6 && field_heading ~ /^[ \t]+/) {
          sub(/^[ \t]+/, "", field_heading)
          field_candidate = field_heading
        }
        field_candidate = strip_field_labels(untoken(unwrap(field_candidate)))
      }
      if (field_candidate ~ /^(Anchor|Where|Why|Resolve):([ \t].*)?$/) {
        field_label = substr(field_candidate, 1, index(field_candidate, ":") - 1)
        field_value = substr(field_candidate, index(field_candidate, ":") + 1)
        sub(/^[ \t]+/, "", field_value)
        if (field_value == "") print "  " field_label ":"
        else print "  " field_label ": " field_value
        next
      }
      severity = out
      # POSIX awk does not require interval expressions such as {1,6}; the supported macOS
      # awk consequently left Markdown headings intact. Count the leading run explicitly and
      # strip it only when it is a one-to-six-marker heading followed by whitespace.
      heading = severity
      hashes = 0
      heading_severity = 0
      while (substr(heading, 1, 1) == "#") { hashes++; heading = substr(heading, 2) }
      if (hashes >= 1 && hashes <= 6 && heading ~ /^[ \t]+/) {
        sub(/^[ \t]+/, "", heading)
        # A heading can wrap an independently decorated token (`#### **CONCERN**:`), so run
        # the same undecoration pipeline again after exposing its content.
        severity = strip_field_labels(untoken(unwrap(heading)))
        heading_severity = toupper(severity) ~ /^\[(BLOCKING|CONCERN|SCOPE)\]/
      }
      # A bracketed severity with harmless heading/emphasis decoration, an optional colon,
      # and any non-empty horizontal whitespace separator is the canonical finding header.
      # Normalize it instead of rejecting an otherwise complete review for presentation alone.
      upper_severity = toupper(severity)
      if (upper_severity ~ /^\[(BLOCKING|CONCERN|SCOPE)\]/) {
        close_at = index(severity, "]")
        severity_rest = substr(severity, close_at + 1)
        if (substr(severity_rest, 1, 1) == ":") severity_rest = substr(severity_rest, 2)
        if (severity_rest ~ /^[ \t]+[^ \t]/) {
          sub(/^[ \t]+/, "", severity_rest)
          print substr(upper_severity, 1, close_at) " " severity_rest
          next
        }
      }
      if (heading_severity || finding_like(severity)) {
        print "REVIEW-FINDING-LIKE: " out
        next
      }
      # Accept only unambiguous textual equivalents of the canonical receipt grammar.
      # Reviewers sometimes render these four required headings as exact inline labels;
      # preserving the substantive review must not depend on that Markdown choice.
      if (match(out, /^(Anchors read|Scope examined|Adversarial attacks|Limits):[ \t]*/)) {
        label = substr(out, 1, index(out, ":") - 1)
        value = substr(out, RLENGTH + 1)
        print "### " label
        if (value != "") print "- " value
        next
      }
      # Likewise canonicalize the single unambiguous metadata spelling emitted by some
      # reviewers. Extra explanatory suffixes are not authority; family and relation are.
      meta = out
      gsub(/`/, "", meta)
      if (meta ~ /^Finding [0-9]+ — family: [a-z0-9][a-z0-9-]*; relation: [a-z-]+(;.*)?$/) {
        number = meta; sub(/^Finding /, "", number); sub(/ .*/, "", number)
        family = meta; sub(/^.*— family: /, "", family); sub(/;.*/, "", family)
        relation = meta; sub(/^.*relation: /, "", relation); sub(/;.*/, "", relation)
        print "- Finding " number " | Family: " family " | Relation: " relation
        next
      }
      # A finding header or verdict is a top-level line whatever decoration wrapped it, so it
      # is emitted at column 0 with every prefix dropped: the checks below match it by an
      # anchored "^\[BLOCKING\] " / "^VERDICT:", and a preserved indent or quote/marker run
      # would hide it under a clean verdict exactly as the bare "- " marker once did. Every
      # other line keeps its prefix, because its recogniser depends on it.
      if (substr(out, 1, 8) == "VERDICT:" || out ~ /^\[(BLOCKING|CONCERN|SCOPE)\] /) { indent = ""; quote = "" }
      print indent quote out
    }
  ' "$1"
}

# Validate the complete Evidence manifest for historical strict receipts. New semantic attempts
# do not call this parser; accepted-round and calibration readers retain it for compatibility.
review_evidence_output_check() {
  local file="$1" check_verdicts="${2:-1}" norm reason
  norm=$(review_normalize "$file") || return 1
  reason=$(printf '%s\n' "$norm" | awk -v check_verdicts="$check_verdicts" '
    BEGIN { evidence=0; anchors=0; scope=0; attacks=0; limits=0; section=0; verdicts=0; secbad=0 }
    /^## Evidence$/ { if (evidence) secbad=1; evidence=1; next }
    /^### Anchors read$/ { if (!evidence || section) secbad=1; section=1; next }
    /^### Scope examined$/ { if (!evidence || section != 1) secbad=1; section=2; next }
    /^### Adversarial attacks$/ { if (!evidence || section != 2) secbad=1; section=3; next }
    /^### Limits$/ { if (!evidence || section != 3) secbad=1; section=4; next }
    /^VERDICT:/ { verdicts++; next }
    section == 1 && /^- [^[:space:]].*/ { anchors++; next }
    section == 2 && /^- [^[:space:]].*/ { scope++; next }
    section == 3 && /^- Attack: .+ Outcome: .+/ { attacks++; next }
    section == 4 && /^- [^[:space:]].*/ { limits++; next }
    END {
      if (evidence != 1) print "the review carries no single \"## Evidence\" heading"
      else if (section != 4 || secbad) print "the Evidence subsections are missing or out of order (Anchors read, Scope examined, Adversarial attacks, Limits)"
      else if (check_verdicts == 1 && verdicts != 1) printf "the review must carry exactly one VERDICT line; it carries %d\n", verdicts
      else if (anchors < 1) print "\"### Anchors read\" names nothing"
      else if (scope < 1) print "\"### Scope examined\" names nothing"
      else if (attacks < 2) printf "\"### Adversarial attacks\" needs two \"- Attack: ... Outcome: ...\" entries; it has %d\n", attacks
      else if (limits < 1) print "\"### Limits\" names nothing"
    }
  ')
  if [ -n "$reason" ]; then
    printf '%s\n' "$reason"
    return 1
  fi
  return 0
}

# review_output_check <file> — prints nothing and returns 0 when the output carries the
# evidence contract; prints one line saying which requirement failed and returns 1 when it
# does not. One implementation, so the reason a receipt was refused can never disagree
# with the decision to refuse it.
review_output_check() {
  local file="$1" norm verdict counts expected reason structured
  if [ ! -f "$file" ] || [ -L "$file" ]; then
    printf 'the reviewer output is not a regular file\n'
    return 1
  fi
  norm=$(review_normalize "$file")
  verdict=$(printf '%s\n' "$norm" | awk 'NF { line=$0 } END { print line }')
  case "$verdict" in
    "VERDICT: clean — "*)
      if printf '%s\n' "$norm" | grep -Eq '^\[(BLOCKING|CONCERN|SCOPE)\] '; then
        printf 'the verdict is clean but the review lists [BLOCKING]/[CONCERN]/[SCOPE] findings\n'
        return 1
      fi
      ;;
    "VERDICT: findings — "*)
      if ! printf '%s\n' "$verdict" | grep -Eq '^VERDICT: findings — [0-9]+ blocking, [0-9]+ concerns?, [0-9]+ scope$'; then
        printf 'the verdict is not "VERDICT: findings — N blocking, M concerns, K scope"\n'
        return 1
      fi
      if printf '%s\n' "$verdict" | grep -Eq '— 0 blocking, 0 concerns?, 0 scope$'; then
        printf 'a verdict counting no findings must be "VERDICT: clean — ..." instead\n'
        return 1
      fi
      expected=$(printf '%s\n' "$verdict" | sed -E 's/^VERDICT: findings — ([0-9]+) blocking, ([0-9]+) concerns?, ([0-9]+) scope$/\1 \2 \3/')
      counts=$(printf '%s\n' "$norm" | awk '/^\[BLOCKING\] /{b++} /^\[CONCERN\] /{c++} /^\[SCOPE\] /{s++} END{printf "%d %d %d", b+0,c+0,s+0}')
      if [ "$counts" != "$expected" ]; then
        printf 'the verdict counts %s blocking/concerns/scope but the review lists %s\n' "$expected" "$counts"
        return 1
      fi
      ;;
    *)
      printf 'the last line is not "VERDICT: clean — ..." or "VERDICT: findings — ..."\n'
      return 1
      ;;
  esac
  if ! reason=$(review_evidence_output_check "$file" 1); then
    printf '%s\n' "$reason"
    return 1
  fi
  structured=$(mktemp -d "${TMPDIR:-/tmp}/review-structure.XXXXXX") || {
    printf 'the reviewer finding structure could not be checked\n'; return 1;
  }
  if ! review_finding_blocks_to_dir "$file" "$structured"; then
    rm -rf "$structured"
    printf 'a finding is missing, duplicates, reorders, empties, or ambiguously places its Anchor/Where/Why/Resolve keys\n'
    return 1
  fi
  rm -rf "$structured"
  return 0
}

review_output_validate() {
  review_output_check "$1" >/dev/null
}

# Check that every recognizable finding is a complete canonical block. Harmless Markdown
# presentation is normalized first; missing, reordered, or ambiguous substantive fields fail.
review_finding_blocks_to_dir() {
  local file="$1" out="$2" norm
  norm=$(mktemp "${TMPDIR:-/tmp}/review-findings.XXXXXX") || return 1
  review_normalize "$file" > "$norm" || { rm -f "$norm"; return 1; }
  awk -v out="$out" '
    function finish() {
      if (active && (field != 4 || !value)) bad=1
      active=0; field=0; value=0
    }
    function key_number(line,   key) {
      key=line
      sub(/^  /, "", key); sub(/:.*/, "", key)
      return key == "Anchor" ? 1 : key == "Where" ? 2 : key == "Why" ? 3 : key == "Resolve" ? 4 : 0
    }
    /^\[(BLOCKING|CONCERN|SCOPE)\] / {
      finish(); count++; active=1; field=0; value=0; path=out "/" count
      print $0 > path
      next
    }
    /^REVIEW-FINDING-LIKE: / { bad=1 }
    /^VERDICT: findings — / { findingsVerdict=1 }
    /^  (Anchor|Where|Why|Resolve):($| )/ {
      if (!active) { bad=1; next }
      nextfield=key_number($0)
      if (nextfield != field + 1 || (field > 0 && !value)) bad=1
      field=nextfield; value=0
      inline=$0; sub(/^  [^:]+:[[:space:]]*/, "", inline)
      if (inline ~ /[^[:space:]]/) value=1
      print $0 >> path
      next
    }
    /^[[:space:]]*(Anchor|Where|Why|Resolve):/ { bad=1; next }
    active && /^[[:space:]]+[^[:space:]]/ {
      if (field == 0) bad=1
      else { value=1; print $0 >> path }
      next
    }
    active && /^[[:space:]]*$/ { print $0 >> path; next }
    active { finish() }
    END { finish(); if (findingsVerdict && count == 0) bad=1; if (bad) exit 1 }
  ' "$norm"
  local result=$?
  rm -f "$norm"
  return "$result"
}


# review_series_output_check <file> <has-prior-round>
# New delivery reviews carry convergence telemetry outside the canonical finding block.
# That block remains the exact ADR-0043-routable severity/Anchor/Where/Why/Resolve shape.
review_series_output_check() {
  local file="$1" prior="$2" norm reason
  norm=$(review_normalize "$file")
  reason=$(printf '%s\n' "$norm" | awk -v prior="$prior" '
    BEGIN {
      split("task-and-design invariants-and-decisions affected-surfaces-and-negative-space correctness-and-failure-paths security-authorization-and-concurrency tests-claims-docs-and-generated-artifacts prior-findings-and-family-closure", wanted, " ")
      relation="(original|repeat-family|fix-regression|first-round-escape|newly-exposed|scope)"
    }
    /^\[(BLOCKING|CONCERN|SCOPE)\] / { findings++; if (metadata) bad="finding blocks must precede review-series metadata" }
    /^  Resolve:($| )/ { lastresolve=NR }
    /^## Review series metadata$/ { metadata++; metadataLine=NR; inmeta=1; next }
    /^## Evidence$/ { evidenceLine=NR; inmeta=0 }
    /^## / && $0 != "## Review series metadata" && $0 != "## Evidence" { if (inmeta) bad="review-series metadata must be immediately before Evidence"; inmeta=0 }
    inmeta && /^- none — clean review$/ { cleanmeta++; next }
    inmeta && /^- Finding [0-9]+ \| Family: [a-z0-9][a-z0-9-]* \| Relation: / {
      line=$0
      if (line !~ ("^[-] Finding [0-9]+ [|] Family: [a-z0-9][a-z0-9-]* [|] Relation: " relation "$")) bad="a review-series relation is not one of the canonical values"
      split(line, p, " "); number=p[3]+0
      if (number != entries+1) bad="review-series findings are not numbered consecutively from 1"
      entries++
      sub(/^.*Relation: /, "", line)
      if (prior == "0" && line != "original") bad="a first-round finding must use Relation: original"
      if (prior == "1" && line == "original") bad="a later-round finding cannot use Relation: original"
      next
    }
    inmeta && NF { bad="review-series metadata must contain only canonical mapping entries before Evidence" }
    /^### Scope examined$/ { inscope=1; next }
    /^### / && $0 != "### Scope examined" { inscope=0 }
    inscope && /^- Lens: [a-z-]+ — / {
      lens=$0; sub(/^- Lens: /, "", lens); sub(/ — .*/, "", lens); seen[lens]++
    }
    END {
      if (bad != "") print bad
      else if (metadata != 1) print "the review needs exactly one ## Review series metadata section"
      else if (evidenceLine <= metadataLine || (findings > 0 && metadataLine <= lastresolve)) print "complete contiguous finding blocks must be followed by metadata and then Evidence"
      else if (findings == 0 && (cleanmeta != 1 || entries != 0)) print "a clean review needs exactly \"- none — clean review\" metadata"
      else if (findings > 0 && (entries != findings || cleanmeta != 0)) print "review-series metadata must map every finding exactly once"
      else for (i=1; i<=7; i++) if (seen[wanted[i]] != 1) { print "Scope examined must carry exactly one Lens entry for " wanted[i]; exit }
    }
  ')
  if [ -n "$reason" ]; then printf '%s\n' "$reason"; return 1; fi
  return 0
}

# Where the hook preserves output that never became an accepted round. The gate never reads
# this path, so nothing here can satisfy a state transition; it is retained only for diagnosis.
review_rejected_path() {
  printf '%s/rejected/%s.md' "$(review_series_state_root "$1")" "$2"
}

review_rejected_latest_path() {
  local root="$1" digest="$2" dir path latest="" legacy
  dir="$(review_series_state_root "$root")/rejected/$digest"
  if [ -e "$dir" ] || [ -L "$dir" ]; then
    [ -d "$dir" ] && [ ! -L "$dir" ] || return 1
    for path in "$dir"/*.md; do
      [ -e "$path" ] || [ -L "$path" ] || continue
      [ -f "$path" ] && [ ! -L "$path" ] || return 1
      if [ -z "$latest" ] || [[ "${path##*/}" > "${latest##*/}" ]]; then latest="$path"; fi
    done
  fi
  if [ -n "$latest" ]; then printf '%s' "$latest"; return 0; fi
  legacy=$(review_rejected_path "$root" "$digest")
  [ -f "$legacy" ] && [ ! -L "$legacy" ] || return 1
  printf '%s' "$legacy"
}

# review_rejection_note <root> <digest> — the diagnosis a gate prints when the reviewer ran
# on this exact tree and its output was refused. Returns 1 and prints nothing when there was
# no such rejection, so the caller can fall back to its own message.
review_rejection_note() {
  local path reason
  path=$(review_rejected_latest_path "$1" "$2") || return 1
  [ -f "$path" ] && [ ! -L "$path" ] || return 1
  reason=$(review_header "$path" rejected) || reason="the reason was not recorded"
  printf 'A historical review of this exact tree ran, but its old-format output did not authorize completion:\n'
  printf '  %s\n' "$reason"
  printf '\n'
  printf 'Its retained raw findings remain useful evidence at %s.\n' "${path#"$1"/}"
  printf 'Inspect them before deciding the next step; run a fresh admitted reviewer for authority.\n'
}

# ADR-0051 readers. Historical strict receipts above remain readable; new authority comes from
# immutable attempts whose semantic result is stored beside the raw output.
. "$REVIEW_RECEIPT_DIR/review-workflow.sh" || return 1 2>/dev/null || exit 1

review_current_key() {
  local root="$1" branch session
  branch=$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null) || return 1
  type round_key_for >/dev/null 2>&1 || . "$REVIEW_RECEIPT_DIR/round-ledger.sh" || return 1
  if [ "$branch" = HEAD ] && [ -z "${REVIEW_DETACHED_CONTEXT_ID:-}" ]; then
    session="${CODEX_SESSION_ID:-}"
    [ -n "$session" ] || return 1
    review_detached_context_activate_for_session "$root" "$branch" "$session" 0 || return 1
  fi
  round_key_for "$root" "$branch" 2>/dev/null
}

review_receipt_path() {
  local root="$1" digest="$2" key attempt archive branch head legacy_key
  key=$(review_current_key "$root") || return 1
  attempt=$(review_attempt_latest_for_tree "$root" "$key" "$digest" 2>/dev/null) && {
    printf '%s/raw.md' "$attempt"; return 0;
  }
  type accepted_round_latest_for_tree >/dev/null 2>&1 || . "$REVIEW_RECEIPT_DIR/accepted-rounds.sh" || return 1
  archive=$(accepted_round_latest_for_tree "$root" "$key" "$digest" 2>/dev/null) || {
    branch=$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null) || return 1
    case "$branch" in deliver/*) return 1 ;; esac
    head=$(git -C "$root" rev-parse HEAD 2>/dev/null) || return 1
    legacy_key="nd/$branch/$head"
    archive=$(accepted_round_latest_for_tree "$root" "$legacy_key" "$digest") || return 1
  }
  printf '%s/review.md' "$archive"
}

review_receipt_attempt() {
  local root="$1" digest="$2" key
  key=$(review_current_key "$root") || return 1
  review_attempt_latest_for_tree "$root" "$key" "$digest"
}

review_receipt_validate() {
  local root="$1" digest="$2" current attempt status branch
  current=$(CLAUDE_PROJECT_DIR="$root" "$REVIEW_RECEIPT_DIR/scripts/tree-digest.sh" 2>/dev/null) || return 1
  [ "$digest" = "$current" ] || return 1
  attempt=$(review_receipt_attempt "$root" "$digest" 2>/dev/null) || {
    # Preserve the pre-ADR-0051 strict reader for valid historical receipts.
    local receipt head elapsed
    receipt=$(review_receipt_path "$root" "$digest") || return 1
    [ "$(review_header "$receipt" branch)" = "$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null)" ] || return 1
    head=$(git -C "$root" rev-parse HEAD 2>/dev/null) || return 1
    [ "$(review_header "$receipt" head)" = "$head" ] || return 1
    elapsed=$(review_header "$receipt" elapsed-seconds) || return 1
    case "$elapsed" in ''|*[!0-9]*) return 1 ;; esac
    review_output_validate "$receipt"
    return
  }
  review_attempt_validate_start "$root" "$attempt" || return 1
  status=$(jq -r '.status' "$attempt/completion.json" 2>/dev/null) || return 1
  case "$status" in completed|empty) ;; *) return 1 ;; esac
  branch=$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null) || return 1
  [ "$(jq -r '.branch' "$attempt/start.json")" = "$branch" ] || return 1
}

review_receipt_verdict() {
  local attempt outcome receipt verdict
  attempt=$(review_receipt_attempt "$1" "$2" 2>/dev/null) && {
    outcome=$(jq -r '.outcome' "$attempt/completion.json") || return 1
    case "$outcome" in clean) echo clean ;; ambiguous) echo ambiguous ;; *) echo findings ;; esac
    return
  }
  receipt=$(review_receipt_path "$1" "$2") || return 1
  verdict=$(review_normalize "$receipt" | awk 'NF {line=$0} END{print line}')
  case "$verdict" in "VERDICT: clean — "*) echo clean ;; "VERDICT: findings — "*) echo findings ;; *) return 1 ;; esac
}

review_completion_authorized() {
  local attempt
  attempt=$(review_receipt_attempt "$1" "$2" 2>/dev/null) && {
    review_attempt_authorizes "$1" "$attempt" "$2"
    return
  }
  # Valid strict receipts written before ADR-0051 remain clean authority.
  [ "$(review_receipt_verdict "$1" "$2" 2>/dev/null)" = clean ]
}

review_completion_series() {
  local attempt
  attempt=$(review_receipt_attempt "$1" "$2" 2>/dev/null) || return 1
  jq -er '.seriesId' "$attempt/start.json"
}

review_completion_close() {
  local root="$1" digest="$2" key="${3:-}" attempt series outcome reason
  attempt=$(review_receipt_attempt "$root" "$digest" 2>/dev/null) || attempt=""
  if [ -n "$attempt" ]; then
    series=$(jq -er '.seriesId' "$attempt/start.json") || return 1
    outcome=$(jq -er '.outcome' "$attempt/completion.json") || return 1
    reason=resolved; [ "$outcome" = clean ] && reason=clean
  else
    [ -n "$key" ] || return 0
    series=$(review_series_find_for_key "$root" "$key" 2>/dev/null) || return 0
    [ ! -e "$(review_series_dir "$root" "$series")/closed.json" ] || return 0
    reason=clean
  fi
  review_series_close "$root" "$series" "$reason"
}

review_key_has_history() {
  local root="$1" key="$2" series count rounds branch head legacy_key
  series=$(review_series_find_for_key "$root" "$key" 2>/dev/null) && {
    count=$(review_attempt_count "$root" "$series") || return 1
    [ "$count" -gt 0 ] && return 0
  }
  type accepted_rounds_list >/dev/null 2>&1 || . "$REVIEW_RECEIPT_DIR/accepted-rounds.sh" || return 1
  rounds=$(accepted_rounds_list "$root" "$key") || return 1
  [ -n "$(printf '%s\n' "$rounds" | awk 'NF{print;exit}')" ] && return 0
  case "$key" in
    nd/context-*)
      branch=$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null) || return 1
      head=$(git -C "$root" rev-parse HEAD 2>/dev/null) || return 1
      legacy_key="nd/$branch/$head"
      rounds=$(accepted_rounds_list "$root" "$legacy_key") || return 1
      [ -n "$(printf '%s\n' "$rounds" | awk 'NF{print;exit}')" ]
      ;;
    *) return 1 ;;
  esac
}

# Explain the current missing review transition at public completion entry points.
# This reports evidence; it never changes an attempt or grants authority.
review_completion_diagnose() {
  local root="$1" tree key attempt outcome
  tree=$(CLAUDE_PROJECT_DIR="$root" "${OH_HOME:-$root}/core/scripts/tree-digest.sh") || return 1
  key=$(review_current_key "$root") || {
    echo 'No current review context. Check the branch and round-status.sh; preserve retained evidence and repair admission.' >&2; return 1;
  }
  attempt=$(review_attempt_latest_for_tree "$root" "$key" "$tree" 2>/dev/null) || {
    echo 'No completed review matches this tree. Retain pending output first; otherwise stage current readiness and admit a fresh reviewer within the existing window. Inspect round-status.sh for allowance.' >&2
    return 1
  }
  review_attempt_summary "$attempt" >&2
  if review_attempt_no_result "$root" "$attempt" "$tree"; then
    echo 'The ended reviewer returned no bytes. Admit a fresh reviewer in this series if allowance remains; at the ceiling present its renewal gate.' >&2
    return 0
  fi
  outcome=$(jq -r .outcome "$attempt/completion.json") || return 1
  case "$outcome" in
    blocking*) echo 'Route any scope findings with review-route-scope.sh; fix the blockers and accompanying concerns, verify, then obtain a fresh review.' >&2 ;;
    clean) echo 'A review exists. Check its exact-tree preparation, consumption and staged/committed state; preserve the evidence and use the supported transition to retry.' >&2 ;;
    *)
      if [ -f "$attempt/resolution.json" ]; then
        echo "A disposition is already saved at $attempt/resolution.json. Resume its pending publication/routing/takeover with review-route-scope.sh, or follow its already saved fix/review choice; do not ask for the same decision again." >&2
      elif [ -n "${CODEX_SESSION_ID:-}${CODEX_HOOK:-}" ]; then codex_gate_present review "$outcome" >&2
      else
        echo 'Present a single-select question with these options and their effects:' >&2
        review_choice_labels "$outcome" >&2
      fi ;;
  esac
}
