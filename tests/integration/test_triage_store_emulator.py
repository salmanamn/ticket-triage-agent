import uuid

import pytest

pytestmark = pytest.mark.integration

EMULATOR_KEY = "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="


@pytest.fixture
def store(monkeypatch):
    database = f"it-{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("COSMOS_ENDPOINT", "http://localhost:8081")
    monkeypatch.setenv("COSMOS_KEY", EMULATOR_KEY)
    monkeypatch.setenv("COSMOS_DATABASE", database)
    monkeypatch.setenv("COSMOS_TRIAGE_CONTAINER", "triage")
    from triage import cosmos

    cosmos.client.cache_clear()
    yield cosmos.CosmosTriageStore(cosmos.ensure_triage_container())
    cosmos.client().delete_database(database)
    cosmos.client.cache_clear()


def test_create_is_insert_only(store):
    assert store.get("T-1") is None
    assert store.create({"id": "T-1", "status": "triaged", "priority": "high"}) is True
    assert store.create({"id": "T-1", "status": "triaged", "priority": "low"}) is False
    assert store.get("T-1")["priority"] == "high"


def test_upsert_replaces_failed_record(store):
    store.upsert({"id": "T-2", "status": "failed"})
    store.upsert({"id": "T-2", "status": "triaged"})
    assert store.get("T-2")["status"] == "triaged"


def test_mark_sets_fields_without_touching_others(store):
    store.create({"id": "T-3", "status": "triaged", "priority": "high"})
    store.mark("T-3", {"event_published_at": "2026-11-10T12:00:00+00:00"})
    store.mark("T-3", {"notification": {"route": "escalation", "event_id": "T-3"}})
    doc = store.get("T-3")
    assert doc["priority"] == "high" and doc["event_published_at"] == "2026-11-10T12:00:00+00:00"
    assert doc["notification"]["route"] == "escalation"
