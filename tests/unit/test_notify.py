import uuid

import pytest
from azure.core.exceptions import HttpResponseError

from triage.events import triaged_event
from triage.notify import (
    AcsMailer,
    InvalidEvent,
    Mailboxes,
    Notifier,
    RecordNotFound,
    acs_operation_id,
    acs_payload,
    build_email,
    email_message_id,
    route_for,
)
from unit.factories import SOURCE, FakeStore, doc, record

BOXES = Mailboxes(
    sender="triage-bot@pearlpay.example",
    escalation="escalations@pearlpay.example",
    review="human-review@pearlpay.example",
)


class FakeMailer:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, message):
        if self.fail:
            raise ConnectionRefusedError("smtp down")
        self.sent.append(message)


def event_for(rec):
    e = triaged_event(rec, SOURCE)
    return e.type, e.id, e.data


def run(rec, mailer=None, store=None):
    store = store or FakeStore({rec.id: doc(rec)})
    mailer = mailer or FakeMailer()
    outcome = Notifier(store, mailer, BOXES).handle(*event_for(rec))
    return outcome, store, mailer


@pytest.mark.parametrize(
    ("priority", "injection", "route"),
    [
        ("low", False, "none"),
        ("medium", False, "none"),
        ("high", False, "escalation"),
        ("critical", False, "escalation"),
        ("low", True, "human_review"),
        ("critical", True, "human_review"),
    ],
)
def test_routing(priority, injection, route):
    assert route_for(record(priority=priority, injection_suspected=injection)) == route


def test_high_ticket_emails_escalations_and_marks_record():
    outcome, store, mailer = run(record(priority="high"))
    assert (outcome.status, outcome.route) == ("notified", "escalation")
    (msg,) = mailer.sent
    assert msg["To"] == "escalations@pearlpay.example"
    assert msg["Subject"] == "[HIGH] Ticket T-1 - cards"
    assert msg["Message-ID"] == email_message_id("T-1", "escalation")
    marker = store.docs["T-1"]["notification"]
    assert marker["route"] == "escalation" and marker["event_id"] == "T-1" and marker["sent_at"]


def test_low_ticket_sends_nothing_but_is_marked():
    outcome, store, mailer = run(record(priority="low"))
    assert outcome.status == "no_email" and mailer.sent == []
    assert store.docs["T-1"]["notification"]["route"] == "none"
    assert store.docs["T-1"]["notification"]["sent_at"] is None


def test_injection_goes_to_human_review_with_warning():
    _, _, mailer = run(record(priority="low", injection_suspected=True))
    (msg,) = mailer.sent
    assert msg["To"] == "human-review@pearlpay.example"
    assert msg["Subject"].startswith("[REVIEW] Ticket T-1")
    assert "HUMAN REVIEW REQUIRED" in msg.get_content()


def test_duplicate_event_sends_no_second_email():
    rec = record(priority="critical")
    store, mailer = FakeStore({"T-1": doc(rec)}), FakeMailer()
    notifier = Notifier(store, mailer, BOXES)
    assert notifier.handle(*event_for(rec)).status == "notified"
    assert notifier.handle(*event_for(rec)).status == "duplicate"
    assert len(mailer.sent) == 1


def test_mail_failure_raises_and_leaves_record_unmarked():
    rec = record(priority="high")
    store = FakeStore({"T-1": doc(rec)})
    with pytest.raises(ConnectionRefusedError):
        run(rec, mailer=FakeMailer(fail=True), store=store)
    assert store.docs["T-1"]["notification"] is None


def test_missing_record_raises_for_retry():
    with pytest.raises(RecordNotFound):
        run(record(), store=FakeStore())


def test_other_event_types_are_ignored():
    outcome = Notifier(FakeStore(), FakeMailer(), BOXES).handle("Ticket.Closed", "T-1", {})
    assert outcome.status == "ignored"


@pytest.mark.parametrize(
    ("event_id", "patch"),
    [("T-1", {"priority": "urgent"}), ("T-1", {"extra": 1}), ("OTHER", {}), ("T-1", {"schema_version": 2})],
)
def test_contract_violations_raise_invalid_event(event_id, patch):
    _, _, data = event_for(record())
    with pytest.raises(InvalidEvent):
        Notifier(FakeStore(), FakeMailer(), BOXES).handle("Ticket.Triaged", event_id, {**data, **patch})


def test_customer_text_never_reaches_mail_headers():
    hostile = record(priority="high", subject="Help\r\nBcc: attacker@evil.example")
    msg = build_email(hostile, "escalation", BOXES)
    assert "evil" not in str(msg["Subject"]) and msg["Bcc"] is None
    assert "attacker@evil.example" in msg.get_content()  # kept in the body, labelled untrusted


# --- ACS Email (Azure, D20) --------------------------------------------------------------------------------------


class FakeAcsClient:
    def __init__(self, status=None):
        self.calls, self.status = [], status

    def begin_send(self, message, *, operation_id, polling):
        self.calls.append({"message": message, "operation_id": operation_id, "polling": polling})
        if self.status:
            err = HttpResponseError(message=f"HTTP {self.status}")
            err.status_code = self.status
            raise err


def test_acs_payload_carries_the_built_email_and_only_safe_headers():
    hostile = record(priority="high", subject="Help\r\nBcc: attacker@evil.example")
    msg = build_email(hostile, "escalation", BOXES)
    payload = acs_payload(msg)
    assert payload["senderAddress"] == BOXES.sender
    assert payload["recipients"] == {"to": [{"address": BOXES.escalation}]}
    assert payload["content"]["subject"] == str(msg["Subject"]) and "evil" not in payload["content"]["subject"]
    assert payload["content"]["plainText"] == msg.get_content()
    assert payload["headers"] == {"X-Ticket-Id": hostile.ticket_id, "X-Triage-Route": "escalation"}
    assert payload["userEngagementTrackingDisabled"] is True


def test_acs_operation_id_is_stable_per_ticket_and_route():
    rec = record(priority="high")
    first = acs_operation_id(email_message_id(rec.ticket_id, "escalation"))
    assert first == acs_operation_id(email_message_id(rec.ticket_id, "escalation"))
    assert first != acs_operation_id(email_message_id(rec.ticket_id, "human_review"))
    assert str(uuid.UUID(first)) == first


def test_acs_mailer_queues_without_polling():
    client = FakeAcsClient()
    msg = build_email(record(priority="high"), "escalation", BOXES)
    AcsMailer(client).send(msg)
    (call,) = client.calls
    assert call["polling"] is False
    assert call["operation_id"] == acs_operation_id(msg["Message-ID"])


def test_acs_conflict_means_already_queued():
    AcsMailer(FakeAcsClient(status=409)).send(build_email(record(priority="high"), "escalation", BOXES))


def test_acs_other_errors_raise_for_event_grid_retry():
    with pytest.raises(HttpResponseError):
        AcsMailer(FakeAcsClient(status=500)).send(build_email(record(priority="high"), "escalation", BOXES))


def test_notifier_with_acs_sends_once_and_marks_record():
    client = FakeAcsClient()
    outcome, store, _ = run(record(priority="critical"), mailer=AcsMailer(client))
    assert outcome.status == "notified" and len(client.calls) == 1
    rec_id = next(iter(store.docs))
    assert store.docs[rec_id]["notification"]["route"] == "escalation"
