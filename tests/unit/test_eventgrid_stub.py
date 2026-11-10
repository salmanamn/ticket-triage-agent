"""Event Grid stub + the real azure-eventgrid publisher, end to end on localhost (no emulators needed)."""

import importlib.util
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError
from azure.eventgrid import EventGridPublisherClient

from triage.events import triaged_event
from unit.factories import SOURCE, record

ROOT = Path(__file__).resolve().parents[2]
KEY = "test-key"


def load_stub():
    spec = importlib.util.spec_from_file_location("eventgrid_stub", ROOT / "scripts" / "eventgrid_stub.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Receiver:
    """Stands in for the Functions Event Grid webhook. Fails the first `fail_first` requests with HTTP 500."""

    def __init__(self, fail_first=0, status=200):
        self.requests, self.fail_first, self.status = [], fail_first, status
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                receiver.requests.append((self.headers, body))  # case-insensitive
                failing = len(receiver.requests) <= receiver.fail_first
                self.send_response(500 if failing else receiver.status)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/runtime/webhooks/EventGrid?functionName=notify_ticket"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def stub(tmp_path):
    servers = []

    def start(receiver, types=("Ticket.Triaged",), attempts=3):
        subs = [{"name": "notify", "includedEventTypes": list(types), "endpoint": receiver.url,
                 "maxDeliveryAttempts": attempts}]  # fmt: skip
        server = load_stub().make_server(0, KEY, subs, tmp_path / "deadletter", [0.05])
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        endpoint = f"http://127.0.0.1:{server.server_port}/api/events"
        return EventGridPublisherClient(endpoint, AzureKeyCredential(KEY)), endpoint

    yield start
    for s in servers:
        s.shutdown()


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_sdk_publish_is_delivered_as_cloudevent_webhook(stub):
    receiver = Receiver()
    client, _ = stub(receiver)
    client.send([triaged_event(record(), SOURCE)])
    assert wait_for(lambda: receiver.requests)
    headers, body = receiver.requests[0]
    assert headers["aeg-event-type"] == "Notification"
    assert headers["Content-Type"] == "application/json"
    (event,) = body
    assert (event["specversion"], event["id"], event["type"]) == ("1.0", "T-1", "Ticket.Triaged")
    assert event["data"]["priority"] == "high"


def test_wrong_key_is_rejected(stub):
    _, endpoint = stub(Receiver())
    with pytest.raises((ClientAuthenticationError, HttpResponseError)) as exc:
        EventGridPublisherClient(endpoint, AzureKeyCredential("wrong")).send([triaged_event(record(), SOURCE)])
    assert exc.value.status_code == 401


def test_event_type_filter(stub):
    receiver = Receiver()
    client, _ = stub(receiver, types=("Ticket.Closed",))
    client.send([triaged_event(record(), SOURCE)])
    time.sleep(0.3)
    assert receiver.requests == []


def test_retries_then_succeeds(stub):
    receiver = Receiver(fail_first=2)
    client, _ = stub(receiver, attempts=3)
    client.send([triaged_event(record(), SOURCE)])
    assert wait_for(lambda: len(receiver.requests) == 3)
    assert [h["aeg-delivery-count"] for h, _ in receiver.requests] == ["0", "1", "2"]


def test_dead_letters_after_last_attempt(stub, tmp_path):
    receiver = Receiver(fail_first=99)
    client, _ = stub(receiver, attempts=2)
    client.send([triaged_event(record(), SOURCE)])
    dead = tmp_path / "deadletter" / "notify" / "T-1.json"
    assert wait_for(dead.exists)
    saved = json.loads(dead.read_text())
    assert saved["deadletterReason"] == "MaxDeliveryAttemptsExceeded" and saved["deliveryAttempts"] == 2
    assert saved["event"]["id"] == "T-1"


def test_bad_request_is_not_retried(stub, tmp_path):
    receiver = Receiver(status=400)
    client, _ = stub(receiver, attempts=5)
    client.send([triaged_event(record(), SOURCE)])
    dead = tmp_path / "deadletter" / "notify" / "T-1.json"
    assert wait_for(dead.exists)
    assert len(receiver.requests) == 1
    assert json.loads(dead.read_text())["deadletterReason"] == "NonRetryableHttpStatus400"
