import pytest

from triage.events import EventRelay, record_from_doc, triaged_event
from triage.models import TICKET_TRIAGED
from unit.factories import NOW, SOURCE, FakePublisher, FakeStore, doc, record


def test_event_id_is_ticket_id_and_data_is_thin():
    event = triaged_event(record(), SOURCE)
    assert (event.id, event.type, event.source, event.subject) == ("T-1", TICKET_TRIAGED, SOURCE, "tickets/T-1")
    assert event.data == {
        "schema_version": 1,
        "ticket_id": "T-1",
        "category": "cards",
        "priority": "high",
        "injection_suspected": False,
        "priority_floor_applied": False,
        "triaged_at": "2026-11-10T12:00:00Z",
    }
    flat = str(event.data)
    assert "alice@example.com" not in flat and "code 51" not in flat


def test_failed_record_has_no_event():
    with pytest.raises(ValueError):
        triaged_event(record(status="failed", category=None, priority=None), SOURCE)


def test_record_from_doc_ignores_cosmos_system_fields():
    assert record_from_doc(doc(record())).ticket_id == "T-1"


def test_relay_publishes_once_then_marks():
    store, pub = FakeStore({"T-1": doc(record())}), FakePublisher()
    relay = EventRelay(store, pub, SOURCE)
    assert relay.publish_pending("T-1") == "published"
    assert store.marks[0][0] == "T-1" and "event_published_at" in store.marks[0][1]
    assert relay.publish_pending("T-1") == "already_published"
    assert len(pub.events) == 1


def test_relay_uses_fresh_record_without_read():
    store, pub = FakeStore({"T-1": doc(record())}), FakePublisher()
    store.get = None  # a read would fail
    assert EventRelay(store, pub, SOURCE).publish_pending("T-1", record=record()) == "published"


def test_relay_force_republishes_same_event_id():
    store, pub = FakeStore({"T-1": doc(record(event_published_at=NOW))}), FakePublisher()
    assert EventRelay(store, pub, SOURCE).publish_pending("T-1", force=True) == "published"
    assert pub.events[0].id == "T-1"


@pytest.mark.parametrize(
    ("docs", "expected"),
    [({}, "missing"), ({"T-1": doc(record(status="failed", category=None, priority=None))}, "not_triaged")],
)
def test_relay_skips_missing_and_failed(docs, expected):
    pub = FakePublisher()
    assert EventRelay(FakeStore(docs), pub, SOURCE).publish_pending("T-1") == expected
    assert pub.events == []


def test_publish_failure_leaves_record_unmarked_and_raises():
    store = FakeStore({"T-1": doc(record())})
    with pytest.raises(ConnectionError):
        EventRelay(store, FakePublisher(fail=True), SOURCE).publish_pending("T-1")
    assert store.marks == [] and store.docs["T-1"]["event_published_at"] is None
