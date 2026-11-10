#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Local Event Grid stub: a custom-topic endpoint for CloudEvents v1.0 that pushes to webhook subscriptions.

Mimics what the app relies on: `POST /api/events` with `aeg-sas-key`, CloudEvents structured/batch content types,
200 on accept, then asynchronous delivery per subscription (event-type filter), retries with backoff, no retry on
400/413, dead-letter files after the last attempt. Not emulated: validation handshake, advanced filters, batching,
managed identity, schema mapping.

Usage: ./scripts/eventgrid_stub.py [--port 6100] [--config emulators/eventgrid/subscriptions.json]
Key: EVENTGRID_TOPIC_KEY from src/local.settings.json (or the env var of the same name).
Inspect: GET /health, GET /_stub/deliveries (last 200 delivery results).
"""

import argparse
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_REQUEST_BYTES = 1024 * 1024  # Event Grid: 1 MB per publish request
REQUIRED = ("specversion", "id", "source", "type")
NO_RETRY = {400, 413}


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def log(line: str) -> None:
    print(f"{now()} {line}", flush=True)


def load_key() -> str:
    if key := os.getenv("EVENTGRID_TOPIC_KEY"):
        return key
    path = ROOT / "src" / "local.settings.json"
    try:
        return json.loads(path.read_text())["Values"]["EVENTGRID_TOPIC_KEY"]
    except (OSError, KeyError, json.JSONDecodeError):
        raise SystemExit(f"EVENTGRID_TOPIC_KEY not set and not found in {path}") from None


def validate(events: object) -> str | None:
    if not isinstance(events, list) or not events:
        return "expected a non-empty CloudEvents batch"
    for e in events:
        if not isinstance(e, dict):
            return "each event must be a JSON object"
        missing = [f for f in REQUIRED if not isinstance(e.get(f), str) or not e.get(f)]
        if missing:
            return f"event missing required attribute(s): {', '.join(missing)}"
        if e["specversion"] != "1.0":
            return "only CloudEvents specversion 1.0 is accepted"
    return None


class Topic:
    def __init__(self, key: str, subscriptions: list[dict], deadletter_dir: Path, backoff_s: list[float]):
        self.key = key
        self.subscriptions = subscriptions
        self.deadletter_dir = deadletter_dir
        self.backoff_s = backoff_s
        self.deliveries: deque[dict] = deque(maxlen=200)
        self.jobs: queue.Queue = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

    def accept(self, events: list[dict]) -> None:
        for event in events:
            log(f"PUBLISHED   id={event['id']} type={event['type']} subject={event.get('subject', '')}")
            for sub in self.subscriptions:
                types = sub.get("includedEventTypes") or []
                if not types or event["type"] in types:
                    self.jobs.put((sub, event))
                else:
                    log(f"FILTERED    sub={sub['name']} id={event['id']} type={event['type']}")

    def _worker(self) -> None:
        while True:
            sub, event = self.jobs.get()
            threading.Thread(target=self._deliver, args=(sub, event), daemon=True).start()

    def _post(self, sub: dict, event: dict, attempt: int) -> int:
        req = urllib.request.Request(  # noqa: S310 - local http endpoints from the committed config
            sub["endpoint"],
            data=json.dumps([event]).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "aeg-event-type": "Notification",
                "aeg-subscription-name": sub["name"].upper(),
                "aeg-delivery-count": str(attempt - 1),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=sub.get("timeoutSeconds", 30)) as resp:  # noqa: S310
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code
        except OSError:
            return 0  # connection refused / timeout

    def _deliver(self, sub: dict, event: dict) -> None:
        attempts = int(sub.get("maxDeliveryAttempts", 5))
        status = 0
        for attempt in range(1, attempts + 1):
            status = self._post(sub, event, attempt)
            result = {"at": now(), "sub": sub["name"], "id": event["id"], "attempt": attempt, "status": status}
            self.deliveries.append(result)
            if 200 <= status < 300:
                log(f"DELIVERED   sub={sub['name']} id={event['id']} attempt={attempt} status={status}")
                return
            if status in NO_RETRY or attempt == attempts:
                break
            delay = self.backoff_s[min(attempt - 1, len(self.backoff_s) - 1)]
            log(f"RETRY       sub={sub['name']} id={event['id']} attempt={attempt} status={status} in={delay}s")
            time.sleep(delay)
        self._deadletter(sub, event, attempt, status)

    def _deadletter(self, sub: dict, event: dict, attempts: int, status: int) -> None:
        folder = self.deadletter_dir / sub["name"]
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{event['id']}.json"
        reason = "MaxDeliveryAttemptsExceeded" if status not in NO_RETRY else f"NonRetryableHttpStatus{status}"
        record = {"deadletterReason": reason, "deliveryAttempts": attempts, "lastHttpStatus": status, "event": event}
        path.write_text(json.dumps(record, indent=2))
        self.deliveries.append({"at": now(), "sub": sub["name"], "id": event["id"], "deadlettered": reason})
        log(f"DEADLETTER  sub={sub['name']} id={event['id']} attempts={attempts} status={status} file={path}")


def make_handler(topic: Topic) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 - quiet default access log
            pass

        def _reply(self, status: int, body: object | None = None) -> None:
            raw = b"" if body is None else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):  # noqa: N802
            if self.path == "/health":
                return self._reply(200, {"status": "ok", "subscriptions": [s["name"] for s in topic.subscriptions]})
            if self.path == "/_stub/deliveries":
                return self._reply(200, list(topic.deliveries))
            return self._reply(404, {"error": "not_found"})

        def do_POST(self):  # noqa: N802
            if self.path.split("?", 1)[0] != "/api/events":
                return self._reply(404, {"error": "not_found"})
            if self.headers.get("aeg-sas-key") != topic.key:
                return self._reply(401, {"error": {"code": "Unauthorized", "message": "invalid aeg-sas-key"}})
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_REQUEST_BYTES:
                return self._reply(413, {"error": {"code": "RequestEntityTooLarge"}})
            ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            try:
                body = json.loads(self.rfile.read(length) or b"null")
            except json.JSONDecodeError:
                return self._reply(400, {"error": {"code": "BadRequest", "message": "invalid JSON"}})
            if ctype == "application/cloudevents+json":
                body = [body]
            elif ctype != "application/cloudevents-batch+json":
                return self._reply(400, {"error": {"code": "BadRequest", "message": "topic accepts CloudEvents only"}})
            if error := validate(body):
                return self._reply(400, {"error": {"code": "BadRequest", "message": error}})
            topic.accept(body)
            return self._reply(200)

    return Handler


def make_server(port: int, key: str, subscriptions: list[dict], deadletter_dir: Path, backoff_s: list[float]):
    topic = Topic(key, subscriptions, deadletter_dir, backoff_s)
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(topic))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=6100)
    parser.add_argument("--config", default=str(ROOT / "emulators" / "eventgrid" / "subscriptions.json"))
    parser.add_argument("--deadletter-dir", default=str(ROOT / "data" / "eventgrid" / "deadletter"))
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text())
    server = make_server(
        args.port,
        load_key(),
        config["subscriptions"],
        Path(args.deadletter_dir),
        config.get("retryBackoffSeconds", [2]),
    )
    for sub in config["subscriptions"]:
        log(f"SUBSCRIPTION {sub['name']} types={sub.get('includedEventTypes') or 'all'} -> {sub['endpoint']}")
    log(f"LISTENING   topic={config.get('topic', 'local')} http://127.0.0.1:{args.port}/api/events")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
