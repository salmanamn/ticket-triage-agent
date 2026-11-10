"""SmtpMailer against Mailpit (docker compose --profile notify up -d mailpit)."""

import json
import urllib.request

import pytest

from triage.notify import Mailboxes, SmtpMailer, build_email, email_message_id
from unit.factories import record

pytestmark = pytest.mark.integration

API = "http://127.0.0.1:8025/api/v1"
BOXES = Mailboxes("triage-bot@pearlpay.example", "escalations@pearlpay.example", "human-review@pearlpay.example")


def api(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)  # noqa: S310 - fixed local URL
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
        raw = resp.read()
    return json.loads(raw) if raw.strip().startswith(b"{") else None


def test_escalation_email_arrives_in_mailpit():
    ticket_id = "IT-MAIL-1"
    msg = build_email(record(id=ticket_id, ticket_id=ticket_id, priority="critical"), "escalation", BOXES)
    SmtpMailer("127.0.0.1", 1025).send(msg)

    found = api("GET", f"/search?query=subject:%22Ticket%20{ticket_id}%22")["messages"]
    try:
        assert len(found) == 1, "expected exactly one message in Mailpit"
        m = found[0]
        assert m["Subject"] == f"[CRITICAL] Ticket {ticket_id} - cards"
        assert m["To"][0]["Address"] == "escalations@pearlpay.example"
        assert m["MessageID"] == email_message_id(ticket_id, "escalation").strip("<>")
    finally:
        if found:
            api("DELETE", "/messages", {"IDs": [m["ID"] for m in found]})
