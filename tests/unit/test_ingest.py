import json

from triage.ingest import MAX_BODY_BYTES, handle_submission
from triage.models import TicketMessage

VALID = {
    "ticket_id": "T-1001",
    "customer_email": "alice@example.com",
    "subject": "Card payment failed",
    "body": "My card payment failed twice this morning.",
    "channel": "email",
}


class FakePublisher:
    def __init__(self):
        self.calls = []

    def publish(self, **kwargs):
        self.calls.append(kwargs)


class FailingPublisher:
    def publish(self, **kwargs):
        raise ConnectionError("broker down")


def raw(obj) -> bytes:
    return json.dumps(obj).encode()


def test_accepts_and_publishes():
    pub = FakePublisher()
    res = handle_submission(raw(VALID), pub)
    assert res.status == 202
    assert res.payload == {"ticket_id": "T-1001", "status": "queued"}
    (call,) = pub.calls
    assert call["message_id"] == "T-1001"
    assert call["subject"] == "ticket.submitted"
    assert call["properties"] == {"channel": "email", "schemaVersion": "1"}
    assert TicketMessage.model_validate_json(call["body"]).customer_email == "alice@example.com"


def test_invalid_json():
    assert handle_submission(b"{not json", FakePublisher()).status == 400


def test_non_object_json():
    assert handle_submission(b"[1, 2]", FakePublisher()).status == 400


def test_validation_errors_do_not_echo_input():
    bad = {"customer_email": "not-an-email", "subject": "x", "body": "short"}
    res = handle_submission(raw(bad), FakePublisher())
    assert res.status == 400
    assert {d["field"] for d in res.payload["details"]} == {"customer_email", "subject", "body"}
    assert "not-an-email" not in json.dumps(res.payload)


def test_payload_too_large_not_published():
    pub = FakePublisher()
    res = handle_submission(b"x" * (MAX_BODY_BYTES + 1), pub)
    assert res.status == 413
    assert pub.calls == []


def test_queue_failure_returns_503():
    res = handle_submission(raw(VALID), FailingPublisher())
    assert res.status == 503
    assert res.payload["ticket_id"] == "T-1001"


def test_generated_id_used_as_message_id():
    pub = FakePublisher()
    body = {k: v for k, v in VALID.items() if k != "ticket_id"}
    res = handle_submission(raw(body), pub)
    assert res.status == 202
    assert pub.calls[0]["message_id"] == res.payload["ticket_id"]
