"""OpenAI-compatible clients: Ollama /v1 locally (key), Azure OpenAI v1 endpoint (Entra ID) on Azure."""

from functools import lru_cache
from typing import Literal, Protocol

from openai import OpenAI

from . import settings

Purpose = Literal["query", "document"]
BATCH_SIZE = 32


class Embedder(Protocol):
    model: str
    dimensions: int

    def embed(self, texts: list[str], purpose: Purpose) -> list[list[float]]: ...


@lru_cache(maxsize=1)
def openai_client() -> OpenAI:
    cfg = settings.ai()
    if cfg.auth == "entra":
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
        return OpenAI(base_url=cfg.base_url, api_key=token_provider)
    return OpenAI(base_url=cfg.base_url, api_key=cfg.api_key or "unused")


class OpenAIEmbedder:
    def __init__(self, client: OpenAI | None = None, cfg: settings.AISettings | None = None):
        self.cfg = cfg or settings.ai()
        self._client = client or openai_client()
        self.model = self.cfg.embedding_model
        self.dimensions = self.cfg.embedding_dimensions

    def embed(self, texts: list[str], purpose: Purpose) -> list[list[float]]:
        prefix = self.cfg.query_prefix if purpose == "query" else self.cfg.doc_prefix
        extra = {"dimensions": self.dimensions} if self.cfg.request_dimensions else {}
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = [prefix + t for t in texts[start : start + BATCH_SIZE]]
            resp = self._client.embeddings.create(model=self.model, input=batch, **extra)
            for item in sorted(resp.data, key=lambda d: d.index):
                if len(item.embedding) != self.dimensions:
                    raise ValueError(f"{self.model} returned {len(item.embedding)} dims, expected {self.dimensions}")
                vectors.append(item.embedding)
        return vectors
