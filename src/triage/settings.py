"""Runtime settings from environment variables (same names locally and on Azure)."""

import os
from dataclasses import dataclass


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
