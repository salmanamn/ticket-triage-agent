import json
import uuid

import pytest
from azure.servicebus import ServiceBusClient

pytestmark = pytest.mark.integration

EMULATOR = (
    "Endpoint=sb://localhost;SharedAccessKeyName=RootManageSharedAccessKey;"
    "SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;"
)


def drain(conn: str, queue: str) -> list:
    with (
        ServiceBusClient.from_connection_string(conn) as client,
        client.get_queue_receiver(queue, max_wait_time=5) as receiver,
    ):
        msgs = []
        for msg in receiver:
            msgs.append(msg)
            receiver.complete_message(msg)
        return msgs


def test_duplicate_submission_enqueued_once(monkeypatch):
    monkeypatch.setenv("ServiceBusConnection", EMULATOR)
    monkeypatch.setenv("TICKETS_QUEUE", "tickets")
    from triage.ingest import handle_submission
    from triage.queue import ServiceBusPublisher

    drain(EMULATOR, "tickets")
    ticket_id = f"IT-{uuid.uuid4().hex[:12]}"
    body = json.dumps(
        {
            "ticket_id": ticket_id,
            "customer_email": "bob@example.com",
            "subject": "Login loop",
            "body": "The app keeps sending me back to the login page.",
        }
    ).encode()

    pub = ServiceBusPublisher()
    assert handle_submission(body, pub).status == 202
    assert handle_submission(body, pub).status == 202  # client retry

    received = [m for m in drain(EMULATOR, "tickets") if m.message_id == ticket_id]
    assert len(received) == 1
    assert received[0].subject == "ticket.submitted"
