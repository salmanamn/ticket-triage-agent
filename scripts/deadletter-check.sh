#!/usr/bin/env bash
# D25 on the deployed stack. Read-only, as you (az login):
#   1. every role assignment of the Event Grid topic's identity (expected: one, on the dead-letter account)
#   2. failed deliveries and dead-lettered events as Event Grid counts them (topic metrics)
#   3. blob writes per storage account and caller, from StorageBlobLogs in log-slz-platform
#
# Usage: scripts/deadletter-check.sh <start, ISO 8601 UTC>
# Lags: metrics 2-5 min, StorageBlobLogs 5-15 min. Event Grid writes a dead-letter 5 min after the last attempt.
set -euo pipefail
START=${1:?usage: deadletter-check.sh <start e.g. 2026-11-15T18:00:00Z>}
[[ $START =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || { echo "start must look like 2026-11-15T18:00:00Z"; exit 2; }
RG=${RESOURCE_GROUP:-rg-triage-azure}

topic_id=$(az eventgrid topic list -g "$RG" --query "[0].id" -o tsv)
principal=$(az eventgrid topic list -g "$RG" --query "[0].identity.principalId" -o tsv)
[[ -n $topic_id && -n $principal ]] || { echo "FAIL no Event Grid topic with a managed identity in $RG"; exit 1; }

echo "== Role assignments of the topic identity"
# Listed for the whole subscription and filtered here (no directory lookup); scopes printed without the subscription.
roles=$(az role assignment list --all --query "[?principalId=='$principal'].[roleDefinitionName, scope]" -o tsv |
  sed -E 's|/subscriptions/[^/]+/resourceGroups/[^/]+/providers/||')
echo "${roles:-none}"
if [[ $(grep -c . <<<"$roles") == 1 && $roles == "Storage Blob Data Contributor"$'\t'"Microsoft.Storage/storageAccounts/stdl"* ]]; then
  echo "OK   one role, on the dead-letter storage account"
else
  echo "FAIL expected exactly one role: Storage Blob Data Contributor on the stdl... storage account"
fi
echo

metric() { # <metric name>: total since START
  az monitor metrics list --resource "$topic_id" --metric "$1" --aggregation Total --interval PT1M --start-time "$START" \
    --query "value[0].timeseries[].data[].total" -o tsv | awk '{ sum += $1 } END { print sum + 0 }'
}
echo "== Event Grid topic metrics since $START"
printf 'DeliveryAttemptFailCount  %s\n' "$(metric DeliveryAttemptFailCount)"
printf 'DeadLetteredCount         %s\n' "$(metric DeadLetteredCount)"
echo

WS=$(az monitor log-analytics workspace show -g rg-slz-platform -n log-slz-platform --query customerId -o tsv)
QUERY="StorageBlobLogs
| where TimeGenerated between (datetime($START) .. now())
| where _ResourceId contains '/resourcegroups/$RG/'
| where Category == 'StorageWrite'
| extend Caller = iff(RequesterObjectId == '$principal', 'eventgrid-topic', 'other')
| summarize Writes = count(), Succeeded = countif(StatusText == 'Success') by AccountName, Caller, OperationName
| order by AccountName asc, Caller asc, OperationName asc"
echo "== Blob writes per storage account and caller (StorageBlobLogs)"
az rest --method post --url "https://api.loganalytics.io/v1/workspaces/$WS/query" \
  --resource https://api.loganalytics.io --body "$(jq -n --arg q "$QUERY" '{query: $q}')" --output json |
  jq -r '.tables[0] | ([.columns[].name] | @tsv), (.rows[] | map(tostring) | @tsv)' |
  if command -v column >/dev/null; then column -t -s $'\t'; else cat; fi