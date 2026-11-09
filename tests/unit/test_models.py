import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from triage.models import TicketMessage, TicketSubmission

VALID = {
    "customer_email": "alice@example.com",
    "subject": "Card payment failed",
    "body": "My card payment failed twice this morning.",
}


def test_defaults_and_whitespace_strip():
    s = TicketSubmission.model_validate({**VALID, "subject": "  Card payment failed  "})
    assert s.channel == "web"
    assert s.ticket_id is None
    assert s.subject == "Card payment failed"


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        TicketSubmission.model_validate({**VALID, "priority": "high"})


def test_bad_email_rejected():
    with pytest.raises(ValidationError):
        TicketSubmission.model_validate({**VALID, "customer_email": "not-an-email"})


@pytest.mark.parametrize("ticket_id", ["../etc", "-starts-with-dash", "x" * 65, "has space"])
def test_ticket_id_pattern(ticket_id):
    with pytest.raises(ValidationError):
        TicketSubmission.model_validate({**VALID, "ticket_id": ticket_id})


def test_from_submission_keeps_client_id():
    now = datetime(2026, 11, 9, tzinfo=UTC)
    m = TicketMessage.from_submission(TicketSubmission.model_validate({**VALID, "ticket_id": "T-1001"}), now=now)
    assert m.ticket_id == "T-1001"
    assert m.received_at == now
    assert m.schema_version == 1


def test_from_submission_generates_uuid():
    m = TicketMessage.from_submission(TicketSubmission.model_validate(VALID))
    assert uuid.UUID(m.ticket_id).version == 4
