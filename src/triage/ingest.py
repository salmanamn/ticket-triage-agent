"""Ticket ingest logic, independent of the Functions runtime."""

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from .models import TicketMessage, TicketSubmission

log = logging.getLogger(__name__)

MAX_BODY_BYTES = 32 * 1024


class Publisher(Protocol):
    def publish(self, *, message_id: str, body: str, subject: str, properties: dict[str, str]) -> None: ...


@dataclass(frozen=True)
class Response:
    status: int
    payload: dict[str, Any]


def handle_submission(raw: bytes, publisher: Publisher) -> Response:
    if len(raw) > MAX_BODY_BYTES:
        return Response(413, {"error": "payload_too_large", "max_bytes": MAX_BODY_BYTES})

    try:
        data = json.loads(raw or b"null")
    except json.JSONDecodeError:
        return Response(400, {"error": "invalid_json"})
    if not isinstance(data, dict):
        return Response(400, {"error": "invalid_json", "detail": "expected a JSON object"})

    try:
        submission = TicketSubmission.model_validate(data)
    except ValidationError as exc:
        details = [
            {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
            for err in exc.errors(include_input=False, include_url=False)
        ]
        return Response(400, {"error": "validation_failed", "details": details})

    message = TicketMessage.from_submission(submission)
    try:
        publisher.publish(
            message_id=message.ticket_id,
            body=message.model_dump_json(),
            subject="ticket.submitted",
            properties={"channel": message.channel, "schemaVersion": str(message.schema_version)},
        )
    except Exception:
        log.exception("Failed to enqueue ticket %s", message.ticket_id)
        return Response(503, {"error": "queue_unavailable", "ticket_id": message.ticket_id})

    log.info("Enqueued ticket %s (channel=%s)", message.ticket_id, message.channel)
    return Response(202, {"ticket_id": message.ticket_id, "status": "queued"})
