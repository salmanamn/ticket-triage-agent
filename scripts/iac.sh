#!/usr/bin/env bash
# Terraform helpers. CI (.github/workflows/ci.yml) runs the same commands as the laptop.
#
#   install-tools   CI only (Linux x86_64): Checkov via uv, Conftest from its GitHub release
#   static          fmt · validate (both envs) · Checkov per root · Conftest policy unit tests   (CI: iac-static)
#   wait-floci      wait until floci-az serves its TLS certificate
#   gate            full-stack plan of envs/local against floci-az -> Conftest -> iac_must_fail  (CI: iac-plan)
#   apply-local     rebuild the floci-az subset: destroy, then apply (create/destroy only, D18)
#   destroy-local   destroy the floci-az subset
#   plan-azure      plan envs/azure with the shared remote state (az login; needs terraform.tfvars)
set -euo pipefail
cd "$(dirname "$0")/.."

CHECKOV_VERSION=3.4.3
CONFTEST_VERSION=0.62.0
ENVS=(infra/envs/local infra/envs/azure)
LOCAL=infra/envs/local
AZURE=infra/envs/azure
POLICY=infra/policy
export TF_IN_AUTOMATION=1 CHECKPOINT_DISABLE=1

install_tools() {
  uv tool install --quiet "checkov==${CHECKOV_VERSION}"
  curl -sSfL "https://github.com/open-policy-agent/conftest/releases/download/v${CONFTEST_VERSION}/conftest_${CONFTEST_VERSION}_Linux_x86_64.tar.gz" |
    sudo tar -xz -C /usr/local/bin conftest
  checkov --version && conftest --version | head -1
}

# envs/local has no backend: its init downloads the providers once; later runs reuse them (no registry access).
init_local() {
  [[ -d $LOCAL/.terraform/providers ]] || terraform -chdir="$LOCAL" init -input=false -no-color >/dev/null
}

static() {
  local d rc=0
  [[ $(checkov --version) == "$CHECKOV_VERSION" ]] || { echo "FAIL checkov $(checkov --version) != $CHECKOV_VERSION (uv tool install checkov==$CHECKOV_VERSION)"; return 1; }

  terraform fmt -recursive -check -diff infra
  echo "OK   terraform fmt"

  init_local
  terraform -chdir="$LOCAL" validate -no-color >/dev/null
  echo "OK   terraform validate $LOCAL"
  # envs/azure: separate data dir (never touch its real backend init, Project 1 gotcha), providers copied
  # from envs/local with -plugin-dir, so this needs no registry access and no second 250 MB download.
  TF_DATA_DIR=.terraform-validate terraform -chdir="$AZURE" init -backend=false -input=false -no-color \
    -plugin-dir="$PWD/$LOCAL/.terraform/providers" >/dev/null
  TF_DATA_DIR=.terraform-validate terraform -chdir="$AZURE" validate -no-color >/dev/null
  echo "OK   terraform validate $AZURE"

  for d in "${ENVS[@]}"; do
    if checkov -d "$d" --framework terraform --compact --quiet >/tmp/checkov.out 2>/dev/null; then
      echo "OK   checkov $d ($(grep -o 'Passed checks: [0-9]*, Failed checks: [0-9]*, Skipped checks: [0-9]*' /tmp/checkov.out))"
    else
      cat /tmp/checkov.out
      echo "FAIL checkov $d"
      rc=1
    fi
  done

  conftest verify --no-color --policy "$POLICY" | tail -1
  return $rc
}

wait_floci() {
  local i
  for i in $(seq 1 60); do
    if curl -sf http://localhost:4577/_floci/tls-cert -o /dev/null; then echo "OK   floci-az up (${i}x2s)"; return 0; fi
    sleep 2
  done
  echo "FAIL floci-az not reachable on :4577"
  return 1
}

floci_reachable() {
  curl -sf https://localhost:4577/metadata/endpoints >/dev/null || {
    echo "floci-az not reachable over TLS: docker compose --profile iac up -d floci-az && ./scripts/trust-floci-cert.sh"
    exit 1
  }
}

gate() {
  floci_reachable
  init_local
  # Fresh plan of every component. Plan only: floci-az 0.16.0 can't create half of them (D18).
  terraform -chdir="$LOCAL" plan -input=false -no-color -var full_stack=true -out=full.tfplan | grep -E '^Plan:'
  terraform -chdir="$LOCAL" show -json full.tfplan >"$LOCAL/plan.json"
  conftest test --no-color --policy "$POLICY" "$LOCAL/plan.json" | grep -E "^FAIL|tests,"
  python3 scripts/iac_must_fail.py "$LOCAL/plan.json"
}

apply_local() {
  floci_reachable
  init_local
  # floci-az doesn't persist several properties, so updates in place drift; rebuild instead (D18).
  terraform -chdir="$LOCAL" destroy -auto-approve -refresh=false -no-color >/dev/null || {
    echo "destroy failed: resetting local state (emulator only)"
    rm -f "$LOCAL/terraform.tfstate" "$LOCAL/terraform.tfstate.backup"
  }
  terraform -chdir="$LOCAL" apply -auto-approve -input=false -no-color | grep -E '^Apply complete|Error'
  terraform -chdir="$LOCAL" state list
}

destroy_local() {
  floci_reachable
  terraform -chdir="$LOCAL" destroy -auto-approve -no-color | grep -E '^Destroy complete|Error'
}

plan_azure() {
  [[ -f $AZURE/terraform.tfvars ]] || { echo "cp $AZURE/terraform.tfvars.example $AZURE/terraform.tfvars and set subscription_id"; exit 1; }
  init_local # envs/azure installs the same providers from envs/local: only the state account needs the network
  terraform -chdir="$AZURE" init -input=false -no-color -backend-config=backend.hcl \
    -plugin-dir="$PWD/$LOCAL/.terraform/providers" >/dev/null
  terraform -chdir="$AZURE" plan -input=false -no-color -out=azure.tfplan | grep -E '^Plan:|Error'
  terraform -chdir="$AZURE" show -json azure.tfplan >"$AZURE/plan.json"
  conftest test --no-color --policy "$POLICY" "$AZURE/plan.json" | grep -E "^FAIL|tests,"
}

case "${1:-}" in
  install-tools) install_tools ;;
  static) static ;;
  wait-floci) wait_floci ;;
  gate) gate ;;
  apply-local) apply_local ;;
  destroy-local) destroy_local ;;
  plan-azure) plan_azure ;;
  *) echo "usage: $0 install-tools | static | wait-floci | gate | apply-local | destroy-local | plan-azure" >&2; exit 2 ;;
esac