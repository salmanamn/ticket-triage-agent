import json
import logging
from functools import lru_cache

import azure.functions as func

from triage import cosmos, settings
from triage.agent import InvalidMessage, Triager, parse_message
from triage.ai import OpenAIChatModel, OpenAIEmbedder
from triage.ingest import handle_submission
from triage.queue import ServiceBusPublisher
from triage.retrieval import Retriever

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
_publisher = ServiceBusPublisher()
log = logging.getLogger("triage.function")


@lru_cache(maxsize=1)
def _triager() -> Triager:
    cfg = settings.triage()
    embedder = OpenAIEmbedder()
    return Triager(
        retriever=Retriever(cosmos.kb_container(), embedder),
        chat=OpenAIChatModel(cfg.chat_model, timeout_s=cfg.timeout_s, max_tokens=cfg.max_output_tokens),
        store=cosmos.CosmosTriageStore(cosmos.triage_container()),
        embedding_model=embedder.model,
        kb_k=cfg.kb_k,
        ticket_k=cfg.ticket_k,
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
