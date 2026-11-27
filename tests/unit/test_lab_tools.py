"""The two lab tools as Project 7 runs them in pods (D30): any listen address, and the stub's webhook key."""

import importlib.util
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from azure.core.credentials import AzureKeyCredential
from azure.eventgrid import EventGridPublisherClient

from triage.events import triaged_event
from unit.factories import SOURCE, record

ROOT = Path(__file__).resolve().parents[2]
WEBHOOK_KEY = "webhook-key-not-for-logs"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PathRecorder:
    def __init__(self):
        self.paths = []
        recorder = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):  # noqa: N802
                self.rfile.read(int(self.headers["Content-Length"]))
                recorder.paths.append(self.path)
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/runtime/webhooks/EventGrid?functionName=notify_ticket"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def test_stub_sends_the_webhook_key_from_the_environment_and_never_logs_it(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("NOTIFY_WEBHOOK_KEY", WEBHOOK_KEY)
    receiver = PathRecorder()
    sub = {
        "name": "notify",
        "includedEventTypes": ["Ticket.Triaged"],
        "endpoint": receiver.url,
        "keyEnv": "NOTIFY_WEBHOOK_KEY",
    }
    server = load("eventgrid_stub").make_server(0, "topic-key", [sub], tmp_path / "dl", [0.05])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = EventGridPublisherClient(
            f"http://127.0.0.1:{server.server_port}/api/events", AzureKeyCredential("topic-key")
        )
        client.send([triaged_event(record(), SOURCE)])
        deadline = time.monotonic() + 5
        while not receiver.paths and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        server.shutdown()
        receiver.server.shutdown()
    assert receiver.paths == [f"/runtime/webhooks/EventGrid?functionName=notify_ticket&code={WEBHOOK_KEY}"]
    assert WEBHOOK_KEY not in capsys.readouterr().out


def test_stub_refuses_to_start_without_the_webhook_key(monkeypatch, tmp_path):
    monkeypatch.delenv("NOTIFY_WEBHOOK_KEY", raising=False)
    sub = {
        "name": "notify",
        "endpoint": "http://triage-http:8080/runtime/webhooks/EventGrid",
        "keyEnv": "NOTIFY_WEBHOOK_KEY",
    }
    with pytest.raises(SystemExit, match="NOTIFY_WEBHOOK_KEY"):
        load("eventgrid_stub").make_server(0, "topic-key", [sub], tmp_path / "dl", [0.05])


def test_stub_without_key_env_keeps_the_endpoint_as_written():
    sub = {"name": "notify", "endpoint": "http://127.0.0.1:7071/runtime/webhooks/EventGrid?functionName=notify_ticket"}
    assert load("eventgrid_stub").webhook_url(sub) == sub["endpoint"]


@pytest.mark.parametrize("name", ["eventgrid_stub", "fake_llm"])
def test_lab_tools_listen_on_the_address_they_are_given(name, tmp_path):
    module = load(name)
    if name == "eventgrid_stub":
        server = module.make_server(0, "k", [], tmp_path / "dl", [0.05], host="0.0.0.0")  # noqa: S104
    else:
        server = module.make_server(0, 768, host="0.0.0.0")  # noqa: S104
    try:
        assert server.server_address[0] == "0.0.0.0"  # noqa: S104
    finally:
        server.server_close()


def test_the_start_up_line_names_the_key_env_not_the_key(monkeypatch):
    monkeypatch.setenv("NOTIFY_WEBHOOK_KEY", WEBHOOK_KEY)
    sub = {
        "name": "notify",
        "endpoint": "http://triage-http:8080/runtime/webhooks/EventGrid",
        "keyEnv": "NOTIFY_WEBHOOK_KEY",
    }
    text = load("eventgrid_stub").describe(sub)
    assert WEBHOOK_KEY not in text and "$NOTIFY_WEBHOOK_KEY" in text


def test_the_laptop_config_needs_no_key():
    """`func start` doesn't check webhook keys, so the laptop's stub config names none (the chart's does)."""
    laptop = json.loads((ROOT / "emulators/eventgrid/subscriptions.json").read_text())
    assert all("keyEnv" not in s for s in laptop["subscriptions"])
