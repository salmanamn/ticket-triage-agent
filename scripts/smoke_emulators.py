#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["azure-servicebus==7.15.0", "azure-cosmos==4.17.1"]
# ///
"""SDK smoke test: Service Bus emulator send/receive + Cosmos vNext emulator CRUD.

Emulator well-known credentials only. Never used against Azure.
"""
import os
import sys
import uuid

from azure.cosmos import CosmosClient, PartitionKey
from azure.servicebus import ServiceBusClient, ServiceBusMessage

SB_CONN = os.getenv(
    "SB_CONN",
    "Endpoint=sb://localhost;SharedAccessKeyName=RootManageSharedAccessKey;"
    "SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;",
)
SB_QUEUE = os.getenv("SB_QUEUE", "tickets")
COSMOS_URL = os.getenv("COSMOS_URL", "http://localhost:8081")
COSMOS_KEY = os.getenv(
    "COSMOS_KEY",
    "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw==",
)


def servicebus() -> None:
    marker = f"smoke-{uuid.uuid4()}"
    with ServiceBusClient.from_connection_string(SB_CONN) as client:
        with client.get_queue_sender(SB_QUEUE) as sender:
            sender.send_messages(ServiceBusMessage(marker, message_id=marker))
        with client.get_queue_receiver(SB_QUEUE, max_wait_time=10) as receiver:
            for msg in receiver:
                receiver.complete_message(msg)
                if str(msg) == marker:
                    print(f"OK   servicebus send/receive ({SB_QUEUE})")
                    return
    raise RuntimeError(f"marker {marker} not received from {SB_QUEUE}")


def cosmos() -> None:
    client = CosmosClient(COSMOS_URL, credential=COSMOS_KEY)
    db = client.create_database_if_not_exists("smoke")
    try:
        container = db.create_container_if_not_exists("items", partition_key=PartitionKey(path="/pk"))
        item = {"id": str(uuid.uuid4()), "pk": "smoke", "value": 42}
        container.upsert_item(item)
        got = container.read_item(item["id"], partition_key="smoke")
        if got["value"] != 42:
            raise RuntimeError(f"unexpected item: {got}")
        print("OK   cosmos create/upsert/read")
    finally:
        client.delete_database("smoke")


def main() -> int:
    failed = False
    for name, check in (("servicebus", servicebus), ("cosmos", cosmos)):
        try:
            check()
        except Exception as exc:  # report every check, then fail
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())