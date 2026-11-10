#!/usr/bin/env bash
# Protect main: PR required (0 approvals, solo repo), strict required checks pinned to the GitHub Actions app,
# admins included, linear history, conversations resolved, no force-push or deletion.
# The required checks are read from a commit whose CI is green, so a typo can't leave main waiting forever.
#
# Usage: ./scripts/protect-main.sh <ref with green CI, e.g. m6-ci>   (needs gh with repo scope, and jq)
set -euo pipefail

REPO=${REPO:-salmanamn/ticket-triage-agent}
REF=${1:?usage: protect-main.sh <ref with green CI>}
CHECKS=(lint unit integration tests-must-fail)

runs=$(gh api "repos/$REPO/commits/$REF/check-runs?per_page=100" \
  --jq '.check_runs[] | [.name, (.conclusion // "pending"), (.app.id | tostring)] | @tsv')

app_id=""
for check in "${CHECKS[@]}"; do
  line=$(awk -F'\t' -v name="$check" '$1 == name' <<<"$runs" | head -1)
  if [[ -z $line ]]; then echo "FAIL check '$check' has not run on $REF"; exit 1; fi
  IFS=$'\t' read -r _ conclusion id <<<"$line"
  if [[ $conclusion != success ]]; then echo "FAIL check '$check' on $REF is '$conclusion'"; exit 1; fi
  if [[ -n $app_id && $id != "$app_id" ]]; then echo "FAIL checks come from different apps"; exit 1; fi
  app_id=$id
  echo "OK   $check: success (app $id)"
done

jq -n --argjson app "$app_id" '{
  required_status_checks: {strict: true, checks: ($ARGS.positional | map({context: ., app_id: $app}))},
  enforce_admins: true,
  required_pull_request_reviews: {required_approving_review_count: 0},
  restrictions: null,
  required_linear_history: true,
  allow_force_pushes: false,
  allow_deletions: false,
  required_conversation_resolution: true
}' --args "${CHECKS[@]}" |
  gh api -X PUT "repos/$REPO/branches/main/protection" --input - --jq '{
    strict: .required_status_checks.strict,
    checks: [.required_status_checks.checks[] | "\(.context) (app \(.app_id))"],
    pr_required: (.required_pull_request_reviews != null),
    enforce_admins: .enforce_admins.enabled,
    linear_history: .required_linear_history.enabled,
    force_pushes: .allow_force_pushes.enabled,
    deletions: .allow_deletions.enabled
  }'