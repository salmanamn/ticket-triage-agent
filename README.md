# ticket-triage-agent

[![ci](https://github.com/salmanamn/ticket-triage-agent/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/salmanamn/ticket-triage-agent/actions/workflows/ci.yml)

Event-driven support-ticket triage:
HTTP API → Service Bus → Azure Functions (Python 3.13) → LLM + RAG (Cosmos DB vector search) → Cosmos DB → Event Grid → email.

The same code runs locally (`docker compose up` with emulators + Ollama) and on Azure (managed identity everywhere, no keys or connection strings).

Status: M6 — CI on every PR (ruff, unit, integration against the emulators with a deterministic fake LLM, tests-must-fail); `main` protected with the four checks required.

Decisions: [docs/decisions.md](docs/decisions.md)