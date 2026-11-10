"""Cosmos DB client: emulator key locally, managed identity on Azure."""

from functools import lru_cache
from typing import Any

from azure.cosmos import ContainerProxy, CosmosClient, PartitionKey
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError

from . import settings


@lru_cache(maxsize=1)
def client() -> CosmosClient:
    cfg = settings.cosmos()
    if cfg.key:
        return CosmosClient(cfg.endpoint, credential=cfg.key)
    from azure.identity import DefaultAzureCredential

    return CosmosClient(cfg.endpoint, credential=DefaultAzureCredential())


def kb_policies(dimensions: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Vector embedding policy + indexing policy (DiskANN on /embedding). Mirrored in Terraform at M7."""
    vector_policy = {
        "vectorEmbeddings": [
            {"path": "/embedding", "dataType": "float32", "distanceFunction": "cosine", "dimensions": dimensions}
        ]
    }
    indexing_policy = {
        "indexingMode": "consistent",
        "automatic": True,
        "includedPaths": [{"path": "/*"}],
        "excludedPaths": [{"path": '/"_etag"/?'}, {"path": "/embedding/*"}],
        "vectorIndexes": [{"path": "/embedding", "type": "diskANN"}],
    }
    return vector_policy, indexing_policy


def ensure_kb_container(dimensions: int) -> ContainerProxy:
    """Local emulator only. On Azure, Terraform owns databases/containers (data-plane RBAC can't create them)."""
    cfg = settings.cosmos()
    db = client().create_database_if_not_exists(cfg.database)
    vector_policy, indexing_policy = kb_policies(dimensions)
    return db.create_container_if_not_exists(
        id=cfg.kb_container,
        partition_key=PartitionKey(path="/kind"),
        vector_embedding_policy=vector_policy,
        indexing_policy=indexing_policy,
    )


def kb_container() -> ContainerProxy:
    cfg = settings.cosmos()
    return client().get_database_client(cfg.database).get_container_client(cfg.kb_container)


def ensure_triage_container() -> ContainerProxy:
    """Local emulator only (Terraform on Azure). Partition key /id: every access is a point read/write by ticket."""
    cfg = settings.cosmos()
    db = client().create_database_if_not_exists(cfg.database)
    return db.create_container_if_not_exists(id=cfg.triage_container, partition_key=PartitionKey(path="/id"))


def triage_container() -> ContainerProxy:
    cfg = settings.cosmos()
    return client().get_database_client(cfg.database).get_container_client(cfg.triage_container)


class CosmosTriageStore:
    def __init__(self, container: ContainerProxy):
        self.container = container

    def get(self, ticket_id: str) -> dict[str, Any] | None:
        try:
            return self.container.read_item(item=ticket_id, partition_key=ticket_id)
        except CosmosResourceNotFoundError:
            return None

    def create(self, doc: dict[str, Any]) -> bool:
        """Insert-only. False when the id already exists (another delivery won the race)."""
        try:
            self.container.create_item(doc)
            return True
        except CosmosResourceExistsError:
            return False

    def upsert(self, doc: dict[str, Any]) -> None:
        self.container.upsert_item(doc)

    def mark(self, ticket_id: str, fields: dict[str, Any]) -> None:
        """Set top-level fields with a partial update (patch), so concurrent writers never overwrite each other's
        fields. Values must be JSON-ready (use model_dump(mode="json"))."""
        ops = [{"op": "set", "path": f"/{name}", "value": value} for name, value in fields.items()]
        self.container.patch_item(item=ticket_id, partition_key=ticket_id, patch_operations=ops)
