#!/usr/bin/env bash
# CI helpers for the emulator service containers (.github/workflows/ci.yml).
#
#   start-servicebus <network>  run the Service Bus emulator on the job's service network. It is not a service
#                               container: those start before checkout, so the repo's config.json can't be mounted.
#   wait                        wait for Service Bus, Cosmos and Mailpit, then run the SDK smoke test
#   logs                        print the tail of every container's log (on failure)
#   check-images                every emulator image in ci.yml must be pinned identically in docker-compose.yml
set -euo pipefail
cd "$(dirname "$0")/.."

start_servicebus() {
  local network=${1:?usage: ci-emulators.sh start-servicebus <network>}
  docker run -d --name servicebus --network "$network" \
    -e SQL_SERVER=mssql \
    -e MSSQL_SA_PASSWORD="${MSSQL_SA_PASSWORD:?MSSQL_SA_PASSWORD not set}" \
    -e ACCEPT_EULA=Y \
    -e EMULATOR_HTTP_PORT=5300 \
    -v "$PWD/emulators/servicebus/config.json:/ServiceBus_Emulator/ConfigFiles/Config.json:ro" \
    -p 127.0.0.1:5672:5672 -p 127.0.0.1:5300:5300 \
    "${SERVICEBUS_IMAGE:?SERVICEBUS_IMAGE not set}"
}

# wait_for <name> <url> <timeout_s> : waits for HTTP 200
wait_for() {
  local name=$1 url=$2 timeout=$3 code=000 start=$SECONDS
  while (( SECONDS - start < timeout )); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$url" || true)
    if [[ $code == 200 ]]; then echo "OK   $name ready ($((SECONDS - start))s)"; return 0; fi
    sleep 3
  done
  echo "FAIL $name not ready after ${timeout}s (last HTTP $code)"
  return 1
}

wait_all() {
  wait_for servicebus http://127.0.0.1:5300/health 240
  wait_for cosmos http://127.0.0.1:8082/ready 240
  wait_for mailpit http://127.0.0.1:8025/readyz 60
  ./scripts/smoke_emulators.py
}

logs() {
  local name
  for name in $(docker ps -a --format '{{.Names}}'); do
    echo "::group::docker logs $name"
    docker logs --tail 200 "$name" 2>&1 || true
    echo "::endgroup::"
  done
}

check_images() {
  local img fail=0 count=0
  while read -r img; do
    count=$((count + 1))
    if grep -qE "^[[:space:]]+image: ${img//./\\.}[[:space:]]*$" docker-compose.yml; then
      echo "OK   $img"
    else
      echo "FAIL $img is not pinned the same way in docker-compose.yml"
      fail=1
    fi
  done < <(grep -oE '(mcr\.microsoft\.com|axllent|floci)/[^"[:space:]]+' .github/workflows/ci.yml | sort -u)
  (( count > 0 )) || { echo "FAIL no emulator images found in ci.yml"; return 1; }
  return $fail
}

case "${1:-}" in
  start-servicebus) start_servicebus "${2:-}" ;;
  wait) wait_all ;;
  logs) logs ;;
  check-images) check_images ;;
  *) echo "usage: $0 start-servicebus <network> | wait | logs | check-images" >&2; exit 2 ;;
esac