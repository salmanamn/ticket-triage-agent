# Decisions

## D1 — Function language and hosting
- Python 3.13, Azure Functions v2 programming model.
- Azure hosting: Flex Consumption. Linux Consumption gets no Python versions after 3.12 and is retiring.
- Local Python managed by uv (`.venv` with 3.13).

## D2 — Vector store: Cosmos DB for NoSQL vector search (DiskANN)
- Replaces Qdrant from the kickoff notes.
- The Cosmos vNext emulator supports DiskANN vector indexes, so retrieval code is identical locally and on Azure.
- One data service for triage results and retrieval; managed identity + data-plane RBAC; serverless.
- Retriever sits behind an interface; Qdrant moves to Project 6.

## D3 — LLM access
- One `openai` SDK client against OpenAI-compatible endpoints: Ollama `/v1` locally, Azure OpenAI v1 endpoint with Entra ID on Azure.
- Endpoint, model and deployment names from env vars only.
- CI uses a deterministic fake; aoai-api-simulator evaluated at M6 (upstream marks it work in progress).

## D4 — Messaging: Service Bus emulator 2.0.0
- Backend: SQL Server 2022 container (SQL Edge no longer used).
- Entities declared in `emulators/servicebus/config.json`; the emulator's admin client is .NET-only, and entities don't persist across restarts.
- Emulator has no Entra ID, no partitioning; 1 namespace, 256 KB messages, 1 h max TTL.
- Emulator caps the duplicate-detection window at 5 min (`PT5M`); Azure keeps 10 min (`PT10M`), set in Terraform at M7.

## D5 — Events and email
- Event Grid has no emulator: a local stub accepts CloudEvents and forwards them to the Functions Event Grid webhook.
- Email behind an adapter: Mailpit (SMTP) locally, Azure Communication Services Email with managed identity on Azure.

## D6 — Credentials
- Emulator well-known keys/connection strings only in gitignored `local.settings.json` and `.env`.
- Azure: identity-based connections only (`__fullyQualifiedNamespace`, `__accountEndpoint`), local/key auth disabled on every resource.

## D7 — Local lab shape
- Core services always on: SQL Server (SB backend, capped 1.5 GB), Service Bus emulator, Cosmos vNext (HTTP, health on 8082), Azurite.
- Ollama (`--profile ai`) and Mailpit (`--profile notify`) start only when a milestone needs them; never run alongside the Project 2 Kusto lab.
- All ports bound to 127.0.0.1 (emulators use well-known keys). Floating tags pinned by digest; Service Bus emulator restarts re-create entities from config.json.

## D8 — Ingest
- `POST /api/tickets` (function key on Azure) validates with Pydantic (`extra=forbid`, size caps, 32 KB body limit) and publishes via the Service Bus SDK, not an output binding: Python output bindings can't set `MessageId`, which duplicate detection needs.
- `ticket_id` is the client idempotency key (generated UUID when omitted) and becomes `MessageId`; retries within the detection window are dropped by the broker.
- Same setting for SDK and trigger: `ServiceBusConnection` (emulator string, local) / `ServiceBusConnection__fullyQualifiedNamespace` + managed identity (Azure).
- Ingest logic is runtime-independent (`triage/ingest.py`) for unit tests. Errors never echo input; logs carry ticket id and channel only (no email/body).
- Queue contract `TicketMessage` carries `schema_version`.

## D9 — Retrieval
- One `knowledge` container, partition key `/kind` (`kb` | `ticket`), vector policy `/embedding` float32 cosine 768 dims, DiskANN index; `/embedding/*` excluded from the regular index.
- Local: `nomic-embed-text` via Ollama with `search_query:` / `search_document:` prefixes. Azure: `text-embedding-3-small` with `dimensions=768` (`EMBEDDING_REQUEST_DIMENSIONS=true`). Each environment indexes with its own model; queries filter on `embeddingModel`.
- KB articles are chunked on `##` headings (max 1,500 chars, title prepended); resolved tickets embed subject + body, with category/priority/resolution as metadata for few-shot triage.
- Database/container creation is local-only; on Azure, Terraform owns them (Cosmos data-plane RBAC can't create containers). Azure account needs the NoSQL vector search capability.
- CI uses a deterministic hashing embedder against the real Cosmos emulator; embedding quality is checked manually here and by the triage eval set at M4.
