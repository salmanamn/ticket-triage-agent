"""Shared builders and fakes for the event and notify tests."""

from datetime import UTC, datetime

from triage.models import TriageRecord

SOURCE = "/pearlpay/ticket-triage"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def record(**overrides) -> TriageRecord:
    base = {
        "id": "T-1",
        "ticket_id": "T-1",
        "status": "triaged",
        "channel": "web",
        "customer_email": "alice@example.com",
        "subject": "Card declined code 51",
        "received_at": NOW,
        "category": "cards",
        "priority": "high",
        "summary": "Card declined with code 51 although the balance covers it.",
        "suggested_reply": "Thanks for reaching out, we have escalated this to the cards team.",
        "model": "fake-chat",
        "embedding_model": "fake-embed",
        "attempts": 1,
        "latency_ms": 10,
        "triaged_at": NOW,
    }
    return TriageRecord(**{**base, **overrides})


class FakeStore:
    def __init__(self, docs=None):
        self.docs = dict(docs or {})
        self.marks = []

    def get(self, ticket_id):
        return self.docs.get(ticket_id)

    def mark(self, ticket_id, fields):
        self.marks.append((ticket_id, fields))
        self.docs[ticket_id] = {**self.docs[ticket_id], **fields}


class FakePublisher:
    def __init__(self, fail=False):
        self.events, self.fail = [], fail

    def publish(self, event):
        if self.fail:
            raise ConnectionError("event grid down")
        self.events.append(event)


def doc(rec: TriageRecord) -> dict:
    return {**rec.model_dump(mode="json"), "_rid": "x", "_etag": '"1"', "_ts": 1}
