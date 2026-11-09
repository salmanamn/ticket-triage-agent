"""API payload and queue contract."""

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field

TICKET_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
Channel = Literal["email", "web", "phone", "chat"]


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
