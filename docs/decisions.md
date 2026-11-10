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
