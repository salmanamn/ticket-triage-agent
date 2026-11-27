"""The laptop-only queue-depth endpoint (D29) and the Cosmos endpoint-discovery switch (D28)."""

import importlib
import json

import azure.functions as func
import pytest

from triage import cosmos, queue, settings

FUNCTIONS = ["submit_ticket", "health", "triage_ticket", "notify_ticket"]


class FakeReceiver:
    def __init__(self, waiting: int):
        self.waiting = waiting
        self.peeked_with = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def peek_messages(self, max_message_count: int, timeout: float | None = None):
        self.peeked_with.append((max_message_count, timeout))
        return [object()] * min(self.waiting, max_message_count)

    def receive_messages(self, *args, **kwargs):
        raise AssertionError("queue depth must only peek: a receive would lock or remove messages")


class FakeClient:
    def __init__(self, receiver: FakeReceiver):
        self.receiver = receiver
        self.queues = []

    def get_queue_receiver(self, name: str):
        self.queues.append(name)
        return self.receiver


@pytest.fixture
def sb(monkeypatch):
    monkeypatch.setenv("ServiceBusConnection", "Endpoint=sb://x;SharedAccessKeyName=k;SharedAccessKey=v")
    monkeypatch.setenv("TICKETS_QUEUE", "tickets")

    def install(waiting: int) -> FakeClient:
        client = FakeClient(FakeReceiver(waiting))
        monkeypatch.setattr(queue, "_depth_client", lambda: client)
        return client

    return install


def test_depth_peeks_the_tickets_queue(sb):
    client = sb(3)
    assert queue.queue_depth() == 3
    assert client.queues == ["tickets"]
    assert client.receiver.peeked_with == [(queue.QUEUE_DEPTH_LIMIT, queue.QUEUE_DEPTH_TIMEOUT_S)]


def test_depth_is_capped_at_the_limit(sb):
    sb(500)
    assert queue.queue_depth() == queue.QUEUE_DEPTH_LIMIT


def load_app(monkeypatch, enabled: str | None):
    if enabled is None:
        monkeypatch.delenv("QUEUE_DEPTH_ENDPOINT", raising=False)
    else:
        monkeypatch.setenv("QUEUE_DEPTH_ENDPOINT", enabled)
    import function_app

    return importlib.reload(function_app)


@pytest.mark.parametrize("enabled", [None, "false", "yes"])
def test_endpoint_is_off_unless_enabled(monkeypatch, enabled):
    app = load_app(monkeypatch, enabled)
    assert [f.get_function_name() for f in app.app.get_functions()] == FUNCTIONS


def test_endpoint_needs_a_key_and_reports_the_count(monkeypatch, sb):
    app = load_app(monkeypatch, "true")
    functions = {f.get_function_name(): f for f in app.app.get_functions()}
    assert set(functions) == {*FUNCTIONS, "queue_depth_report"}
    trigger = json.loads(functions["queue_depth_report"].get_function_json())["bindings"][0]
    assert trigger["authLevel"] == "FUNCTION" and trigger["methods"] == ["GET"] and trigger["route"] == "queue-depth"
    sb(2)
    request = func.HttpRequest("GET", "/api/queue-depth", body=b"")
    response = app.queue_depth_report(request)
    assert response.status_code == 200
    assert json.loads(response.get_body()) == {"messageCount": 2, "limit": queue.QUEUE_DEPTH_LIMIT}


def test_endpoint_reports_unavailable_without_details(monkeypatch, sb):
    app = load_app(monkeypatch, "true")

    def broken(*args, **kwargs):
        raise ConnectionError("amqp://192.168.49.101:5672 refused")

    monkeypatch.setattr(app, "queue_depth", broken)
    response = app.queue_depth_report(func.HttpRequest("GET", "/api/queue-depth", body=b""))
    assert response.status_code == 503 and b"192.168" not in response.get_body()


@pytest.mark.parametrize(("value", "expected"), [(None, True), ("true", True), ("false", False), ("FALSE", False)])
def test_cosmos_endpoint_discovery(monkeypatch, value, expected):
    monkeypatch.setenv("COSMOS_ENDPOINT", "http://192.168.49.102:8081")
    if value is None:
        monkeypatch.delenv("COSMOS_ENDPOINT_DISCOVERY", raising=False)
    else:
        monkeypatch.setenv("COSMOS_ENDPOINT_DISCOVERY", value)
    assert settings.cosmos().endpoint_discovery is expected


def test_cosmos_client_gets_the_discovery_switch(monkeypatch):
    seen = {}

    class FakeCosmosClient:
        def __init__(self, endpoint, credential, **kwargs):
            seen.update(kwargs, endpoint=endpoint)

    monkeypatch.setenv("COSMOS_ENDPOINT", "http://192.168.49.102:8081")
    monkeypatch.setenv("COSMOS_KEY", "emulator-key")
    monkeypatch.setenv("COSMOS_ENDPOINT_DISCOVERY", "false")
    monkeypatch.setattr(cosmos, "CosmosClient", FakeCosmosClient)
    cosmos.client.cache_clear()
    try:
        cosmos.client()
    finally:
        cosmos.client.cache_clear()
    assert seen == {"endpoint": "http://192.168.49.102:8081", "enable_endpoint_discovery": False}


def test_depth_client_does_not_retry(monkeypatch):
    """An unreachable queue must answer 503 quickly (KEDA waits 3 s), so the depth's client has no retries."""
    seen = {}

    class FakeServiceBusClient:
        @classmethod
        def from_connection_string(cls, conn, **options):
            seen.update(options)
            return cls()

    monkeypatch.setenv("ServiceBusConnection", "Endpoint=sb://x;SharedAccessKeyName=k;SharedAccessKey=v")
    monkeypatch.setattr(queue, "ServiceBusClient", FakeServiceBusClient)
    queue._depth_client.cache_clear()
    try:
        queue._depth_client()
    finally:
        queue._depth_client.cache_clear()
    assert seen == {"retry_total": 0}
