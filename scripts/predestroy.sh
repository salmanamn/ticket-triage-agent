#!/usr/bin/env bash
# Delete what Azure creates in the stack's resource group on its own, so `terraform destroy` can delete the RG
# (envs/azure keeps prevent_deletion_if_contains_resources = true: anything else left over still fails loudly, D22).
#   - "Application Insights Smart Detection" action group, created with the App Insights component
# Usage: scripts/predestroy.sh <resource group>   (az signed in)
set -euo pipefail
RG=${1:?usage: predestroy.sh <resource group>}
if [[ $(az group exists --name "$RG") != true ]]; then echo "OK   $RG does not exist"; exit 0; fi
ids=$(az resource list -g "$RG" --resource-type microsoft.insights/actiongroups \
  --query "[?name=='Application Insights Smart Detection'].id" -o tsv)
if [[ -z $ids ]]; then echo "OK   no generated action group in $RG"; exit 0; fi
while IFS= read -r id; do # the name has spaces: one id per line, quoted
  az resource delete --ids "$id" --output none
  echo "OK   deleted ${id##*/}"
done <<<"$ids"
