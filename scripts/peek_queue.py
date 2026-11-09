#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["azure-servicebus==7.15.0"]
# ///
"""Peek (non-destructive) messages on a local emulator queue. Usage: peek_queue.py [queue]"""

import sys

from azure.servicebus import ServiceBusClient

CONN = (
    "Endpoint=sb://localhost;SharedAccessKeyName=RootManageSharedAccessKey;"
    "SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;"
)
queue = sys.argv[1] if len(sys.argv) > 1 else "tickets"

with ServiceBusClient.from_connection_string(CONN) as client, client.get_queue_receiver(queue) as receiver:
    msgs = receiver.peek_messages(max_message_count=50)
    print(f"{len(msgs)} message(s) in {queue}")
    for m in msgs:
        print(f"{m.message_id}\t{m.subject}\t{m.enqueued_time_utc:%Y-%m-%d %H:%M:%S}Z\tdelivery={m.delivery_count}")
