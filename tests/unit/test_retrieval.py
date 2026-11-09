import pytest

from triage.retrieval import MAX_CHUNK_CHARS, Retriever, chunk_markdown, ticket_document

ARTICLE = "# Card payment declined\n\n## Codes\n51 insufficient funds\n\n## Escalation\nCards team, high"


class FakeContainer:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.upserts = []
        self.queries = []

    def upsert_item(self, item):
        self.upserts.append(item)

    def query_items(self, query, **kwargs):
        self.queries.append((query, kwargs))
        return iter(self.rows)


def test_chunk_markdown_splits_on_sections():
    docs = chunk_markdown("card-declines", ARTICLE)
    assert [d.id for d in docs] == ["kb-card-declines-0", "kb-card-declines-1"]
    assert all(d.title == "Card payment declined" and d.content.startswith("Card payment declined") for d in docs)
    assert "## Escalation" in docs[1].content


def test_chunk_markdown_splits_long_sections():
    docs = chunk_markdown("long", "# T\n\n## A\n" + "x" * (MAX_CHUNK_CHARS * 2))
    assert len(docs) == 3


def test_ticket_document():
    doc = ticket_document(
        {
            "ticket_id": "H-1",
            "subject": "S",
            "body": "B",
            "category": "cards",
            "priority": "high",
            "resolution": "R",
        }
    )
    assert (doc.id, doc.kind, doc.content) == ("ticket-H-1", "ticket", "S\n\nB")
    assert doc.metadata == {"category": "cards", "priority": "high", "resolution": "R"}


def test_index_stores_embedding_and_model(hash_embedder):
    c = FakeContainer()
    assert Retriever(c, hash_embedder).index(chunk_markdown("card-declines", ARTICLE)) == 2
    assert len(c.upserts[0]["embedding"]) == 768
    assert c.upserts[0]["embeddingModel"] == "hash-bow"


def test_search_scopes_to_model_and_partition(hash_embedder):
    row = {"id": "kb-x-0", "kind": "kb", "source": "x", "title": "T", "content": "c", "metadata": {}, "score": 0.9}
    c = FakeContainer(rows=[row])
    hits = Retriever(c, hash_embedder).search("card declined", k=3, kind="kb")
    assert hits[0].score == 0.9
    sql, kwargs = c.queries[0]
    assert "TOP 3" in sql and "c.embeddingModel = @model" in sql
    assert kwargs["partition_key"] == "kb"
    assert {"name": "@model", "value": "hash-bow"} in kwargs["parameters"]


@pytest.mark.parametrize("k", [0, 21])
def test_search_rejects_bad_k(hash_embedder, k):
    with pytest.raises(ValueError):
        Retriever(FakeContainer(), hash_embedder).search("q", k=k)
