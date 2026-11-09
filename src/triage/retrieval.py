"""Retrieval over Cosmos DB vector search: KB article chunks + resolved historical tickets."""

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from .ai import Embedder

Kind = Literal["kb", "ticket"]
MAX_CHUNK_CHARS = 1500


@dataclass(frozen=True)
class Document:
    id: str
    kind: Kind
    source: str
    title: str
    content: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Hit:
    id: str
    kind: Kind
    source: str
    title: str
    content: str
    score: float
    metadata: dict[str, str]


def chunk_markdown(source: str, text: str) -> list[Document]:
    """Split an article on '## ' headings; title from the leading '# ' line; long sections split by size."""
    lines = text.strip().splitlines()
    has_title = bool(lines) and lines[0].startswith("# ")
    title = lines[0][2:].strip() if has_title else source
    body = "\n".join(lines[1:] if has_title else lines)
    sections = [s.strip() for s in re.split(r"(?m)^(?=## )", body) if s.strip()] or [body.strip()]
    docs: list[Document] = []
    for section in sections:
        for start in range(0, len(section), MAX_CHUNK_CHARS):
            part = section[start : start + MAX_CHUNK_CHARS]
            docs.append(Document(f"kb-{source}-{len(docs)}", "kb", source, title, f"{title}\n\n{part}"))
    return docs


def ticket_document(record: dict[str, str]) -> Document:
    """Resolved ticket: embed what a new ticket looks like (subject + body); keep outcome as metadata."""
    return Document(
        id=f"ticket-{record['ticket_id']}",
        kind="ticket",
        source=record["ticket_id"],
        title=record["subject"],
        content=f"{record['subject']}\n\n{record['body']}",
        metadata={k: record[k] for k in ("category", "priority", "resolution")},
    )


class Retriever:
    def __init__(self, container: Any, embedder: Embedder):
        self.container = container
        self.embedder = embedder

    def index(self, docs: list[Document]) -> int:
        vectors = self.embedder.embed([d.content for d in docs], "document")
        for doc, vector in zip(docs, vectors, strict=True):
            self.container.upsert_item(
                {
                    "id": doc.id,
                    "kind": doc.kind,
                    "source": doc.source,
                    "title": doc.title,
                    "content": doc.content,
                    "metadata": doc.metadata,
                    "embedding": vector,
                    "embeddingModel": self.embedder.model,
                }
            )
        return len(docs)

    def search(self, query: str, k: int = 5, kind: Kind | None = None) -> list[Hit]:
        if not 1 <= k <= 20:
            raise ValueError("k must be between 1 and 20")
        (vector,) = self.embedder.embed([query], "query")
        kind_filter = " AND c.kind = @kind" if kind else ""
        # k is a validated int; every value goes in as a parameter.
        sql = (
            f"SELECT TOP {k} c.id, c.kind, c.source, c.title, c.content, c.metadata, "  # noqa: S608
            f"VectorDistance(c.embedding, @v) AS score FROM c "
            f"WHERE c.embeddingModel = @model{kind_filter} ORDER BY VectorDistance(c.embedding, @v)"
        )
        params = [{"name": "@v", "value": vector}, {"name": "@model", "value": self.embedder.model}]
        if kind:
            params.append({"name": "@kind", "value": kind})
            rows = self.container.query_items(sql, parameters=params, partition_key=kind)
        else:
            rows = self.container.query_items(sql, parameters=params, enable_cross_partition_query=True)
        return [
            Hit(
                id=r["id"],
                kind=r["kind"],
                source=r["source"],
                title=r["title"],
                content=r["content"],
                score=float(r["score"]),
                metadata=r.get("metadata") or {},
            )
            for r in rows
        ]
