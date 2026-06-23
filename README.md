# contact-verifier

A small service that **ingests B2B contact records, verifies them, and serves the verified
data** over a REST API, an MCP server, and a warehouse export — with the things that matter
when you handle other people's data: per-tenant isolation, careful handling of an external
dependency, and an honest privacy posture.

> **Status: portfolio prototype.** It runs end-to-end from a clean clone on SQLite with no
> external services. All sample data is **synthetic** — there is no real contact data, PII,
> or customer data anywhere in the repo. "Verification" here means email **syntax + DNS/MX
> deliverability**, not a paid email-validation API.

## What it does

```
  ingest (REST / CLI)
        │
        ▼
  verify ── syntax → DNS/MX deliverability → dedup → confidence
        │        (external call: timeout, retries+backoff, rate limit, cache)
        ▼
  store  ── one row per contact, every row scoped to a tenant
        │        (SQLite by default; Postgres via DATABASE_URL + Alembic)
        ├──▶ REST API      paginated, API-key auth, tenant-scoped
        ├──▶ MCP server    the same data as agent tools
        └──▶ warehouse     Parquet export, tenant=<id>/ partitions (S3 / Snowflake-stage shape)
```

Each contact is verified to a status — `valid`, `invalid`, `risky`, or `unknown` — with an
explainable confidence, and later records with the same (normalized) email are flagged as
duplicates of the canonical one.

## Quick start (about 2 minutes)

```bash
pip install -e ".[dev,mcp]"          # Python 3.11+; SQLite, no services needed

# Drive the whole flow from the CLI:
KEY=$(contact-verifier provision --name "Acme" | awk '/API key/{print $NF}')
contact-verifier seed   --key "$KEY"     # 15 synthetic sample contacts
contact-verifier verify --key "$KEY"     # real DNS: valid domains resolve, fakes don't
contact-verifier export --key "$KEY"     # -> warehouse/tenant=<id>/contacts-*.parquet
```

Or run the API and call it over HTTP:

```bash
contact-verifier serve                   # http://127.0.0.1:8000  (/docs for OpenAPI)

curl -s -X POST localhost:8000/v1/contacts -H "X-API-Key: $KEY" \
  -H 'content-type: application/json' \
  -d '{"contacts":[{"email":"jane@example.com"},{"email":"bad-syntax"}]}'
curl -s -X POST localhost:8000/v1/contacts/verify -H "X-API-Key: $KEY"
curl -s "localhost:8000/v1/contacts?status=valid" -H "X-API-Key: $KEY"
```

To use Postgres instead of SQLite: `docker compose up -d db`, then
`CV_DATABASE_URL=postgresql+psycopg://cv:cv@localhost:5432/contact_verifier alembic upgrade head`
(install the driver with `pip install -e ".[postgres]"`).

## What to look at (the craft)

- **External-dependency handling** — `verify/dns.py`: per-attempt timeout, bounded
  exponential backoff + jitter on *transient* failures only (NXDOMAIN is definitive and not
  retried), a client-side rate limit, and a short-lived cache. Resolver, clock, and sleep are
  injected, so it's unit-tested with no network (`tests/test_verify.py`).
- **Tenant isolation** — `db/repository.py`: every query is scoped to a tenant in one place.
  `tests/test_api.py::test_tenant_isolation` proves one tenant can't read or fetch another's
  data.
- **Auth** — API keys are random, prefixed, and stored only as a SHA-256 hash; the plaintext
  is shown once and never persisted (`auth.py`).
- **Delivery** — the same verified data is served three ways: REST, MCP (`mcp/server.py`),
  and a partitioned Parquet export (`export.py`).
- **Observability** — structured JSON logs with a request id bound through each request, and
  optional, env-gated Sentry (`observability.py`).

## Security & privacy posture

- Synthetic data only; no real PII or customer data, in the tree or in git history.
- API keys hashed at rest; secrets read from the environment / a gitignored `.env`.
- All SQL is parameterized (SQLAlchemy); no string-built queries.
- Sentry is **off** unless a DSN is set, so error payloads don't leave the box by default.
- 404 (not 403) for another tenant's record, so the API doesn't reveal that it exists.

## Repository map

```
src/contact_verifier/
  app.py            FastAPI application factory
  config.py         settings (env-driven)
  auth.py           API-key auth -> tenant
  observability.py  request tracing + optional Sentry
  verify/           email syntax + DNS/MX deliverability + the status/confidence engine
  db/               models, engine/session, the tenant-scoped repository
  api/              routes + schemas + injectable dependencies
  services.py       the verify-and-dedup use case
  export.py         Parquet/CSV warehouse export
  mcp/server.py     the MCP delivery server
  cli.py            provision / seed / verify / export / serve
alembic/            migrations (Postgres)
tests/              30 tests (verification, API, tenancy, dedup, export, MCP)
```

## Tests

```bash
pytest          # 30 tests, no network (the DNS resolver is injected/faked)
ruff check src tests
```

## License

[Apache License 2.0](LICENSE).
