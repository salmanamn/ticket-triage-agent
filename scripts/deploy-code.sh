#!/usr/bin/env bash
# Package src/ and deploy it to the stack's Flex Consumption app with a remote build (Python, D1/D21).
# The platform builds requirements.txt on Linux and stores the package in the app-package container with the
# app's own identity; the deployer only needs the site's publish action (CI: id-slz-apply, Contributor).
# Usage: scripts/deploy-code.sh <resource group>   (az signed in)
set -euo pipefail
cd "$(dirname "$0")/.."
RG=${1:?usage: deploy-code.sh <resource group>}
EXPECTED=(health notify_ticket submit_ticket triage_ticket)

app=$(az functionapp list -g "$RG" --query "[0].name" -o tsv)
[[ -n $app ]] || { echo "FAIL no function app in $RG: run the apply first"; exit 1; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
(cd src && zip -qr "$work/app.zip" . -x 'local.settings.json*' 'azure.settings.json' '*__pycache__*' '.venv/*' '.python_packages/*')
echo "OK   package: $(unzip -l "$work/app.zip" | tail -1 | awk '{print $2}') files"

az functionapp deployment source config-zip -g "$RG" -n "$app" --src "$work/app.zip" --build-remote true --timeout 900 --output none
echo "OK   deployed to $app (remote build done)"

# The host indexes the functions after the restart; Event Grid can only validate notify_ticket once it is listed.
for _ in $(seq 1 30); do
  found=$(az functionapp function list -g "$RG" -n "$app" --query "[].name" -o tsv | sed 's|.*/||' | LC_ALL=C sort | tr '\n' ' ')
  [[ $found == "${EXPECTED[*]} " ]] && { echo "OK   functions: $found"; exit 0; }
  sleep 10
done
echo "FAIL functions after 5 min: '${found:-none}', expected: ${EXPECTED[*]}"
exit 1
