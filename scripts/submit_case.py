#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""POST an eval case to the ingest API with a fresh ticket id.

Local (default): the Functions host on :7071. Azure: --url https://<app>.azurewebsites.net/api/tickets and the
function key in FUNCTION_KEY (sent as x-functions-key; never on the command line, so it stays out of shell history).

Usage: submit_case.py <case_id> [--cases eval/tickets.jsonl] [--id <ticket_id>] [--url <ingest url>]
Default ticket id: M5-<case_id>-<HHMMSS> (new id each run, so broker duplicate detection doesn't drop it).
"""

import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

parser = argparse.ArgumentParser()
parser.add_argument("case_id")
parser.add_argument("--cases", default=str(ROOT / "eval" / "tickets.jsonl"))
parser.add_argument("--id", dest="ticket_id")
parser.add_argument("--url", default="http://127.0.0.1:7071/api/tickets")
args = parser.parse_args()

cases = {c["ticket_id"]: c for c in map(json.loads, Path(args.cases).read_text().splitlines()) if c}
if args.case_id not in cases:
    raise SystemExit(f"unknown case {args.case_id}; known: {', '.join(sorted(cases))}")
case = cases[args.case_id]
payload = {
    "ticket_id": args.ticket_id or f"M5-{args.case_id}-{datetime.now():%H%M%S}",
    "customer_email": "m5-test@example.com",
    "subject": case["subject"],
    "body": case["body"],
    "channel": "web",
}
headers = {"Content-Type": "application/json"}
if os.environ.get("FUNCTION_KEY"):
    headers["x-functions-key"] = os.environ["FUNCTION_KEY"]
elif not args.url.startswith("http://127.0.0.1"):
    raise SystemExit("set FUNCTION_KEY for a non-local URL")
req = urllib.request.Request(args.url, data=json.dumps(payload).encode(), method="POST", headers=headers)  # noqa: S310
try:
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        status, body = resp.status, resp.read().decode()
except urllib.error.HTTPError as exc:
    status, body = exc.code, exc.read().decode()
print(status, body)
print(f"expected: {case['expected_category']} / {case['expected_priority']}")
