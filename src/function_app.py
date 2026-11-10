import json
import logging
from functools import lru_cache

import azure.functions as func

from triage import cosmos, settings
from triage.agent import InvalidMessage, Triager, parse_message
from triage.ai import OpenAIChatModel, OpenAIEmbedder
from triage.events import EventGridPublisher, EventRelay
from triage.ingest import handle_submission
from triage.notify import Mailboxes, Notifier, SmtpMailer
from triage.queue import ServiceBusPublisher
from triage.retrieval import Retriever

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
_publisher = ServiceBusPublisher()
log = logging.getLogger("triage.function")


@lru_cache(maxsize=1)
def _store() -> cosmos.CosmosTriageStore:
    return cosmos.CosmosTriageStore(cosmos.triage_container())


@lru_cache(maxsize=1)
def _triager() -> Triager:
    cfg = settings.triage()
    embedder = OpenAIEmbedder()
    return Triager(
        retriever=Retriever(cosmos.kb_container(), embedder),
        chat=OpenAIChatModel(cfg.chat_model, timeout_s=cfg.timeout_s, max_tokens=cfg.max_output_tokens),
        store=_store(),
        embedding_model=embedder.model,
        kb_k=cfg.kb_k,
        ticket_k=cfg.ticket_k,
    )


@lru_cache(maxsize=1)
def _relay() -> EventRelay:
    return EventRelay(_store(), EventGridPublisher(), settings.events().source)


@lru_cache(maxsize=1)
def _notifier() -> Notifier:
    cfg = settings.notify()
    return Notifier(
        _store(),
        SmtpMailer(cfg.smtp_host, cfg.smtp_port, cfg.smtp_starttls),
        Mailboxes(sender=cfg.sender, escalation=cfg.escalation_mailbox, review=cfg.review_mailbox),
    )


@app.route(route="tickets", methods=["POST"])
def submit_ticket(req: func.HttpRequest) -> func.HttpResponse:
    result = handle_submission(req.get_body(), _publisher)
    return func.HttpResponse(json.dumps(result.payload), status_code=result.status, mimetype="application/json")


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse('{"status":"ok"}', mimetype="application/json")


@app.service_bus_queue_trigger(arg_name="msg", queue_name="%TICKETS_QUEUE%", connection="ServiceBusConnection")
def triage_ticket(msg: func.ServiceBusMessage) -> None:
    """Any exception abandons the message; after MaxDeliveryCount the broker moves it to the DLQ."""
    attempt = msg.delivery_count or 1
    try:
        ticket = parse_message(msg.get_body(), msg.message_id)
    except InvalidMessage as exc:
        log.error("Rejected message %s (attempt %d): %s", msg.message_id, attempt, exc)
        raise

    try:
        outcome = _triager().triage(ticket, attempt=attempt, max_attempts=settings.triage().max_attempts)
    except Exception as exc:
        log.error("Triage failed for %s (attempt %d): %s", ticket.ticket_id, attempt, type(exc).__name__)
        raise

    if outcome.record:
        r = outcome.record
        log.info(
            "Triaged %s: category=%s priority=%s floor=%s injection=%s sources=%d latency_ms=%d attempt=%d",
            r.ticket_id,
            r.category,
            r.priority,
            r.priority_floor_applied,
            r.injection_suspected,
            len(r.sources),
            r.latency_ms,
            attempt,
        )

    # After the Cosmos write. Also runs on redeliveries, so a publish that failed earlier is retried here.
    try:
        status = _relay().publish_pending(ticket.ticket_id, record=outcome.record)
    except Exception as exc:
        log.error("Event publish failed for %s (attempt %d): %s", ticket.ticket_id, attempt, type(exc).__name__)
        raise
    log.info("Event relay for %s: %s", ticket.ticket_id, status)


@app.event_grid_trigger(arg_name="event")
def notify_ticket(event: func.CloudEvent) -> None:
    """Ticket.Triaged -> email. Any exception makes Event Grid (or the local stub) retry, then dead-letter."""
    try:
        outcome = _notifier().handle(event.type, event.id, event.get_json())
    except Exception as exc:
        log.error("Notify failed for event %s: %s", event.id, type(exc).__name__)
        raise
    log.info("Notify %s: %s route=%s", event.id, outcome.status, outcome.route)
