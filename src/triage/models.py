"""API payload and queue contract."""

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field

TICKET_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
Channel = Literal["email", "web", "phone", "chat"]
Category = Literal["cards", "account_access", "otp", "transfers", "disputes", "technical", "other"]
Priority = Literal["low", "medium", "high", "critical"]
CATEGORIES: tuple[str, ...] = Category.__args__
PRIORITIES: tuple[str, ...] = Priority.__args__  # ordered low -> critical


class TicketSubmission(BaseModel):
    """Public payload for POST /api/tickets."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticket_id: str | None = Field(
        default=None,
        pattern=TICKET_ID_PATTERN,
        description="Client idempotency key; generated when omitted.",
    )
    customer_email: EmailStr
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=8000)
    channel: Channel = "web"


class TicketMessage(BaseModel):
    """Queue contract between ingest and triage. Bump schema_version on breaking changes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    ticket_id: str = Field(pattern=TICKET_ID_PATTERN)
    customer_email: EmailStr
    subject: str
    body: str
    channel: Channel
    received_at: datetime

    @classmethod
    def from_submission(cls, submission: TicketSubmission, now: datetime | None = None) -> "TicketMessage":
        return cls(
            ticket_id=submission.ticket_id or str(uuid4()),
            customer_email=submission.customer_email,
            subject=submission.subject,
            body=submission.body,
            channel=submission.channel,
            received_at=now or datetime.now(UTC),
        )


# Schema sent to the model. Kept to the subset Azure OpenAI strict mode accepts (no length keywords);
# lengths are enforced by TriageDecision below. Property order matters for constrained decoding:
# the summary is generated before the labels.
TRIAGE_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "priority": {"type": "string", "enum": list(PRIORITIES)},
        "suggested_reply": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "category", "priority", "suggested_reply", "sources"],
    "additionalProperties": False,
}


class TriageDecision(BaseModel):
    """What the model returns (validated after generation)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    summary: str = Field(min_length=10, max_length=600)
    category: Category
    priority: Priority
    suggested_reply: str = Field(min_length=20, max_length=2000)
    sources: list[str] = Field(default_factory=list, max_length=10)


class RetrievedRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    score: float


NotifyRoute = Literal["escalation", "human_review", "none"]


class NotificationRecord(BaseModel):
    """What the notify step did for a ticket. Its presence means the Ticket.Triaged event was handled."""

    model_config = ConfigDict(extra="forbid")

    route: NotifyRoute
    event_id: str
    email_message_id: str | None = None
    sent_at: datetime | None = None
    processed_at: datetime


class TriageRecord(BaseModel):
    """Document in the Cosmos `triage` container (id = ticket_id). Also the contract read by the notify step."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    id: str
    ticket_id: str
    status: Literal["triaged", "failed"]
    channel: Channel
    customer_email: EmailStr
    subject: str
    received_at: datetime
    category: Category | None = None
    priority: Priority | None = None
    summary: str | None = None
    suggested_reply: str | None = None
    sources: list[str] = Field(default_factory=list)
    priority_floor_applied: bool = False
    injection_suspected: bool = False  # notify routes these to human review
    error: str | None = None
    model: str
    embedding_model: str
    retrieved: list[RetrievedRef] = Field(default_factory=list)
    attempts: int
    latency_ms: int
    triaged_at: datetime
    event_published_at: datetime | None = None  # set by EventRelay once Event Grid accepted Ticket.Triaged
    notification: NotificationRecord | None = None  # set by the notify function (idempotency marker)


TICKET_TRIAGED = "Ticket.Triaged"


class TicketTriagedData(BaseModel):
    """CloudEvent `data` for Ticket.Triaged. Thin by design: no customer email, subject, body or model text.
    Consumers read the full record from Cosmos by ticket_id (claim check)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    ticket_id: str = Field(pattern=TICKET_ID_PATTERN)
    category: Category
    priority: Priority
    injection_suspected: bool
    priority_floor_applied: bool
    triaged_at: datetime
