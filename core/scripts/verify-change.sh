#!/usr/bin/env bash
# ADR-0052: one selection policy for review, pre-push and CI. Proof: verify-change.test.sh.
set -uo pipefail

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "verify-change: not inside a Git worktree" >&2
  exit 1
}
cd "$ROOT" || exit 1

if [ -n "${OH_HOME:-}" ]; then
  exec "$OH_HOME/oh" --root "$ROOT" verify "${1:-origin/main}" "${2:-review}"
fi

BASE="${1:-origin/main}"
MODE="${2:-review}"
case "$MODE" in
  review|pre-push|ci|plan) ;;
  *) echo "verify-change: mode must be review, pre-push, ci or plan" >&2; exit 2 ;;
esac
git rev-parse --verify "$BASE^{commit}" >/dev/null 2>&1 || {
  echo "verify-change: cannot resolve base $BASE" >&2
  exit 1
}
MERGE_BASE=$(git merge-base HEAD "$BASE" 2>/dev/null) || {
  echo "verify-change: cannot find a merge base with $BASE" >&2
  exit 1
}

CHANGED=$(mktemp) || exit 1
LINTABLE=$(mktemp) || { rm -f "$CHANGED"; exit 1; }
DESIGNS=$(mktemp) || { rm -f "$CHANGED" "$LINTABLE"; exit 1; }
SORTED_DESIGNS=$(mktemp) || { rm -f "$CHANGED" "$LINTABLE" "$DESIGNS"; exit 1; }
LOGS=$(mktemp -d) || { rm -f "$CHANGED" "$LINTABLE" "$DESIGNS" "$SORTED_DESIGNS"; exit 1; }
PIDS=()
cleanup() {
  local pid
  for pid in ${PIDS[@]+"${PIDS[@]}"}; do kill "$pid" 2>/dev/null || true; done
  for pid in ${PIDS[@]+"${PIDS[@]}"}; do wait "$pid" 2>/dev/null || true; done
  rm -f "$CHANGED" "$LINTABLE" "$DESIGNS" "$SORTED_DESIGNS"
  rm -rf "$LOGS"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM

# Include committed branch changes, staged and unstaged edits, and untracked files. Duplicate
# names are harmless and keep this portable across the macOS and Ubuntu Bash/tooling families.
git diff --no-renames --name-only -z "$MERGE_BASE"...HEAD > "$CHANGED" || exit 1
git diff --no-renames --name-only -z >> "$CHANGED" || exit 1
git diff --cached --no-renames --name-only -z >> "$CHANGED" || exit 1
git ls-files --others --exclude-standard -z >> "$CHANGED" || exit 1

full_lint=0
product=0
selector=0 guardrails=0 codex=0 pipeline=0 semantic=0
ci_staging=0
design_full=0
design_count=0
lint_count=0
change_count=0
unknown=0
select_all_harness() { selector=1; guardrails=1; codex=1; pipeline=1; semantic=1; }
while IFS= read -r -d '' path; do
  change_count=$((change_count + 1))
  case "$path" in
    eslint.config.js|package.json|pnpm-lock.yaml|pnpm-workspace.yaml|tools/eslint-rules/*)
      full_lint=1 ;;
  esac
  # Owners first, then their actual shared consumers. Explanatory docs are not executable
  # harness changes. Only known explanatory harness documents are exempt: a new Markdown
  # path still needs an owner, just like a new executable/configuration path.
  case "$path" in
    CLAUDE.md|README.md|core/README.md|.codex/README.md|\
    core/BACKLOG.md|core/RESUME.md|core/recovery-audit.md|core/reviewer-calibration/README.md) ;;
    AGENTS.md|*/AGENTS.md) codex=1 ;;
    core/scripts/verify-change.sh|core/test-fixture.sh|.gitignore)
      select_all_harness ;;
    .github/workflows/delivery.yml) select_all_harness; ci_staging=1 ;;
    core/scripts/verify-change.test.sh) selector=1 ;;
    core/hooks/test.sh) guardrails=1 ;;
    adapters/codex/test.sh) codex=1 ;;
    core/scripts/test.sh) pipeline=1 ;;
    core/review-workflow.test.sh) semantic=1 ;;
    core/scripts/review-calibration.sh) pipeline=1 ;;
    core/scripts/review-dashboard.mjs) pipeline=1; semantic=1 ;;
    core/scripts/verify-docs.sh) pipeline=1; selector=1 ;;
    core/scripts/start.sh|adapters/codex/task-grant.sh) pipeline=1; codex=1 ;;
    core/lib.sh|core/hooks/lib.sh|core/*-ledger.sh|core/accepted-rounds.sh|\
    core/review-*.sh|core/review-*.txt|core/delivery-policy.json|\
    core/scripts/next.sh|core/scripts/plan.sh|core/scripts/roadmap.sh|core/scripts/tree-digest.sh|\
    core/scripts/review-*.sh|core/scripts/round-status.sh|\
    core/scripts/task-status.sh|core/scripts/codex-gate.sh|\
    core/hooks/review-*.sh|core/hooks/round-*.sh|core/hooks/task-grant.sh)
      select_all_harness ;;
    core/hooks/*) guardrails=1; codex=1 ;;
    core/settings.json) guardrails=1 ;;
    prompts/*) semantic=1; codex=1 ;;
    workflows/design/SKILL.md) pipeline=1; semantic=1; codex=1 ;;
    workflows/*) pipeline=1; codex=1 ;;
    core/scripts/complete.sh|core/scripts/freeze.sh|core/scripts/claim.sh)
      pipeline=1; semantic=1 ;;
    core/scripts/*|core/reviewer-calibration/*) pipeline=1 ;;
    .codex/*|.agents/skills/*) codex=1 ;;
    .githooks/pre-push) guardrails=1; selector=1 ;;
    .githooks/commit-msg) pipeline=1; semantic=1 ;;
    .githooks/prepare-commit-msg) semantic=1 ;;
    .github/workflows/pr.yml) product=1; ci_staging=1; selector=1 ;;
    .github/scripts/*) product=1; ci_staging=1 ;;
    .github/verify-ci-staging*) ci_staging=1 ;;
    core/*|.github/*|.githooks/*|.agents/*)
      printf 'verify-change: unclassified harness/CI path: %q\n' "$path" >&2
      case "$path" in
        .github/*) echo 'Recommended owner: product CI; alternative: harness verification.' >&2 ;;
        *) echo 'Recommended owner: shared harness; alternatives: host adapter or product CI.' >&2 ;;
      esac
      unknown=1 ;;
    */README.md) ;;
    apps/*|packages/*|e2e/*|tools/*|infra/*|package.json|pnpm-lock.yaml|pnpm-workspace.yaml|\
    turbo.json|tsconfig*.json|eslint.config.js|docker-compose*.yml|docker-compose*.yaml|\
    .dockerignore|.env.example|.prettierignore|.prettierrc.json)
      product=1 ;;
  esac
  case "$path" in
    docs/design/[0-9][0-9][0-9][0-9]-*.md)
      if [ -f "$path" ]; then
        basename "$path" | cut -c1-4 >> "$DESIGNS"
        design_count=$((design_count + 1))
      else
        design_full=1
      fi ;;
  esac
  case "$path" in
    docs/reference/testing.md)
      ci_staging=1 ;;
  esac
  case "$path" in
    *.js|*.jsx|*.mjs|*.cjs|*.ts|*.tsx|*.mts|*.cts)
      if [ -f "$path" ]; then
        printf '%s\0' "$path" >> "$LINTABLE"
        lint_count=$((lint_count + 1))
      fi ;;
  esac
done < "$CHANGED"

if [ "$unknown" = 1 ]; then
  echo 'No checks ran. Derive the evident owner from callers/dependencies, update this tracked selection rule and its coverage, then rerun. Ask the human only if ownership is ambiguous; no per-run override.' >&2
  exit 2
fi

lint=0
if [ "$full_lint" = 1 ] || [ "$lint_count" -gt 0 ]; then lint=1; fi
if [ "$MODE" = plan ]; then
  # Fixed keys/values only: safe to append to GITHUB_OUTPUT. Unknown paths fail above.
  printf 'product=%s\nlint=%s\nselector=%s\nguardrails=%s\ncodex=%s\npipeline=%s\nsemantic=%s\nci_staging=%s\n' \
    "$product" "$lint" "$selector" "$guardrails" "$codex" "$pipeline" "$semantic" "$ci_staging"
  exit 0
fi

failed=""
step() {
  local label="$1" output show_output=0
  shift
  if [ "${1:-}" = --show-output ]; then show_output=1; shift; fi
  printf '  run   %s\n' "$label"
  if output=$("$@" 2>&1); then
    printf '  ok    %s\n' "$label"
    if [ "$show_output" = 1 ] && [ -n "$output" ]; then
      printf '%s\n' "$output" | sed 's/^/        /'
    fi
  else
    printf '  FAIL  %s\n' "$label"
    [ -z "$output" ] || printf '%s\n' "$output" | sed 's/^/        /'
    failed="${failed}${failed:+, }$label"
  fi
}
lint_changed() { xargs -0 pnpm exec eslint -- < "$LINTABLE"; }
affected_packages() { TURBO_SCM_BASE="$BASE" pnpm exec turbo run typecheck test --affected; }

echo "affected verification ($BASE, $MODE):"
# Product PR CI owns its full lint/typecheck/test and environment-dependent checks. For a
# harness-only JS change, process CI still runs the same changed-file lint as local review.
if [ "$MODE" = ci ] && [ "$product" = 1 ]; then
  :
elif [ "$full_lint" = 1 ]; then
  step "lint" pnpm lint
elif [ "$lint_count" -gt 0 ]; then
  step "changed-file lint" lint_changed
fi

if [ "$product" = 1 ] && [ "$MODE" != ci ]; then
  # Keep Turbo's cache hits/misses and suite timings visible on successful runs too.
  # A replayed pass is useful evidence, but it is not another fresh test execution.
  step "affected typecheck + tests" --show-output affected_packages
fi

# At most two independent suites at once. Separate logs keep failures readable; each pair
# is joined before starting another. No generation or repository transition runs in parallel.
SUITES=()
[ "$selector" = 0 ] || SUITES+=(core/scripts/verify-change.test.sh)
[ "$guardrails" = 0 ] || SUITES+=(core/hooks/test.sh)
[ "$codex" = 0 ] || SUITES+=(adapters/codex/test.sh)
[ "$pipeline" = 0 ] || SUITES+=(core/scripts/test.sh)
[ "$semantic" = 0 ] || SUITES+=(core/review-workflow.test.sh)
join_suites() {
  local index label
  for ((index=0; index<${#PIDS[@]}; index++)); do
    label="${LABELS[$index]}"
    if wait "${PIDS[$index]}"; then
      printf '  ok    %s\n' "$label"
    else
      printf '  FAIL  %s\n' "$label"
      sed 's/^/        /' "$LOGS/$index.log"
      failed="${failed}${failed:+, }$label"
    fi
  done
  PIDS=()
  LABELS=()
}
LABELS=()
for suite in ${SUITES[@]+"${SUITES[@]}"}; do
  printf '  run   %s\n' "$suite"
  (
    unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
      GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_COMMON_DIR GIT_NAMESPACE GIT_PREFIX
    exec bash "$suite"
  ) > "$LOGS/${#PIDS[@]}.log" 2>&1 &
  PIDS+=("$!")
  LABELS+=("$suite")
  [ "${#PIDS[@]}" -lt 2 ] || join_suites
done
join_suites

if [ "$ci_staging" = 1 ]; then
  step "CI staging tests" node --test .github/verify-ci-staging.test.mjs
  step "CI staging contract" node .github/verify-ci-staging.mjs
fi

if [ "$change_count" -gt 0 ] || [ "$MODE" = ci ]; then
  step "doc lifecycle" core/scripts/verify-docs.sh "$BASE"
  step "roadmap registry" core/scripts/verify-roadmap.sh "$BASE"
  if [ "$MODE" = review ] && [ "$design_count" -gt 0 ] && [ "$design_full" = 0 ]; then
    LC_ALL=C sort -u "$DESIGNS" > "$SORTED_DESIGNS" || exit 1
    while IFS= read -r design; do
      [ -n "$design" ] && step "design $design" core/scripts/verify-design.sh --review "$design"
    done < "$SORTED_DESIGNS"
  else
    step "design docs" core/scripts/verify-design.sh
  fi
fi

if [ "$MODE" = pre-push ] || [ "$MODE" = ci ]; then
  step "delivery process" core/scripts/verify-delivery.sh "$BASE"
fi

if [ -n "$failed" ]; then
  echo "" >&2
  echo "REFUSED — $failed" >&2
  exit 1
fi

exit 0
