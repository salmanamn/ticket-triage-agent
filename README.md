# ticket-triage-agent

[![ci](https://github.com/salmanamn/ticket-triage-agent/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/salmanamn/ticket-triage-agent/actions/workflows/ci.yml)

Event-driven support-ticket triage:
HTTP API → Service Bus → Azure Functions (Python 3.13) → LLM + RAG (Cosmos DB vector search) → Cosmos DB → Event Grid → email.

The same code runs locally (`docker compose up` with emulators + Ollama) and on Azure (managed identity everywhere, no keys or connection strings).

Status: M7 — Terraform for the Azure stack (`infra/`: Flex Consumption, Service Bus, Cosmos DB serverless with vector search, Event Grid, identities and RBAC, diagnostics to the shared workspace), planned against floci-az and real Azure; Checkov and a Conftest gate in CI. `main` requires six checks: lint, unit, integration, tests-must-fail, iac-static, iac-plan.

Infrastructure: `infra/modules/stack` (composition root) → `infra/envs/local` (floci-az) and `infra/envs/azure` (remote state). Policies in `infra/policy/`.

Decisions: [docs/decisions.md](docs/decisions.md)