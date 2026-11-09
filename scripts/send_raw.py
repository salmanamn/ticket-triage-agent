#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["azure-servicebus==7.15.0"]
# ///
"""Send a raw message straight to the local emulator queue, bypassing ingest (poison/DLQ tests).

Usage: send_raw.py <message_id> '<body>' [queue]
"""

import sys

from azure.servicebus import ServiceBusClient, ServiceBusMessage

CONN = (
    "Endpoint=sb://localhost;SharedAccessKeyName=RootManageSharedAccessKey;"
    "SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;"
)

if len(sys.argv) < 3:
    sys.exit(__doc__)
message_id, body = sys.argv[1], sys.argv[2]
queue = sys.argv[3] if len(sys.argv) > 3 else "tickets"

with ServiceBusClient.from_connection_string(CONN) as client, client.get_queue_sender(queue) as sender:
    sender.send_messages(
        ServiceBusMessage(body, message_id=message_id, content_type="application/json", subject="ticket.submitted")
    )
print(f"sent {message_id} to {queue}")
