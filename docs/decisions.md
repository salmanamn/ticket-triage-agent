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

## D5 — Events and email
- Event Grid has no emulator: a local stub accepts CloudEvents and forwards them to the Functions Event Grid webhook.
- Email behind an adapter: Mailpit (SMTP) locally, Azure Communication Services Email with managed identity on Azure.

## D6 — Credentials
- Emulator well-known keys/connection strings only in gitignored `local.settings.json` and `.env`.
- Azure: identity-based connections only (`__fullyQualifiedNamespace`, `__accountEndpoint`), local/key auth disabled on every resource.