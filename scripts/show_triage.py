"""Print a triage record from Cosmos (local emulator, or Azure with TRIAGE_SETTINGS=src/azure.settings.json).

Usage: PYTHONPATH=src uv run python scripts/show_triage.py <ticket_id> [--full]
"""

import argparse
import json

import local_env

from triage import cosmos

HIDDEN = {"customer_email", "_rid", "_self", "_etag", "_attachments", "_ts"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ticket_id")
    parser.add_argument("--full", action="store_true", help="include retrieved hits and system fields")
    args = parser.parse_args()
    local_env.load()

    doc = cosmos.CosmosTriageStore(cosmos.triage_container()).get(args.ticket_id)
    if doc is None:
        raise SystemExit(f"no triage record for {args.ticket_id}")
    if not args.full:
        doc = {k: v for k, v in doc.items() if k not in HIDDEN | {"retrieved"}}
    print(json.dumps(doc, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
