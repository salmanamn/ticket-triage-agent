#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["azure-servicebus==7.15.0"]
# ///
"""Peek (non-destructive) messages on a local emulator queue or its dead-letter queue.

Usage: peek_queue.py [queue] [--dlq]
"""

import argparse

from azure.servicebus import ServiceBusClient, ServiceBusSubQueue

CONN = (
    "Endpoint=sb://localhost;SharedAccessKeyName=RootManageSharedAccessKey;"
    "SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;"
)

parser = argparse.ArgumentParser()
parser.add_argument("queue", nargs="?", default="tickets")
parser.add_argument("--dlq", action="store_true", help="peek the dead-letter sub-queue")
args = parser.parse_args()
sub_queue = ServiceBusSubQueue.DEAD_LETTER if args.dlq else None
label = f"{args.queue}/$deadletterqueue" if args.dlq else args.queue

with (
    ServiceBusClient.from_connection_string(CONN) as client,
    client.get_queue_receiver(args.queue, sub_queue=sub_queue) as receiver,
):
    msgs = receiver.peek_messages(max_message_count=50)
    print(f"{len(msgs)} message(s) in {label}")
    for m in msgs:
        line = f"{m.message_id}\t{m.subject}\t{m.enqueued_time_utc:%Y-%m-%d %H:%M:%S}Z\tdelivery={m.delivery_count}"
        if args.dlq:
            line += f"\treason={m.dead_letter_reason}"
        print(line)
