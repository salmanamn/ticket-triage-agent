#!/usr/bin/env bash
# Dispatch deploy.yml from the laptop, show the plan, approve the `azure` environment, follow the run (D21).
# Same flow as secure-landing-zone's ci-deploy.sh, plus deploy-code and the notify switch.
#
# Usage: scripts/ci-deploy.sh apply [--notify] | destroy | deploy-code
#   apply             stack without the Event Grid notify subscription (first apply of a session)
#   apply --notify    stack + notify subscription (after deploy-code: Event Grid validates notify_ticket)
set -euo pipefail

ACTION=${1:?usage: $0 apply [--notify] | destroy | deploy-code}
NOTIFY=false
[[ ${2:-} == --notify ]] && NOTIFY=true
[[ $ACTION =~ ^(apply|destroy|deploy-code)$ ]] || { echo "unknown action $ACTION"; exit 2; }
REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)

since=$(date -u -d "-60 sec" +%Y-%m-%dT%H:%M:%SZ) # tolerate a little clock skew vs GitHub
gh workflow run deploy.yml --ref main -f action="$ACTION" -f notify="$NOTIFY"
RUN_ID=""
for _ in $(seq 1 20); do
  sleep 3
  RUN_ID=$(gh run list --workflow deploy.yml --event workflow_dispatch --limit 5 --json databaseId,createdAt \
    --jq "[.[] | select(.createdAt >= \"$since\")][0].databaseId // empty")
  [[ -n $RUN_ID ]] && break
done
[[ -n $RUN_ID ]] || { echo "the dispatched run didn't show up"; exit 1; }
URL="https://github.com/$REPO/actions/runs/$RUN_ID"
echo "run: $URL ($ACTION, notify=$NOTIFY)"

if [[ $ACTION != deploy-code ]]; then
  job() { gh run view "$RUN_ID" --json jobs --jq ".jobs[] | select(.name==\"plan\") | .$1"; }
  until [[ $(job status) == completed ]]; do sleep 10; done
  # Job logs via API: available as soon as the job finishes, even while the run waits for approval.
  gh api "repos/$REPO/actions/jobs/$(job databaseId)/logs" | grep -E 'Plan:|No changes|tests,|^.{29}FAIL' | cut -c30- || true
  [[ $(job conclusion) == success ]] || { echo "plan failed: $URL"; exit 1; }
fi

for _ in $(seq 1 30); do
  [[ $(gh api "repos/$REPO/actions/runs/$RUN_ID/pending_deployments" --jq length) -gt 0 ]] && break
  if [[ $(gh run view "$RUN_ID" --json status --jq .status) == completed ]]; then
    echo "no changes, nothing to approve"
    exit 0
  fi
  sleep 5
done

read -rp "Approve $ACTION? [y/N] " ok
STATE=$([[ ${ok:-n} == y ]] && echo approved || echo rejected)
ENV_ID=$(gh api "repos/$REPO/environments/azure" --jq .id)
BODY=$(printf '{"environment_ids":[%s],"state":"%s","comment":"%s via ci-deploy.sh"}' "$ENV_ID" "$STATE" "$ACTION")
STATUS=$(gh api -X POST -i "repos/$REPO/actions/runs/$RUN_ID/pending_deployments" --input - <<<"$BODY" 2>&1 | head -n 1) || true
echo "approval POST: $STATUS"

sleep 3
RECORDED=$(gh api "repos/$REPO/actions/runs/$RUN_ID/approvals" --jq "[.[] | select(.state==\"$STATE\")] | length")
[[ $RECORDED -gt 0 ]] || { echo "approval not recorded; approve in the browser: $URL"; exit 1; }
echo "$STATE"

[[ $STATE == approved ]] && gh run watch "$RUN_ID" --exit-status --interval 15 >/dev/null && echo "run succeeded: $URL"
