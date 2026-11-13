# ticket-triage-agent

[![ci](https://github.com/salmanamn/ticket-triage-agent/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/salmanamn/ticket-triage-agent/actions/workflows/ci.yml)

Event-driven support-ticket triage:
HTTP API → Service Bus → Azure Functions (Python 3.13) → LLM + RAG (Cosmos DB vector search) → Cosmos DB → Event Grid → email.

The same code runs locally (`docker compose up` with emulators + Ollama) and on Azure (managed identity everywhere, no keys or connection strings).

Status: M8 — deployed to real Azure through CI with GitHub OIDC (`.github/workflows/deploy.yml`: PR plan, approval-gated exact-plan apply/destroy, code deploy to Flex Consumption), with Azure OpenAI (gpt-5.4-mini + text-embedding-3-small) and Azure Communication Services Email; end-to-end run on Azure (high / injection / low) with telemetry in the shared Log Analytics workspace, stack destroyed the same night. `main` requires six checks: lint, unit, integration, tests-must-fail, iac-static, iac-plan.

Infrastructure: `infra/modules/stack` (composition root) → `infra/envs/local` (floci-az) and `infra/envs/azure` (remote state, deployed only by `deploy.yml`). Policies in `infra/policy/`.

Azure session: `./scripts/ci-deploy.sh apply` → `./scripts/ci-deploy.sh deploy-code` → `./scripts/ci-deploy.sh apply --notify` → seed + E2E → `./scripts/ci-deploy.sh destroy`.

Decisions: [docs/decisions.md](docs/decisions.md)
