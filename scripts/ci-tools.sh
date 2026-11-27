#!/usr/bin/env bash
# Pinned tools for CI (D31), each checked against a SHA-256 before it is installed (same versions and checksums as
# Project 4's scripts/ci-tools.sh).  ./scripts/ci-tools.sh helm trivy
# Helm publishes its binaries only on get.helm.sh, so its checksum comes from there too: it catches a broken
# download, not a compromised release. Trivy's checksum is written here, from its GitHub release.
set -euo pipefail
HELM_VERSION=v4.3.2
TRIVY_VERSION=0.76.2
TRIVY_SHA256=bc0fc726e017b8927a62b2d3531d7a84ee01769daf5c99ed866dced54089fdbf

bin=${CI_TOOLS_BIN:-$HOME/.local/bin}
mkdir -p "$bin"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

fetch() { # URL SHA256 FILE
  curl -fsSL --retry 5 --retry-all-errors -o "$work/$3" "$1"
  echo "$2  $work/$3" | sha256sum -c --quiet -
}

for tool in "$@"; do
  case $tool in
    helm)
      file=helm-$HELM_VERSION-linux-amd64.tar.gz
      sum=$(curl -fsSL --retry 5 "https://get.helm.sh/$file.sha256sum" | awk '{print $1}')
      fetch "https://get.helm.sh/$file" "$sum" "$file"
      tar -xzf "$work/$file" -C "$work" linux-amd64/helm && install -m 0755 "$work/linux-amd64/helm" "$bin/helm"
      ;;
    trivy)
      file=trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz
      fetch "https://github.com/aquasecurity/trivy/releases/download/v$TRIVY_VERSION/$file" "$TRIVY_SHA256" "$file"
      tar -xzf "$work/$file" -C "$work" trivy && install -m 0755 "$work/trivy" "$bin/trivy"
      ;;
    *)
      echo "unknown tool: $tool" >&2
      exit 2
      ;;
  esac
  echo "installed $tool: $bin/$tool"
done