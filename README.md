# ticket-triage-agent

Event-driven support-ticket triage:
HTTP API → Service Bus → Azure Functions (Python 3.13) → LLM + RAG (Cosmos DB vector search) → Cosmos DB → Event Grid → email.

The same code runs locally (`docker compose up` with emulators + Ollama) and on Azure (managed identity everywhere, no keys or connection strings).

Status: M1 — local lab.

Decisions: [docs/decisions.md](docs/decisions.md)