#!/usr/bin/env bash
# Trust floci-az's self-signed TLS certificate (azurerm only talks HTTPS to a custom cloud).
# Re-run after every new floci-az container or data directory: the certificate changes with it.
# Same file name as Project 1, so the cert of the lab that ran last is the trusted one.
set -euo pipefail
crt=$(mktemp)
trap 'rm -f "$crt"' EXIT
curl -sf http://localhost:4577/_floci/tls-cert -o "$crt"
grep -q "BEGIN CERTIFICATE" "$crt" || { echo "No cert: is FLOCI_AZ_TLS_ENABLED=true?"; exit 1; }
sudo install -m 644 "$crt" /usr/local/share/ca-certificates/floci-az.crt
sudo update-ca-certificates --fresh >/dev/null
curl -sf https://localhost:4577/metadata/endpoints >/dev/null && echo "floci-az cert trusted"