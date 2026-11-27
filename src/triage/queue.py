"""Service Bus publisher: emulator connection string locally, managed identity on Azure."""

import threading
from functools import lru_cache

from azure.servicebus import ServiceBusClient, ServiceBusMessage

from . import settings

_lock = threading.Lock()  # sync SB clients aren't thread-safe; the Python worker may run sync functions in threads
_depth_lock = threading.Lock()  # the queue depth's own client, same reason


def _new_client(**options) -> ServiceBusClient:
    sb = settings.servicebus()
    if sb.connection_string:
        return ServiceBusClient.from_connection_string(sb.connection_string, **options)
    from azure.identity import DefaultAzureCredential  # Azure only; honours AZURE_CLIENT_ID for user-assigned MI

    return ServiceBusClient(sb.fully_qualified_namespace, credential=DefaultAzureCredential(), **options)


@lru_cache(maxsize=1)
def _client() -> ServiceBusClient:
    return _new_client()


@lru_cache(maxsize=1)
def _depth_client() -> ServiceBusClient:
    """The queue depth's own client: no retries, so an unreachable queue answers 503 at once, not after the
    SDK's backoff (KEDA's HTTP timeout is 3 s; the image check gave up after 10 s)."""
    return _new_client(retry_total=0)


class ServiceBusPublisher:
    def publish(self, *, message_id: str, body: str, subject: str, properties: dict[str, str]) -> None:
        message = ServiceBusMessage(
            body,
            message_id=message_id,
            content_type="application/json",
            subject=subject,
            application_properties=properties,
        )
        with _lock, _client().get_queue_sender(settings.servicebus().queue) as sender:
            sender.send_messages(message)


QUEUE_DEPTH_LIMIT = 100
QUEUE_DEPTH_TIMEOUT_S = 5


def queue_depth(limit: int = QUEUE_DEPTH_LIMIT) -> int:
    """Active messages on the tickets queue, counted by peeking (nothing is locked or removed), at most `limit`.

    For KEDA on the laptop only (D29): its Service Bus scaler reads the length through the management API over
    HTTPS, which the emulator doesn't serve. A fresh receiver each time, so the peek starts at the first message.
    """
    with _depth_lock, _depth_client().get_queue_receiver(settings.servicebus().queue) as receiver:
        return len(receiver.peek_messages(max_message_count=limit, timeout=QUEUE_DEPTH_TIMEOUT_S))
