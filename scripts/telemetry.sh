#!/usr/bin/env bash
# The Azure E2E as seen in log-slz-platform (Project 1): App Insights tables of the Function App and the resource
# logs of every resource in rg-triage-azure. Read-only queries as you (az login), via the Log Analytics API.
#
# Usage: scripts/telemetry.sh <start, ISO 8601 UTC> [ticket id prefix, default M8-]
# Ingestion lags: App Insights ~2-5 min, resource logs ~5-15 min after the events.
set -euo pipefail
START=${1:?usage: telemetry.sh <start e.g. 2026-11-11T19:00:00Z> [ticket id prefix]}
PREFIX=${2:-M8-}
[[ $START =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || { echo "start must look like 2026-11-11T19:00:00Z"; exit 2; }
[[ $PREFIX =~ ^[A-Za-z0-9-]+$ ]] || { echo "prefix: letters, digits and hyphens only"; exit 2; }

WS=$(az monitor log-analytics workspace show -g rg-slz-platform -n log-slz-platform --query customerId -o tsv)
WHEN="TimeGenerated between (datetime($START) .. now())"
STACK="_ResourceId contains '/resourcegroups/rg-triage-azure/'"

query() {
  echo "== $1"
  az rest --method post --url "https://api.loganalytics.io/v1/workspaces/$WS/query" \
    --resource https://api.loganalytics.io --body "$(jq -n --arg q "$2" '{query: $q}')" --output json |
    jq -r '.tables[0] | ([.columns[].name] | @tsv), (.rows[] | map(tostring) | @tsv)' | table
  echo
}

table() { if command -v column >/dev/null; then column -t -s $'\t'; else cat; fi; }

query "Function executions (AppRequests)" \
  "AppRequests | where $WHEN | summarize runs = count(), failed = countif(Success == false), p50_ms = round(percentile(DurationMs, 50)) by Name | order by Name asc"
query "Pipeline log lines for $PREFIX tickets (AppTraces)" \
  "AppTraces | where $WHEN | where Message has '$PREFIX' | project TimeGenerated, SeverityLevel, Message | order by TimeGenerated asc | take 40"
query "Exceptions (AppExceptions)" \
  "AppExceptions | where $WHEN | summarize count() by OperationName, ExceptionType"
query "Resource logs of rg-triage-azure by table" \
  "union isfuzzy=true withsource=Table AzureDiagnostics, CDBDataPlaneRequests, StorageBlobLogs, FunctionAppLogs, ACSEmailSendMailOperational, ACSEmailStatusUpdateOperational | where $WHEN | where $STACK | summarize rows = count() by Table | order by Table asc"
query "AzureDiagnostics by provider and category" \
  "AzureDiagnostics | where $WHEN | where $STACK | summarize rows = count() by ResourceProvider, Category | order by ResourceProvider asc"
query "Email delivery (ACS)" \
  "union isfuzzy=true ACSEmailStatusUpdateOperational | where $WHEN | summarize count() by DeliveryStatus"
