#!/usr/bin/env bash
# CI only: sign the Azure CLI in as $ARM_CLIENT_ID with this job's GitHub OIDC token (no secret, no extra action).
# Needs `permissions: id-token: write` and ARM_CLIENT_ID / ARM_TENANT_ID / ARM_SUBSCRIPTION_ID in the environment.
set -euo pipefail
: "${ACTIONS_ID_TOKEN_REQUEST_URL:?no OIDC token endpoint: the job needs permissions: id-token: write}"
token=$(curl -sSf -H "Authorization: bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}" \
  "${ACTIONS_ID_TOKEN_REQUEST_URL}&audience=api://AzureADTokenExchange" | jq -r .value)
az login --service-principal --username "$ARM_CLIENT_ID" --tenant "$ARM_TENANT_ID" --federated-token "$token" --output none
az account set --subscription "$ARM_SUBSCRIPTION_ID"
echo "OK   az signed in as ${ARM_CLIENT_ID:0:8}…"
