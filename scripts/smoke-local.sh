#!/usr/bin/env bash
# Wait for the local emulators, then run SDK-level smoke tests.
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0

# wait_for <name> <url> [timeout_s] : waits for HTTP 200
wait_for() {
  local name=$1 url=$2 timeout=${3:-120} code=000 start=$SECONDS
  while (( SECONDS - start < timeout )); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$url")
    if [[ $code == 200 ]]; then echo "OK   $name ready ($((SECONDS - start))s)"; return 0; fi
    sleep 3
  done
  echo "FAIL $name not ready after ${timeout}s (last HTTP $code)"; fail=1
}

# listening <name> <url> : any HTTP status means the port answers
listening() {
  local code; code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$2")
  if [[ $code != 000 ]]; then echo "OK   $1 listening (HTTP $code)"; else echo "FAIL $1 not listening"; fail=1; fi
}

running() { docker compose ps --services --status running | grep -qx "$1"; }

wait_for servicebus http://127.0.0.1:5300/health 180
wait_for cosmos     http://127.0.0.1:8082/ready  180
listening azurite   "http://127.0.0.1:10000/devstoreaccount1?comp=list"
running ollama  && wait_for ollama  http://127.0.0.1:11434/api/version 60
running mailpit && wait_for mailpit http://127.0.0.1:8025/readyz 60

if (( fail )); then echo "SMOKE FAILED (readiness)"; exit 1; fi

./scripts/smoke_emulators.py || { echo "SMOKE FAILED (sdk)"; exit 1; }
echo "SMOKE PASSED"