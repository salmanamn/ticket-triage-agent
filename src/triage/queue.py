"""Service Bus publisher: emulator connection string locally, managed identity on Azure."""

import threading
from functools import lru_cache

from azure.servicebus import ServiceBusClient, ServiceBusMessage

from . import settings

_lock = threading.Lock()  # sync SB clients aren't thread-safe; the Python worker may run sync functions in threads


@lru_cache(maxsize=1)
def _client() -> ServiceBusClient:
    sb = settings.servicebus()
    if sb.connection_string:
        return ServiceBusClient.from_connection_string(sb.connection_string)
    from azure.identity import DefaultAzureCredential  # Azure only; honours AZURE_CLIENT_ID for user-assigned MI

    return ServiceBusClient(sb.fully_qualified_namespace, credential=DefaultAzureCredential())


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
