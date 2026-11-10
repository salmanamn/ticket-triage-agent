#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""List (or clear) messages in the local Mailpit inbox via its API.

Usage: inbox.py [--clear]
"""

import argparse
import json
import urllib.request

API = "http://127.0.0.1:8025/api/v1/messages"

parser = argparse.ArgumentParser()
parser.add_argument("--clear", action="store_true", help="delete all messages")
args = parser.parse_args()

if args.clear:
    urllib.request.urlopen(urllib.request.Request(API, method="DELETE"), timeout=5).close()  # noqa: S310
    print("inbox cleared")
else:
    with urllib.request.urlopen(API, timeout=5) as resp:  # noqa: S310 - fixed local URL
        data = json.load(resp)
    print(f"{data['total']} message(s)")
    for m in reversed(data["messages"]):
        to = ",".join(t["Address"] for t in m["To"])
        print(f"{m['Created'][:19]}\t{to}\t{m['Subject']}")
