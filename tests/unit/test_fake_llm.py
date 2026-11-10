"""The fake LLM (scripts/fake_llm.py) through the real openai SDK and the production adapters. No emulators."""

import array
import base64
import importlib.util
import json
import math
import threading
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import openai
import pytest
from openai import OpenAI

from triage.agent import Triager
from triage.ai import ModelOutputError, OpenAIChatModel, OpenAIEmbedder
from triage.models import TRIAGE_JSON_SCHEMA, TicketMessage, TriageDecision
from triage.retrieval import Hit
from triage.settings import AISettings

ROOT = Path(__file__).resolve().parents[2]


def load_fake():
    spec = importlib.util.spec_from_file_location("fake_llm", ROOT / "scripts" / "fake_llm.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fake():
    server = load_fake().make_server(0, 768)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    yield base, OpenAI(base_url=f"{base}/v1", api_key="fake", max_retries=0)
    server.shutdown()


def ai_cfg(base: str, dimensions: int = 768, request_dimensions: bool = False) -> AISettings:
    return AISettings(
        base_url=f"{base}/v1",
        auth="key",
        api_key="fake",
        embedding_model="fake-embed",
        embedding_dimensions=dimensions,
        request_dimensions=request_dimensions,
        query_prefix="",
        doc_prefix="",
    )


def ticket(body: str, subject: str = "Help needed") -> TicketMessage:
    return TicketMessage(
        ticket_id="T-1",
        customer_email="alice@example.com",
        subject=subject,
        body=body,
        channel="web",
        received_at=datetime(2026, 11, 10, tzinfo=UTC),
    )


def prompt(body: str, subject: str = "Help needed") -> str:
    return (
        '<knowledge_base>\n<item id="kb-card-declines-2">\nCode 51\n</item>\n</knowledge_base>\n\n'
        '<similar_resolved_tickets>\n<item id="ticket-H-2001">\nDeclined 51\n</item>\n</similar_resolved_tickets>\n\n'
        f'<ticket channel="web">\nSubject: {subject}\n\n{body}\n</ticket>'
    )


def chat(client, body: str, **kwargs) -> str:
    model = OpenAIChatModel("fake-chat", client=client)
    args = {"system": "s", "user": prompt(body), "schema": TRIAGE_JSON_SCHEMA, "name": "t", "temperature": 0.0}
    return model.complete_json(**{**args, **kwargs})


class FixedRetriever:
    def search(self, query, k=5, kind=None):
        if kind == "kb":
            return [Hit("kb-card-declines-2", "kb", "card-declines", "Card payment declined", "Code 51", 0.8, {})]
        return [Hit("ticket-H-2001", "ticket", "H-2001", "Declined 51", "Declined", 0.9, {"priority": "high"})]


class MemoryStore:
    def __init__(self):
        self.docs = {}

    def get(self, ticket_id):
        return self.docs.get(ticket_id)

    def create(self, doc):
        if doc["id"] in self.docs:
            return False
        self.docs[doc["id"]] = doc
        return True

    def upsert(self, doc):
        self.docs[doc["id"]] = doc


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_embeddings_are_deterministic_unit_vectors(fake):
    base, client = fake
    embedder = OpenAIEmbedder(client=client, cfg=ai_cfg(base))
    a1, a2, b = embedder.embed(["card declined code 51", "card declined code 51", "otp sms not received"], "query")
    assert len(a1) == 768 and a1 == a2
    assert math.isclose(math.sqrt(sum(x * x for x in a1)), 1.0, rel_tol=1e-5)
    assert cosine(a1, embedder.embed(["my card was declined"], "query")[0]) > cosine(a1, b)


def test_embeddings_honour_dimensions_and_both_encodings(fake):
    base, client = fake
    (vector,) = OpenAIEmbedder(client=client, cfg=ai_cfg(base, 256, request_dimensions=True)).embed(["x yz"], "query")
    assert len(vector) == 256
    as_float = client.embeddings.create(model="fake-embed", input="card declined", encoding_format="float")
    as_b64 = client.embeddings.create(model="fake-embed", input="card declined", encoding_format="base64")
    decoded = array.array("f", base64.b64decode(as_b64.data[0].embedding)).tolist()  # the SDK's default format
    assert as_float.data[0].embedding == pytest.approx(decoded, abs=1e-6)


@pytest.mark.parametrize(
    ("body", "category", "priority"),
    [
        ("My card was declined at the supermarket with code 51 although my balance is fine.", "cards", "high"),
        ("How do I change the daily limit for international transfers in the app?", "transfers", "low"),
        ("Someone logged in to my account from a new device, it wasn't me.", "account_access", "critical"),
        ("I was charged twice for the same coffee order yesterday.", "disputes", "medium"),
        ("The app shows a blank page every evening after the update.", "other", "medium"),
    ],
)
def test_chat_returns_schema_valid_labels(fake, body, category, priority):
    decision = TriageDecision.model_validate(json.loads(chat(fake[1], body)))
    assert (decision.category, decision.priority) == (category, priority)
    assert decision.sources == ["kb-card-declines-2", "ticket-H-2001"]


def test_same_prompt_same_output(fake):
    body = "My card was declined with code 51."
    assert chat(fake[1], body) == chat(fake[1], body)


def test_truncation_marker_raises_model_output_error(fake):
    with pytest.raises(ModelOutputError, match="truncated"):
        chat(fake[1], "Card declined. FAKE_LLM_TRUNCATE")


def test_request_without_structured_output_is_rejected(fake):
    with pytest.raises(openai.BadRequestError, match="json_schema"):
        fake[1].chat.completions.create(model="fake-chat", messages=[{"role": "user", "content": prompt("Hi there")}])


def test_upstream_500_surfaces_as_sdk_error(fake):
    with pytest.raises(openai.InternalServerError):
        chat(fake[1], "Card declined. FAKE_LLM_HTTP500")


def test_triager_end_to_end_with_fake_llm(fake):
    base, client = fake
    store = MemoryStore()
    triager = Triager(
        retriever=FixedRetriever(),
        chat=OpenAIChatModel("fake-chat", client=client),
        store=store,
        embedding_model="fake-embed",
    )
    outcome = triager.triage(ticket("My card was declined with code 51 but my balance covers it."))
    assert outcome.status == "triaged"
    doc = store.docs["T-1"]
    assert (doc["category"], doc["priority"], doc["model"]) == ("cards", "high", "fake-chat")
    with urllib.request.urlopen(f"{base}/_fake/requests", timeout=5) as resp:  # noqa: S310 - local test server
        last = json.load(resp)[-1]
    assert (last["path"], last["temperature"]) == ("/v1/chat/completions", 0.0)


def test_triager_rejects_invalid_output_and_drops_invented_sources(fake):
    client = fake[1]
    triager = Triager(
        retriever=FixedRetriever(),
        chat=OpenAIChatModel("fake-chat", client=client),
        store=MemoryStore(),
        embedding_model="fake-embed",
    )
    with pytest.raises(ModelOutputError, match="validation"):
        triager.triage(ticket("Card declined. FAKE_LLM_INVALID"))
    assessment = triager.decide(ticket("Card declined. FAKE_LLM_INVENT_SOURCE"))
    assert "kb-invented-0" not in assessment.decision.sources
    assert assessment.decision.sources == ["kb-card-declines-2", "ticket-H-2001"]
