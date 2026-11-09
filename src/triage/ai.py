"""OpenAI-compatible clients: Ollama /v1 locally (key), Azure OpenAI v1 endpoint (Entra ID) on Azure."""

from functools import lru_cache
from typing import Any, Literal, Protocol

from openai import OpenAI

from . import settings

Purpose = Literal["query", "document"]
BATCH_SIZE = 32


class Embedder(Protocol):
    model: str
    dimensions: int

    def embed(self, texts: list[str], purpose: Purpose) -> list[list[float]]: ...


class ModelOutputError(Exception):
    """The model returned nothing usable (truncated, empty, or not matching the schema)."""


class ChatModel(Protocol):
    model: str

    def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any], name: str, temperature: float
    ) -> str: ...


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


class OpenAIChatModel:
    """Structured JSON via `response_format=json_schema` (Ollama: grammar-constrained; Azure OpenAI: strict)."""

    def __init__(self, model: str, client: OpenAI | None = None, timeout_s: float = 180.0, max_tokens: int = 700):
        self.model = model
        self._client = client or openai_client()
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens

    def complete_json(self, *, system: str, user: str, schema: dict[str, Any], name: str, temperature: float) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
            temperature=temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout_s,
        )
        choice = resp.choices[0]
        if choice.finish_reason == "length":
            raise ModelOutputError(f"output truncated at {self.max_tokens} tokens")
        if not choice.message.content:
            raise ModelOutputError("empty output")
        return choice.message.content
