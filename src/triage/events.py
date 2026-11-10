"""Ticket.Triaged CloudEvent: build, publish to Event Grid (local stub or Azure), and relay pending records.

The relay runs after the Cosmos write. The record keeps `event_published_at`, so a failed publish is retried
on the next Service Bus delivery (the triage itself is skipped, the event is not). Event id = ticket id, so a
repeated publish is a duplicate the consumer can recognise.
"""

import logging
import threading
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Literal, Protocol

from azure.core.messaging import CloudEvent

from . import settings
from .models import TICKET_TRIAGED, TicketTriagedData, TriageRecord

log = logging.getLogger(__name__)

RelayStatus = Literal["published", "already_published", "not_triaged", "missing"]


class Publisher(Protocol):
    def publish(self, event: CloudEvent) -> None: ...


class RelayStore(Protocol):
    def get(self, ticket_id: str) -> dict[str, Any] | None: ...

    def mark(self, ticket_id: str, fields: dict[str, Any]) -> None: ...


def record_from_doc(doc: dict[str, Any]) -> TriageRecord:
    """Cosmos adds system fields (_rid, _etag, _ts, ...); the contract forbids unknown fields."""
    return TriageRecord.model_validate({k: v for k, v in doc.items() if not k.startswith("_")})


def triaged_event(record: TriageRecord, source: str) -> CloudEvent:
    if record.status != "triaged" or record.category is None or record.priority is None:
        raise ValueError(f"record {record.id} is not a completed triage")
    data = TicketTriagedData(
        ticket_id=record.ticket_id,
        category=record.category,
        priority=record.priority,
        injection_suspected=record.injection_suspected,
        priority_floor_applied=record.priority_floor_applied,
        triaged_at=record.triaged_at,
    )
    return CloudEvent(
        source=source,
        type=TICKET_TRIAGED,
        subject=f"tickets/{record.ticket_id}",
        id=record.ticket_id,
        time=record.triaged_at,
        datacontenttype="application/json",
        data=data.model_dump(mode="json"),
    )


_lock = threading.Lock()


@lru_cache(maxsize=1)
def _client():
    from azure.eventgrid import EventGridPublisherClient

    cfg = settings.events()
    if cfg.topic_key:
        from azure.core.credentials import AzureKeyCredential

        return EventGridPublisherClient(cfg.topic_endpoint, AzureKeyCredential(cfg.topic_key))
    from azure.identity import DefaultAzureCredential  # Azure: EventGrid Data Sender on the topic

    return EventGridPublisherClient(cfg.topic_endpoint, DefaultAzureCredential())


class EventGridPublisher:
    def publish(self, event: CloudEvent) -> None:
        with _lock:
            _client().send([event])


class EventRelay:
    def __init__(self, store: RelayStore, publisher: Publisher, source: str):
        self.store = store
        self.publisher = publisher
        self.source = source

    def publish_pending(
        self, ticket_id: str, *, record: TriageRecord | None = None, force: bool = False
    ) -> RelayStatus:
        """Publish Ticket.Triaged unless already published. `record` skips the read right after a fresh write;
        `force` republishes (same event id) for recovery and idempotency tests."""
        if record is None:
            doc = self.store.get(ticket_id)
            if doc is None:
                return "missing"
            record = record_from_doc(doc)
        if record.status != "triaged":
            return "not_triaged"
        if record.event_published_at and not force:
            return "already_published"

        self.publisher.publish(triaged_event(record, self.source))
        self.store.mark(ticket_id, {"event_published_at": datetime.now(UTC).isoformat()})
        log.info("Published %s for %s (priority=%s)", TICKET_TRIAGED, ticket_id, record.priority)
        return "published"
