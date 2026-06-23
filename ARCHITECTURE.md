# Architecture

The shape is a small data service: **ingest → verify → store → serve**, with one external
dependency (DNS) handled defensively and every row scoped to a tenant.

```
   REST / CLI ──ingest──┐
                        ▼
                   ┌─────────┐     external: DNS/MX
                   │ verify  │◀── (timeout, retries+backoff,
                   │ engine  │     rate limit, cache)
                   └────┬────┘
        syntax → deliverability → dedup → status + confidence
                        ▼
                   ┌─────────┐
                   │ storage │  SQLite (default) / Postgres
                   │ (per-   │  models + tenant-scoped repository
                   │ tenant) │
                   └────┬────┘
            ┌───────────┼─────────────┐
            ▼           ▼             ▼
          REST        MCP server   warehouse export
        (FastAPI)   (agent tools)  (Parquet, tenant=<id>/)
```

## Layers

- **`api/`** — FastAPI routes and Pydantic schemas. Handlers are thin: validate input, call a
  service or the repository, shape the response. Dependencies (`session`, `tenant`,
  `verifier`) are injected with `Annotated[...]` so the network-touching pieces can be
  swapped in tests.
- **`services.py`** — use-cases (currently: verify-a-tenant's-contacts-and-flag-duplicates),
  callable identically from HTTP, the CLI, or a test.
- **`db/`** — the data model and **the one place tenant isolation is enforced**. The
  repository has no method that reads or writes a contact without a `tenant_id` in the WHERE
  clause; handlers get their tenant from the API key and can't reach past it. All SQL is
  parameterized by SQLAlchemy.
- **`verify/`** — pure, network-free syntax/normalization (`email.py`), the defensive DNS/MX
  client (`dns.py`), and the engine that turns the checks into a status + confidence
  (`engine.py`).
- **`export.py` / `mcp/`** — two more delivery surfaces over the same stored data.

## The external dependency (the interesting part)

`verify/dns.py` is where most of the integration judgment lives, because a network call to a
flaky external system is exactly what breaks in production:

- **Timeout** per attempt — one slow resolver can't hang a request.
- **Retries with exponential backoff + jitter**, but only on *transient* failures (timeout,
  SERVFAIL). `NXDOMAIN` means the domain does not exist, so it's returned immediately —
  retrying a definitive answer just wastes time and quota.
- **Client-side rate limit** — a bulk verify run paces itself instead of hammering the
  resolver.
- **Short-lived cache** — the same domains recur constantly across a contact list and their
  MX records don't change between requests.
- The resolver, clock, and sleep are **injected**, so all of this is unit-tested
  deterministically with no network and no real waiting.

A transient failure that exhausts retries returns `unknown` (→ status `risky`) rather than a
false negative, so a DNS hiccup never silently marks a good contact as undeliverable.

## Storage and migrations

SQLAlchemy 2.0 models. SQLite is the default so the service runs with no external services;
set `CV_DATABASE_URL` to a Postgres DSN to use Postgres. Schema changes are managed by
Alembic (`alembic upgrade head`); the SQLite demo path also supports `create_all` for a
zero-config start. Indexes cover the hot paths: list/search a tenant's contacts, and dedup
within a tenant by normalized email.

## Security & privacy

- **Tenancy:** API key → tenant; every query is tenant-scoped; a cross-tenant fetch returns
  404, not 403, so the API doesn't confirm another tenant's record exists.
- **Secrets:** API keys are stored only as a SHA-256 hash; the plaintext is shown once.
  Configuration and any DSNs come from the environment / a gitignored `.env`.
- **Data:** synthetic only — no real contact data or PII in the tree or in git history.
- **Error reporting:** Sentry is off unless a DSN is set, and is configured with
  `send_default_pii=False`, so contact data isn't shipped to an error backend.

## Observability

Structured JSON logs (`structlog`), with a request id generated per request, bound into the
log context for the life of the request, and echoed back in an `x-request-id` response
header — so one request is greppable end-to-end. Sentry is wired but optional and env-gated.

## What's deliberately out of scope

This is a focused portfolio artifact, not a product. No background workers/queue (verify runs
inline), no real third-party enrichment API (DNS/MX is the external call), no auth beyond API
keys, and the warehouse export writes to the local filesystem rather than a real S3/Snowflake
stage. Each of those is a known extension, not an accidental gap.
