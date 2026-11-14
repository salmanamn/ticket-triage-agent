#!/usr/bin/env bash
# azurerm 4.81's azurerm_function_app_flex_consumption always writes AzureWebJobsStorage as an account-key connection
# string, with an empty key when storage_authentication_type is a managed identity. The host prefers that string over
# the identity-based AzureWebJobsStorage__* settings, signs with the empty key and never starts ("MAC signature ... is
# not the same", 403 on azure-webjobs-secrets). Remove it after every apply; azurerm's refresh ignores its absence,
# so this causes no drift (D23).
# Usage: scripts/fix-host-storage.sh <resource group>   (az signed in)
set -euo pipefail
RG=${1:?usage: fix-host-storage.sh <resource group>}
app=$(az functionapp list -g "$RG" --query "[0].name" -o tsv)
[[ -n $app ]] || { echo "OK   no function app in $RG"; exit 0; }
if [[ -z $(az functionapp config appsettings list -g "$RG" -n "$app" --query "[?name=='AzureWebJobsStorage'].name" -o tsv) ]]; then
  echo "OK   $app has no key-based AzureWebJobsStorage"
  exit 0
fi
az functionapp config appsettings delete -g "$RG" -n "$app" --setting-names AzureWebJobsStorage --output none
az functionapp restart -g "$RG" -n "$app"
echo "OK   removed azurerm's key-based AzureWebJobsStorage from $app and restarted it"