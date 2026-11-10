"""Publish Ticket.Triaged for a triage record (local Cosmos + Event Grid stub): recovery and idempotency tests.

Usage: PYTHONPATH=src uv run python scripts/publish_event.py <ticket_id> [--force]
Without --force only records whose event isn't published yet are sent. --force resends (same event id).
"""

import argparse

import local_env

from triage import cosmos, settings
from triage.events import EventGridPublisher, EventRelay


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ticket_id")
    parser.add_argument("--force", action="store_true", help="republish even if already published")
    args = parser.parse_args()
    local_env.load()

    relay = EventRelay(
        cosmos.CosmosTriageStore(cosmos.triage_container()), EventGridPublisher(), settings.events().source
    )
    print(f"{args.ticket_id}: {relay.publish_pending(args.ticket_id, force=args.force)}")


if __name__ == "__main__":
    main()
