#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Deterministic fake LLM: an OpenAI-compatible /v1 server for CI and model-free local runs (stdlib only).

POST /v1/chat/completions  triage JSON from keyword rules on the <ticket> block. Requires
                           response_format=json_schema (strict) with category/priority enums, like Azure strict mode.
POST /v1/embeddings        hashing bag-of-words vectors (float or base64); `dimensions` honoured.
GET  /v1/models, /health, /_fake/requests (last 200 request summaries).

Same input -> same output, so tests can assert exact labels. It is not a model: labels come from keywords.
Markers in the ticket text force failure paths:
  FAKE_LLM_TRUNCATE       finish_reason=length with half a JSON document
  FAKE_LLM_INVALID        content that is not JSON
  FAKE_LLM_INVENT_SOURCE  cites an id that was not retrieved
  FAKE_LLM_HTTP500        HTTP 500

Usage: ./scripts/fake_llm.py [--port 11434] [--dimensions 768]   (stop the Ollama container first)
"""

import argparse
import base64
import hashlib
import json
import math
import re
import struct
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TICKET_BLOCK = re.compile(r"<ticket[^>]*>(.*?)</ticket>", re.DOTALL)
KB_BLOCK = re.compile(r"<knowledge_base>(.*?)</knowledge_base>", re.DOTALL)
SIMILAR_BLOCK = re.compile(r"<similar_resolved_tickets>(.*?)</similar_resolved_tickets>", re.DOTALL)
ITEM_ID = re.compile(r'<item id="([^"]+)">')
SUBJECT_LINE = re.compile(r"^\s*Subject:\s*(.+)$", re.MULTILINE)

# First match wins; the order resolves overlaps ("card charged twice" is a dispute, not a card problem).
CATEGORY_RULES: list[tuple[str, re.Pattern]] = [
    (
        "disputes",
        re.compile(
            r"\b(charged twice|double charge|duplicate charge|unrecogni[sz]ed (charge|transaction|payment)|"
            r"don'?t recogni[sz]e|dispute|chargeback)\b",
            re.I,
        ),
    ),
    ("otp", re.compile(r"\b(otp|one[- ]time (code|password)|verification code|sms code)\b", re.I)),
    (
        "account_access",
        re.compile(r"\b(log ?in|sign ?in|signed out|locked out|lockout|password|new device|unknown device)\b", re.I),
    ),
    ("transfers", re.compile(r"\b(transfers?|swift|iban|beneficiary|remittance|wire)\b", re.I)),
    ("cards", re.compile(r"\b(cards?|declined|decline|atm|contactless)\b", re.I)),
    ("technical", re.compile(r"\b(crash\w*|freez\w*|bug|error)\b", re.I)),
]
CRITICAL = re.compile(
    r"\b(fraud\w*|hacked|stolen|wasn'?t me|not me|didn'?t make|unauthori[sz]ed|"
    r"someone (else )?(logged|used|accessed))\b",
    re.I,
)
QUESTION = re.compile(r"\b(how (do|can) i|how to|is it possible|what is|where can i)\b", re.I)
HIGH = re.compile(r"\b(declined|blocked|overdue|missing|not arrived|hasn'?t arrived|locked out|stuck)\b", re.I)


def triage_labels(ticket_text: str) -> tuple[str, str]:
    category = next((name for name, rule in CATEGORY_RULES if rule.search(ticket_text)), "other")
    if CRITICAL.search(ticket_text):
        priority = "critical"
    elif HIGH.search(ticket_text):
        priority = "high"
    elif QUESTION.search(ticket_text):
        priority = "low"
    else:
        priority = "medium"
    return category, priority


def hash_embedding(text: str, dimensions: int) -> list[float]:
    """Same scheme as tests/conftest.HashEmbedder: keyword overlap -> cosine similarity."""
    v = [0.0] * dimensions
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        if len(token) >= 3:
            v[int(hashlib.sha256(token.encode()).hexdigest()[:8], 16) % dimensions] += 1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


class BadRequest(Exception):
    pass


def _schema_enums(body: dict) -> tuple[list[str], list[str]]:
    fmt = body.get("response_format") or {}
    if fmt.get("type") != "json_schema":
        raise BadRequest("response_format must be json_schema (structured output)")
    spec = fmt.get("json_schema") or {}
    if spec.get("strict") is not True:
        raise BadRequest("json_schema.strict must be true")
    props = (spec.get("schema") or {}).get("properties") or {}
    try:
        return list(props["category"]["enum"]), list(props["priority"]["enum"])
    except (KeyError, TypeError):
        raise BadRequest("schema must define category and priority enums") from None


def chat_completion(body: dict) -> tuple[int, dict]:
    categories, priorities = _schema_enums(body)
    user = next((m.get("content", "") for m in body.get("messages", []) if m.get("role") == "user"), "")
    match = TICKET_BLOCK.search(user)
    if not match:
        raise BadRequest("user message has no <ticket> block")
    ticket = match.group(1)
    if "FAKE_LLM_HTTP500" in ticket:
        return 500, {"error": {"message": "fake upstream failure", "type": "server_error"}}

    category, priority = triage_labels(ticket)
    category = category if category in categories else categories[-1]
    priority = priority if priority in priorities else priorities[0]
    subject = (SUBJECT_LINE.search(ticket) or [None, "the request"])[1].strip()[:80]
    sources = []
    for block in (KB_BLOCK.search(user), SIMILAR_BLOCK.search(user)):
        ids = ITEM_ID.findall(block.group(1)) if block else []
        sources += ids[:1]
    if "FAKE_LLM_INVENT_SOURCE" in ticket:
        sources.append("kb-invented-0")
    decision = {
        "summary": f"Customer reports a {category.replace('_', ' ')} issue: {subject}.",
        "category": category,
        "priority": priority,
        "suggested_reply": (
            f"Thank you for contacting Pearl Pay. We have reviewed your {category.replace('_', ' ')} request "
            "and our team will follow up shortly."
        ),
        "sources": sources,
    }
    content, finish = json.dumps(decision), "stop"
    if "FAKE_LLM_TRUNCATE" in ticket:
        content, finish = content[: len(content) // 2], "length"
    elif "FAKE_LLM_INVALID" in ticket:
        content = "Sure! Here is the triage: priority high."
    prompt_tokens = len(user.split())
    completion_tokens = len(content.split())
    return 200, {
        "id": "chatcmpl-fake-" + hashlib.sha256(user.encode()).hexdigest()[:12],
        "object": "chat.completion",
        "created": 0,
        "model": body.get("model", "fake-chat"),
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish},
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def embeddings(body: dict, default_dimensions: int) -> tuple[int, dict]:
    inputs = body.get("input")
    if isinstance(inputs, str):
        inputs = [inputs]
    if not isinstance(inputs, list) or not inputs or not all(isinstance(t, str) for t in inputs):
        raise BadRequest("input must be a string or a non-empty list of strings")
    dims = int(body.get("dimensions") or default_dimensions)
    as_base64 = body.get("encoding_format") == "base64"
    data = []
    for i, text in enumerate(inputs):
        vector = hash_embedding(text, dims)
        value = base64.b64encode(struct.pack(f"<{dims}f", *vector)).decode() if as_base64 else vector
        data.append({"object": "embedding", "index": i, "embedding": value})
    tokens = sum(len(t.split()) for t in inputs)
    return 200, {
        "object": "list",
        "data": data,
        "model": body.get("model", "fake-embed"),
        "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
    }


def make_handler(default_dimensions: int, requests: deque) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 - quiet default access log
            pass

        def _reply(self, status: int, body: object) -> None:
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):  # noqa: N802
            if self.path == "/health":
                return self._reply(200, {"status": "ok"})
            if self.path == "/v1/models":
                models = [{"id": m, "object": "model", "owned_by": "fake"} for m in ("fake-chat", "fake-embed")]
                return self._reply(200, {"object": "list", "data": models})
            if self.path == "/_fake/requests":
                return self._reply(200, list(requests))
            return self._reply(404, {"error": {"message": "not found"}})

        def do_POST(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path not in ("/v1/chat/completions", "/v1/embeddings"):
                return self._reply(404, {"error": {"message": "not found"}})
            body: dict = {}
            try:
                parsed = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if not isinstance(parsed, dict):
                    raise BadRequest("body must be a JSON object")
                body = parsed
                if path == "/v1/chat/completions":
                    status, reply = chat_completion(body)
                else:
                    status, reply = embeddings(body, default_dimensions)
            except (BadRequest, json.JSONDecodeError, ValueError) as exc:
                status, reply = 400, {"error": {"message": str(exc), "type": "invalid_request_error"}}
            requests.append(
                {
                    "path": path,
                    "status": status,
                    "model": body.get("model"),
                    "temperature": body.get("temperature"),
                    "inputs": len(body["input"]) if isinstance(body.get("input"), list) else None,
                }
            )
            return self._reply(status, reply)

    return Handler


def make_server(port: int = 11434, dimensions: int = 768) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(dimensions, deque(maxlen=200)))
    server.daemon_threads = True
    return server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument("--dimensions", type=int, default=768)
    args = parser.parse_args()
    server = make_server(args.port, args.dimensions)
    print(f"fake LLM listening on http://127.0.0.1:{args.port}/v1 (embeddings: {args.dimensions} dims)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
