"""Runtime settings from environment variables (same names locally and on Azure)."""

import os
from dataclasses import dataclass


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing setting {name}")
    return value


@dataclass(frozen=True)
class ServiceBusSettings:
    queue: str
    connection_string: str | None
    fully_qualified_namespace: str | None


def servicebus() -> ServiceBusSettings:
    """Local: ServiceBusConnection (emulator). Azure: ServiceBusConnection__fullyQualifiedNamespace (MI)."""
    conn = os.getenv("ServiceBusConnection")
    fqns = os.getenv("ServiceBusConnection__fullyQualifiedNamespace")
    if not conn and not fqns:
        raise RuntimeError(
            "Set ServiceBusConnection (local emulator) or ServiceBusConnection__fullyQualifiedNamespace (Azure)"
        )
    return ServiceBusSettings(
        queue=os.getenv("TICKETS_QUEUE", "tickets"),
        connection_string=conn,
        fully_qualified_namespace=fqns,
    )


@dataclass(frozen=True)
class AISettings:
    base_url: str
    auth: str  # "key" (Ollama, local) | "entra" (Azure OpenAI)
    api_key: str | None
    embedding_model: str
    embedding_dimensions: int
    request_dimensions: bool  # send `dimensions` (Azure text-embedding-3-*); Ollama models are fixed-size
    query_prefix: str
    doc_prefix: str


def ai() -> AISettings:
    auth = os.getenv("OPENAI_AUTH", "key")
    if auth not in ("key", "entra"):
        raise RuntimeError("OPENAI_AUTH must be 'key' or 'entra'")
    return AISettings(
        base_url=_require("OPENAI_BASE_URL"),
        auth=auth,
        api_key=os.getenv("OPENAI_API_KEY"),
        embedding_model=_require("EMBEDDING_MODEL"),
        embedding_dimensions=int(_require("EMBEDDING_DIMENSIONS")),
        request_dimensions=os.getenv("EMBEDDING_REQUEST_DIMENSIONS", "false").lower() == "true",
        query_prefix=os.getenv("EMBED_QUERY_PREFIX", ""),
        doc_prefix=os.getenv("EMBED_DOC_PREFIX", ""),
    )


@dataclass(frozen=True)
class CosmosSettings:
    endpoint: str
    key: str | None  # emulator only; Azure uses managed identity
    database: str
    kb_container: str
    triage_container: str


def cosmos() -> CosmosSettings:
    return CosmosSettings(
        endpoint=_require("COSMOS_ENDPOINT"),
        key=os.getenv("COSMOS_KEY"),
        database=os.getenv("COSMOS_DATABASE", "triage"),
        kb_container=os.getenv("COSMOS_KB_CONTAINER", "knowledge"),
        triage_container=os.getenv("COSMOS_TRIAGE_CONTAINER", "triage"),
    )


@dataclass(frozen=True)
class TriageSettings:
    chat_model: str  # Ollama model tag locally, Azure OpenAI deployment name on Azure
    kb_k: int
    ticket_k: int
    max_attempts: int  # must equal the queue's MaxDeliveryCount
    timeout_s: float
    max_output_tokens: int


def triage() -> TriageSettings:
    return TriageSettings(
        chat_model=_require("CHAT_MODEL"),
        kb_k=int(os.getenv("TRIAGE_KB_K", "3")),
        ticket_k=int(os.getenv("TRIAGE_TICKET_K", "3")),
        max_attempts=int(os.getenv("TRIAGE_MAX_ATTEMPTS", "5")),
        timeout_s=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "180")),
        max_output_tokens=int(os.getenv("TRIAGE_MAX_OUTPUT_TOKENS", "700")),
    )


@dataclass(frozen=True)
class EventSettings:
    topic_endpoint: (
        str  # stub: http://127.0.0.1:6100/api/events; Azure: https://<topic>.<region>-1.eventgrid.azure.net/api/events
    )
    topic_key: str | None  # local stub only; Azure uses managed identity (EventGrid Data Sender), local auth disabled
    source: str


def events() -> EventSettings:
    return EventSettings(
        topic_endpoint=_require("EVENTGRID_TOPIC_ENDPOINT"),
        topic_key=os.getenv("EVENTGRID_TOPIC_KEY"),
        source=os.getenv("EVENT_SOURCE", "/pearlpay/ticket-triage"),
    )


@dataclass(frozen=True)
class NotifySettings:
    transport: str  # "smtp" (Mailpit locally). Azure Communication Services Email is added at M8.
    smtp_host: str
    smtp_port: int
    smtp_starttls: bool
    sender: str
    escalation_mailbox: str  # High/Critical tickets
    review_mailbox: str  # injection_suspected tickets (human review before any reply)


def notify() -> NotifySettings:
    transport = os.getenv("EMAIL_TRANSPORT", "smtp")
    if transport != "smtp":
        raise RuntimeError("EMAIL_TRANSPORT must be 'smtp' (ACS Email arrives at M8)")
    return NotifySettings(
        transport=transport,
        smtp_host=os.getenv("SMTP_HOST", "127.0.0.1"),
        smtp_port=int(os.getenv("SMTP_PORT", "1025")),
        smtp_starttls=os.getenv("SMTP_STARTTLS", "false").lower() == "true",
        sender=_require("EMAIL_SENDER"),
        escalation_mailbox=_require("ESCALATION_MAILBOX"),
        review_mailbox=_require("REVIEW_MAILBOX"),
    )
