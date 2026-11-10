"""Notify step for Ticket.Triaged events, independent of the Functions runtime.

Routing: injection_suspected -> human-review mailbox (always, whatever the priority); otherwise High/Critical ->
escalation mailbox; otherwise no email. The record's `notification` field is the idempotency marker:
check -> send -> mark, so delivery is at-least-once (a crash between send and mark can repeat one email,
with the same Message-ID). Customer-controlled text never goes into a mail header.
"""

import logging
import smtplib
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formatdate
from typing import Any, Literal, Protocol

from pydantic import ValidationError

from .events import record_from_doc
from .models import TICKET_TRIAGED, NotificationRecord, NotifyRoute, TicketTriagedData, TriageRecord

log = logging.getLogger(__name__)

NotifyStatus = Literal["notified", "no_email", "duplicate", "ignored"]


class InvalidEvent(Exception):
    """The event breaks the Ticket.Triaged contract. Raised so Event Grid retries, then dead-letters it."""


class RecordNotFound(Exception):
    """No triage record for the event yet. Raised so Event Grid retries the delivery."""


class Mailer(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class NotifyStore(Protocol):
    def get(self, ticket_id: str) -> dict[str, Any] | None: ...

    def mark(self, ticket_id: str, fields: dict[str, Any]) -> None: ...


class SmtpMailer:
    """Mailpit locally (no auth, no TLS). ACS Email replaces this on Azure at M8."""

    def __init__(self, host: str, port: int, starttls: bool = False, timeout_s: float = 10):
        self.host, self.port, self.starttls, self.timeout_s = host, port, starttls, timeout_s

    def send(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_s) as smtp:
            if self.starttls:
                smtp.starttls()
            smtp.send_message(message)


@dataclass(frozen=True)
class Mailboxes:
    sender: str
    escalation: str
    review: str


@dataclass(frozen=True)
class NotifyOutcome:
    status: NotifyStatus
    route: NotifyRoute | None = None


def route_for(record: TriageRecord) -> NotifyRoute:
    if record.injection_suspected:
        return "human_review"  # labels may be attacker-influenced: a person checks before anyone replies
    if record.priority in ("high", "critical"):
        return "escalation"
    return "none"


def email_message_id(ticket_id: str, route: NotifyRoute) -> str:
    """Stable per ticket + route: a repeated send is recognisable as the same message."""
    return f"<triage.{ticket_id}.{route}@pearlpay.example>"


def build_email(record: TriageRecord, route: NotifyRoute, boxes: Mailboxes) -> EmailMessage:
    if route == "none":
        raise ValueError("no email for route 'none'")
    priority = (record.priority or "unknown").upper()
    if route == "human_review":
        to = boxes.review
        subject = (
            f"[REVIEW] Ticket {record.ticket_id} - possible prompt injection ({record.priority}, {record.category})"
        )
        banner = (
            "HUMAN REVIEW REQUIRED. Injection markers were removed before the model call, so the labels and the\n"
            "draft reply below may be influenced by the customer's text. Confirm category and priority and edit the\n"
            "reply before anything is sent. Re-route to escalations if the ticket is genuinely urgent."
        )
    else:
        to = boxes.escalation
        subject = f"[{priority}] Ticket {record.ticket_id} - {record.category}"
        banner = "Escalation: triaged High/Critical. The suggested reply is a draft; review before sending."

    lines = [
        banner,
        "",
        f"Ticket:        {record.ticket_id}",
        f"Channel:       {record.channel}",
        f"Received:      {record.received_at.isoformat()}",
        f"Category:      {record.category}",
        f"Priority:      {record.priority}" + ("  (fraud floor applied)" if record.priority_floor_applied else ""),
        f"Injection:     {'suspected' if record.injection_suspected else 'no'}",
        f"Customer:      {record.customer_email}",
        f"Subject (customer text, untrusted): {record.subject}",
        "",
        "Summary:",
        record.summary or "",
        "",
        "Suggested reply (DRAFT - do not send unreviewed):",
        record.suggested_reply or "",
        "",
        f"Sources: {', '.join(record.sources) or 'none'}",
        f"Model:   {record.model} / {record.embedding_model}",
    ]
    msg = EmailMessage()
    msg["From"] = boxes.sender
    msg["To"] = to
    msg["Subject"] = subject  # built from enums + validated ticket id only; never customer text
    msg["Message-ID"] = email_message_id(record.ticket_id, route)
    msg["Date"] = formatdate(usegmt=True)
    msg["X-Ticket-Id"] = record.ticket_id
    msg["X-Triage-Route"] = route
    msg.set_content("\n".join(lines))
    return msg


class Notifier:
    def __init__(self, store: NotifyStore, mailer: Mailer, boxes: Mailboxes):
        self.store = store
        self.mailer = mailer
        self.boxes = boxes

    def handle(self, event_type: str, event_id: str, data: Any) -> NotifyOutcome:
        if event_type != TICKET_TRIAGED:
            log.warning("Ignoring event %s of type %s", event_id, event_type)
            return NotifyOutcome("ignored")
        try:
            payload = TicketTriagedData.model_validate(data)
        except ValidationError as exc:
            fields = sorted({".".join(str(p) for p in e["loc"]) or "<root>" for e in exc.errors(include_input=False)})
            raise InvalidEvent(f"contract violation in {fields}") from None
        if payload.ticket_id != event_id:
            raise InvalidEvent("event id does not match data.ticket_id")

        doc = self.store.get(payload.ticket_id)
        if doc is None:
            raise RecordNotFound(payload.ticket_id)
        record = record_from_doc(doc)
        if record.notification is not None:
            log.info("Ticket %s already notified (route=%s); skipping", record.ticket_id, record.notification.route)
            return NotifyOutcome("duplicate", record.notification.route)
        if record.status != "triaged":
            raise InvalidEvent("event refers to a record that is not triaged")

        route = route_for(record)
        now = datetime.now(UTC)
        message_id = None
        if route != "none":
            message = build_email(record, route, self.boxes)
            self.mailer.send(message)
            message_id = message["Message-ID"]
        marker = NotificationRecord(
            route=route,
            event_id=event_id,
            email_message_id=message_id,
            sent_at=now if message_id else None,
            processed_at=now,
        )
        self.store.mark(record.ticket_id, {"notification": marker.model_dump(mode="json")})
        return NotifyOutcome("notified" if message_id else "no_email", route)
