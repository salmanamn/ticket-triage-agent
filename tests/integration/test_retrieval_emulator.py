import uuid

import pytest

from triage.retrieval import Document, Retriever

pytestmark = pytest.mark.integration

EMULATOR_KEY = "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="

DOCS = [
    Document(
        "kb-cards-0",
        "kb",
        "cards",
        "Card payment declined",
        "Card payment declined. Decline code 51 insufficient funds, available balance, pending authorisation.",
    ),
    Document(
        "kb-otp-0",
        "kb",
        "otp",
        "OTP not received",
        "OTP SMS not received while roaming, resend limit, registered mobile number.",
    ),
    Document(
        "ticket-H-1",
        "ticket",
        "H-1",
        "Transfer delayed",
        "International SWIFT transfer delayed, gpi trace UETR, beneficiary name mismatch.",
        {"category": "transfers", "priority": "high", "resolution": "Corrected beneficiary name"},
    ),
]


@pytest.fixture
def container(monkeypatch, hash_embedder):
    database = f"it-{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("COSMOS_ENDPOINT", "http://localhost:8081")
    monkeypatch.setenv("COSMOS_KEY", EMULATOR_KEY)
    monkeypatch.setenv("COSMOS_DATABASE", database)
    monkeypatch.setenv("COSMOS_KB_CONTAINER", "knowledge")
    from triage import cosmos

    cosmos.client.cache_clear()
    yield cosmos.ensure_kb_container(hash_embedder.dimensions)
    cosmos.client().delete_database(database)
    cosmos.client.cache_clear()


def test_vector_search_ranks_relevant_first(container, hash_embedder):
    retriever = Retriever(container, hash_embedder)
    assert retriever.index(DOCS) == 3
    hits = retriever.search("my card payment was declined with code 51", k=3)
    assert hits[0].id == "kb-cards-0"
    assert hits[0].score > hits[-1].score


def test_kind_filter_returns_tickets_only(container, hash_embedder):
    retriever = Retriever(container, hash_embedder)
    retriever.index(DOCS)
    hits = retriever.search("transfer delayed", k=5, kind="ticket")
    assert [h.id for h in hits] == ["ticket-H-1"]
    assert hits[0].metadata["priority"] == "high"
