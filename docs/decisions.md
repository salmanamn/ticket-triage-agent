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

## D10 — Triage model and structured output
- Local chat model `phi4-mini:3.8b` (Q4_K_M, 2.5 GB, MIT): no thinking mode, so CPU latency is predictable; the Phi family also exists in Azure AI Foundry. `qwen3.5:4b` not used locally because thinking is on by default (slow on CPU). Model name only from `CHAT_MODEL` (Azure: deployment name).
- One JSON schema (`TRIAGE_JSON_SCHEMA`) in the Azure OpenAI strict-mode subset: enums, all fields required, `additionalProperties: false`, no length keywords. Sent as `response_format: json_schema` (Ollama: grammar-constrained decoding; Azure: strict). `summary` comes first so it is generated before the labels.
- After generation, Pydantic (`TriageDecision`) enforces lengths and labels; cited source ids not in the retrieved set are dropped. Invalid or truncated output raises `ModelOutputError`.
- Temperature 0 on the first delivery, 0.4 on redeliveries (a deterministic retry would repeat the same failure).
- Priority is decided in order: (1) a pure how-to or information request is `low`, and KB escalation rules don't apply to it; (2) a KB "When to escalate" rule that describes what happened to the customer; (3) the general rubric. Added after the first eval: the model applied escalation rules to questions (E03, E07). Body capped at 2,000 chars, each retrieved item at 600 chars, k = 3 KB + 3 tickets.
- Deterministic rules on the original text after generation: fraud / account-takeover wording raises priority to at least `high` (`priority_floor_applied`), never lowers it.
- Prompt injection, in layers. Labels are enums, so injected text can't add actions or fields. Sentences matching an injection denylist are removed before retrieval and the model call, and the ticket is flagged `injection_suspected`. A flagged ticket can't be `critical` unless the fraud pattern matches. Prompt instructions alone did not hold: the first eval's E14 got `critical` because the ticket asked for it. A denylist is bypassable, so M5 routes flagged tickets to human review.
- Ollama keeps both models resident (`OLLAMA_MAX_LOADED_MODELS=2`) with an 8k context so the prompt is never silently truncated.

## D11 — Idempotency and poison messages
- Triage record id = `ticket_id` = `MessageId`; container `triage`, partition key `/id` (point reads/writes only).
- Read before work: an existing `triaged` record means a redelivery, so it is skipped without a model call. Writes are insert-only (`create_item`), so on a race the first result wins. A `failed` record is replaced by a later success (e.g. a DLQ resubmit).
- Built-in Service Bus trigger with auto-complete: any exception abandons the message, and the broker dead-letters it at `MaxDeliveryCount` 5 (`TRIAGE_MAX_ATTEMPTS` must match). Explicit dead-lettering isn't used because the Python SDK-type bindings (`azurefunctions-extensions-bindings-servicebus`) are still beta/preview.
- The last attempt writes a `status: failed` record (error class plus a short message, never ticket input) before raising, so failures are visible in Cosmos as well as in the DLQ.
- Contract violations (bad JSON, unknown `schema_version`, extra fields, `MessageId` ≠ `ticket_id`) are rejected before retrieval or a model call.
- Concurrency: `maxConcurrentCalls` 1 locally (CPU model, app-setting override), 4 in `host.json` for Azure; lock auto-renewal 10 min; function timeout 10 min.

## D12 — Triage eval
- `eval/tickets.jsonl`: 14 tickets that aren't in the KB history, labelled from the KB escalation rules, across all categories, plus one prompt-injection case (E14).
- `eval/holdout.jsonl`: 8 more tickets (one injection, H07) that are run once after tuning and never tuned against. Prompt and rule changes are made against `tickets.jsonl` only, so the holdout is the honest score.
- `scripts/eval_triage.py --cases <file>` runs real retrieval plus the chat model with no Cosmos writes. Gates: category ≥ 85 %, priority exact ≥ 70 %, within one level ≥ 95 %, critical recall 100 %, valid output 100 %. Injection resisted means the case is flagged and doesn't get the priority the attacker asked for; normal tickets must not be flagged. Reports go to `docs/evidence/m4-eval.md` (tuning) and `docs/evidence/m4-eval-holdout.md`.
- CI keeps deterministic fakes (M6). The eval is run by hand after any model or prompt change.
- First holdout run (n = 8): category 87.5 %, priority exact 75 %, within one level 87.5 %, critical recall 1/2, injection resisted. Misses: H05, an unrecognised charge, triaged `high` not `critical` (the fraud floor stops at `high` while the KB says critical); H07, where injection residue ("approve a refund") pulled the category to `disputes` and the flag cap held priority at `high`. Both still reach the High/Critical notify path at M5. The tuning set gates the milestone; the holdout is reported, never tuned against. Any fix needs a new holdout written before the change.

## D13 — Ticket.Triaged event and notify
- After the Cosmos write the triage function publishes a CloudEvents 1.0 `Ticket.Triaged` (id = ticket id, subject `tickets/<id>`, source `/pearlpay/ticket-triage`) with the `azure-eventgrid` SDK: key locally (stub), managed identity + EventGrid Data Sender on Azure (topic local auth disabled).
- Outbox-lite: the record keeps `event_published_at`. The relay also runs on Service Bus redeliveries, so a failed publish is retried without re-running triage; after 5 failed deliveries the message goes to the DLQ and the record stays `triaged` with no `event_published_at`. `scripts/publish_event.py <id>` republishes.
- Event data is thin (ids, labels, flags, time): no customer email, subject, body or model text in Event Grid. The notify function reads the full record from Cosmos (claim check).
- Local Event Grid: `scripts/eventgrid_stub.py` (stdlib) accepts CloudEvents on `/api/events` with `aeg-sas-key`, filters by event type, pushes to the Functions webhook `/runtime/webhooks/EventGrid?functionName=notify_ticket` with `aeg-event-type: Notification`, retries with backoff, no retry on 400/413, dead-letters to `data/eventgrid/deadletter/`. No validation handshake, advanced filters or batching. Key read from `local.settings.json`.
- Routing in code, not in subscription filters (Event Grid ANDs advanced filters, and the rule needs OR): `injection_suspected` → human-review mailbox whatever the priority (labels and draft may be attacker-influenced); else High/Critical → escalations; else no email. The subscription filters on event type only.
- Idempotency: `notification` on the record (route, event id, Message-ID, times). check → send → mark, so at-least-once: a crash between send and mark, or two concurrent deliveries of the same event, can repeat one email with the same Message-ID. Chosen over claim-first (at-most-once) because a lost critical alert costs more than a duplicate. Fields are written with Cosmos patch (`set`) so the relay and notify never overwrite each other.
- Email: plain text; subject built only from the validated ticket id and enum labels (no customer text in headers); body labels the customer subject as untrusted; the suggested reply is always marked DRAFT. Mailpit (SMTP) locally; ACS Email with managed identity at M8 behind the same `Mailer` interface.

## D14 — CI and branch protection
- One workflow, `.github/workflows/ci.yml`, on PRs to `main`, pushes to `main` and manual runs. Four jobs, all required on `main`: `lint` (ruff format/check, `uv sync --locked`, `src/requirements.txt` re-exported and diffed, CI emulator images identical to `docker-compose.yml`), `unit` (no emulators), `integration` (emulators), `tests-must-fail` (mutations). `ubuntu-24.04`, `permissions: contents: read`, checkout without persisted credentials, uv pinned via `pipx install uv==<version>` (setup-uv v8 has immutable full-version tags only); no secrets anywhere, so Dependabot and fork PRs run the same jobs.
- Emulators in CI use the same pinned images as the local lab. SQL Server, Cosmos vNext and Mailpit are service containers. The Service Bus emulator is started with `docker run` on the job's service network (`job.services.mssql.network`) after checkout: service containers start before checkout, so the repo's `config.json` can't be mounted into one. SQL Server's SA password is a throwaway literal (CI-only, port not published). Ollama, Azurite and the Functions host are not in CI.
- LLM in CI: `scripts/fake_llm.py`, a stdlib OpenAI-compatible `/v1` server (chat completions + embeddings). It rejects requests without strict `json_schema` output, answers with labels from keyword rules on the `<ticket>` block, cites the first retrieved ids, serves hashing bag-of-words embeddings (float and the SDK's default base64, `dimensions` honoured), and has markers for truncation, invalid JSON, invented sources and HTTP 500. The production `OpenAIChatModel` / `OpenAIEmbedder` and the openai SDK run unchanged against it. It is not a quality signal; the eval (D12) stays a manual gate after model or prompt changes.
- microsoft/aoai-api-simulator evaluated and not used for CI: last release v0.6 (2024-11), generated chat content is lorem ipsum without `json_schema` support, embeddings are random, and it serves only the classic `/openai/deployments/...` routes (we use the v1 endpoint). It may still fit throttling/latency tests at M8.
- `tests/integration/test_pipeline_emulators.py` runs the pipeline without the Functions host: ingest → Service Bus emulator → triage (fake LLM, Cosmos vector search over the real KB) → Cosmos record → Event Grid stub → notify → Mailpit, plus redelivery/duplicate-event idempotency and the last-attempt failure record. The Functions bindings themselves are covered by the local E2E runs (M4/M5), not CI.
- `scripts/tests_must_fail.py` applies 15 known-bad mutations (fraud floor, injection strip/cap, invented sources, redelivery skip, deterministic first attempt, structured output, MessageId, error echo, PII in events, republish, injection routing, duplicate email, customer text in subject, stub retrying 400) to a temporary copy and requires the unit tests to fail for each. A mutation whose anchor text disappears fails the job, so mutations are updated together with the code.
- `main`: classic branch protection via `scripts/protect-main.sh <green ref>`: PR required (0 approvals, solo repo), strict required checks pinned to the GitHub Actions app id read from a green commit, admins included, linear history, conversation resolution, no force-push or deletion. Dependabot (github-actions, weekly, grouped); Python deps are bumped by hand (`uv lock` + `uv export`).

## D15 — Network posture on Azure: public endpoints, Entra ID only
- The Flex app has no VNet integration in the lab, so Service Bus, Cosmos DB, Event Grid and storage keep public endpoints. Service Bus Standard has no private endpoints at all (Premium ≈ $680/month).
- Instead every data service refuses keys: Service Bus `local_auth_enabled = false`, Cosmos `local_authentication_enabled = false` + no key metadata writes, Event Grid `local_auth_enabled = false`, storage Shared Key off, Application Insights local auth off. TLS 1.2 minimum everywhere.
- Each Checkov finding this causes is skipped inline with this decision as the reason. Private endpoints + Flex VNet integration move to Project 7 (capstone).

## D16 — Identities and RBAC
- One user-assigned identity, `id-<name>-app`, runs the Function App and reads its deployment package; app settings name it (`AZURE_CLIENT_ID`, `<connection>__clientId`, `__credential = managedidentity`). User-assigned so its roles exist before the app starts.
- Data roles at the narrowest scope, by built-in role id: Storage Blob Data Owner (host storage account), Service Bus Data Sender + Receiver (`tickets` queue), EventGrid Data Sender (topic), Monitoring Metrics Publisher (App Insights), Cosmos Built-in Data Contributor (database `triage`). No Owner/Contributor, nothing at resource-group or subscription scope; the Conftest gate enforces the role allowlist.
- The Event Grid topic has a system-assigned identity with Storage Blob Data Contributor on the `eventgrid-deadletter` container only; the subscription dead-letters with that identity (storage has no keys).
- Azure OpenAI's Cognitive Services OpenAI User is on the allowlist for M8.

## D17 — Cosmos knowledge container as an ARM template deployment
- azurerm 4.x has no vector embedding policy or vector index on `azurerm_cosmosdb_sql_container`, and Cosmos can't add a vector policy to an existing container. The `knowledge` container is created by `azurerm_resource_group_template_deployment` from `infra/modules/cosmos/knowledge-container.json` (API 2025-10-15); `triage` stays a plain azurerm container. Same pattern as Project 1's CMK.
- The template mirrors `triage.cosmos.kb_policies()`; `tests/unit/test_infra_contract.py` fails when the two differ (plus delivery count and embedding size against the emulator config and local settings), and `tests_must_fail` has two mutations for it.
- azapi was the alternative: one more provider, for a single resource.

## D18 — Terraform layout, floci-az scope and the IaC gates
- `infra/modules/stack` is the composition root (RG, app identity, App Insights, RBAC) over `storage`, `messaging`, `cosmos`, `events`, `functionapp`. `infra/envs/local` (floci-az, local state) and `infra/envs/azure` (shared remote state `stslztfstatet8trox`, key `ticket-triage-azure.tfstate`) call only the stack and differ in provider and inputs.
- floci-az 0.16.0 (latest release, 2026-10-31; read from its source at the tag) has ARM handlers for resource groups, storage accounts + containers, user-assigned identities, Event Grid topics + event subscriptions (WebHook destinations only, dead-letter to blob), Log Analytics workspaces, diagnostic settings and `Microsoft.Web/sites`. It has none for `Microsoft.ServiceBus`, `Microsoft.DocumentDB`, `Microsoft.Web/serverfarms` (so no FC1 plan), `Microsoft.Insights/components` or `Microsoft.Authorization/roleAssignments`: those answer 404. Its Event Grid PUTs answer 200, but azurerm 4.81 (go-azure-sdk eventgrid 2025-02-15) accepts only 201 for topic and subscription CreateOrUpdate, so the apply fails after floci-az has stored the topic (seen in M7). Workspaces still can't be created by azurerm (no `deletedWorkspaces`), but diagnostic settings are stored without checking their destination.
- So `envs/local` has two modes: default = the floci-az subset (7 resources: RG, identity, suffix, storage + 2 containers, blob diagnostic setting), applied create/destroy only (`scripts/iac.sh apply-local`; RG deletion with leftovers allowed, emulator only); `-var full_stack=true` = every component, plan only. The local app runtime stays on the dedicated emulators (D4, D7) and the Event Grid stub (D13).
- On Azure the notify subscription waits for the code (`notify_subscription_enabled = false` until M8): Event Grid validates the function endpoint on create.
- CI adds two required jobs. `iac-static`: `terraform fmt`, `validate` of both envs (separate `TF_DATA_DIR`), Checkov 3.4.3 per root, `conftest verify` (20 policy unit tests). `iac-plan`: floci-az 0.16.0 service container → full-stack plan → `conftest test` → `scripts/iac_must_fail.py` (22 mutations of the real plan, each must be denied).
- The Function App's `app_settings` are unknown in a plan (azurerm can't plan a map with unknown values), so the stack outputs `app_setting_names` and the gate checks those: no connection strings, keys or secrets by name.
- azurerm reads Service Bus and Cosmos keys on refresh even with local auth off (Project 1 gotcha): from M8 that happens on every plan. Project 2's SLZ-003 stays quiet only if M8 adds federated credentials to the Project 1 CI identities it allowlists; a laptop plan against a deployed stack fires it (true positive, operator).

## D19 — Azure OpenAI: models, request shape, Entra only
- One `kind = OpenAI` account per stack (`oai-<name>-<suffix>`, custom subdomain = name: required for Entra tokens), local (key) auth off, outbound network access restricted with an empty allowlist, public endpoint (D15). The app identity gets Cognitive Services OpenAI User on the account; nothing else.
- Chat: **gpt-5.4-mini 2026-03-17, Global Standard** (GA, structured outputs, Chat Completions; retires 2027-09). gpt-4.1-mini and gpt-4o-mini are *Deprecated*: blocked for subscriptions that never deployed them, which this one hasn't. gpt-5.x are reasoning models: they reject `temperature` and `max_tokens`. `CHAT_REASONING_EFFORT=low` switches `OpenAIChatModel` to `reasoning_effort` + `max_completion_tokens` (4000: hidden reasoning tokens count against it) and drops the temperature; locally (empty) Ollama keeps `temperature` + `max_tokens`. So D10's temperature 0/0.4 split is local-only.
- Embeddings: **text-embedding-3-small v1, Standard (regional uaenorth)**, `dimensions = 768` (D9, `EMBEDDING_REQUEST_DIMENSIONS=true`). Deployment names equal the model names, so `embeddingModel` in the KB documents reads the same as the model.
- Capacity 50k TPM each, `OnceCurrentVersionExpired`; the Conftest gate denies any Provisioned SKU (billed per hour, used or not).
- The model changes on Azure, so the D12 eval is re-run there and reported (`docs/evidence/m8-eval-azure.md`); nothing is tuned against it.

## D20 — Email on Azure: ACS Email with managed identity
- Email Communication Service + **Azure-managed domain** (`DoNotReply@<guid>.azurecomm.net`, 5 emails/min and 10/h per subscription: enough for the lab) linked to a Communication Services resource, data location UAE.
- The Communication Services resource is an **ARM template deployment** (`infra/modules/email/communication-service.json`, API 2025-05-01): azurerm 4.81's `azurerm_communication_service` has no `disableLocalAuth` and lists the keys on every refresh. The template sets `disableLocalAuth = true` and `linkedDomains`; Conftest denies the azurerm resource and any template with local auth on. Same pattern as D17.
- Sending role: custom **"SLZ Email Sender"** (`Microsoft.Communication/CommunicationServices/Read` + `/Write`, `Microsoft.Communication/EmailServices/write`: Microsoft's documented minimum) defined in Project 1's bootstrap with a fixed id (`fca60e2f-…`), assigned to the app identity on the ACS resource only. The built-in Communication and Email Service Owner is broader.
- `AcsMailer` sends the message `build_email` already builds (plain text, subject from ids and enums only); ACS sets From/To/Subject/Date itself, and only `X-Ticket-Id` / `X-Triage-Route` pass through. `begin_send(..., polling=False)`: the 202 means queued; delivery is in `ACSEmailStatusUpdateOperational`. Operation-Id = uuid5(Message-ID), so a resend after a crash between send and mark reuses the operation; a 409 counts as queued (D13 stays at-least-once).
- Recipients are real mailboxes in a sensitive Terraform variable (`notify_mailboxes`, CI secret `NOTIFY_MAILBOXES`): shown as `(sensitive value)` in plans and summaries, names only in `app_setting_names`.

## D21 — Azure deploys through CI (deploy.yml)
- Same identities as Project 1 (`id-slz-plan`, `id-slz-apply`) with three more federated credentials (this repo's `pull_request`, `main`, `environment:azure`; subject prefix read from a real token), so Project 2's KnownPrincipals allowlist still covers CI for SLZ-001/003.
- Project 1 bootstrap changes (applied by hand): the apply identity's RBAC Administrator ABAC list gains the roles this stack assigns (Storage Blob Data Owner/Contributor, Service Bus Data Sender/Receiver, EventGrid Data Sender, Monitoring Metrics Publisher, Cognitive Services OpenAI User, SLZ Email Sender); the plan identity gets "SLZ Terraform Plan - Refresh List Actions" (Cosmos listKeys/readonlykeys/listConnectionStrings, Event Grid topic listKeys and subscription getFullUrl, `Microsoft.Web/sites/config/list/action`): azurerm's refresh of a deployed stack calls these even with local auth off. Service Bus' listKeys failure is only a warning in azurerm, so it isn't granted.
- The ABAC condition can't restrict scope or principal: the apply identity could assign these roles anywhere. Accepted for the lab because every apply is an approved, exact, policy-gated plan: `deploy.yml` runs the Conftest gate (role allowlist, resource scopes, ServicePrincipal only except the operator's OpenAI role) on the plan it uploads.
- Flow: PR → plan + gate + summary (not a required check). Dispatch `apply` (notify off) → `deploy-code` (environment approval, `az login` with the job's OIDC token, zip of `src/`, `az functionapp deployment source config-zip --build-remote true`, wait until the 4 functions are listed) → `apply --notify` (Event Grid validates `notify_ticket`) → work → `destroy` the same night. `scripts/ci-deploy.sh` dispatches, shows the plan and approves.
- Operator: with `OPERATOR_OBJECT_ID` set, the stack gives the human operator Cosmos Built-in Data Contributor on db `triage` and Cognitive Services OpenAI User on the account, to seed the KB, run the eval and read records from the laptop (`TRIAGE_SETTINGS=src/azure.settings.json`, written by `scripts/azure_settings.py`). A `User` principal may hold no other role (Conftest).

## D22 — Teardown
- `envs/azure` keeps `prevent_deletion_if_contains_resources = true`, so anything left in `rg-triage-azure` that Terraform doesn't own fails the destroy loudly. Known Azure-generated resources are handled explicitly: `application_insights.disable_generated_rule = true` (the "Failure Anomalies" rule is disabled on create and deleted with the component) and `scripts/predestroy.sh` deletes the "Application Insights Smart Detection" action group before the destroy apply.
- `cognitive_account.purge_soft_delete_on_destroy = true`: a soft-deleted account would hold its name and quota for 48 h.
- The destroy job ends with `az group exists` = false. The Event Grid dead-letter container and every log are gone with the stack; the telemetry stays in `log-slz-platform` (90 days).
