# contact-verifier

Mark a dead email address `valid` and you don't just lose one message — you teach every mailbox provider that your domain sends to addresses that bounce. Sender reputation is the asset, and a confident-but-wrong verdict is what spends it.

So this service refuses to guess. When it checks an email's deliverability and the DNS lookup actually can't confirm the domain, it returns `risky` (confidence `0.5`) — never a false `valid` and never a false `invalid`. A flaky network call doesn't get to author the answer of record. That's the whole posture, and it's the same one I bring to every system I build that handles something I'd have to answer for: the model (or here, an external lookup) proposes at the edges; a deterministic, tested rule decides.

`risky`-on-uncertainty is unit-tested deterministically — the resolver, clock, and sleep are injected, so the fail-closed branch fires in CI with no network and no waiting. And the DNS client knows the difference between "I couldn't reach an answer" (retry, then fail closed) and "the domain does not exist" — `NXDOMAIN` is definitive, returned immediately, never retried.

## Run it

SQLite, no services. Python 3.11+.

```bash
pip install -e ".[dev,mcp]"

KEY=$(contact-verifier provision --name "Acme" | awk '/API key/{print $NF}')
contact-verifier seed   --key "$KEY"     # 15 synthetic sample contacts
contact-verifier verify --key "$KEY"     # real DNS: valid domains resolve, fakes don't
contact-verifier export --key "$KEY"     # -> warehouse/tenant=<id>/contacts-*.parquet
```

Or over HTTP — `contact-verifier serve`, then `POST /v1/contacts`, `POST /v1/contacts/verify`, `GET /v1/contacts?status=valid` (OpenAPI at `/docs`). Postgres instead of SQLite: set `CV_DATABASE_URL` and `alembic upgrade head`.

## What it is

A multi-tenant FastAPI service that ingests B2B contacts, verifies email deliverability (syntax → DNS/MX, no paid API), and serves the verified data three ways from one stored copy:

```
ingest ──▶ verify ──▶ store ──┬──▶ REST      (API-key auth, paginated)
 REST/CLI  syntax     per-     ├──▶ MCP       (4 tenant-scoped agent tools)
           DNS/MX     tenant   └──▶ warehouse (Parquet, tenant=<id>/ partitions)
```

Two invariants do the load-bearing work, and both are proven by a test rather than asserted in prose:

- **Tenant isolation lives in one place.** Every read and write in `db/repository.py` carries a `tenant_id`; handlers get their tenant from the API key and can't reach past it. A cross-tenant fetch returns `404`, not `403`, so the API won't even confirm another tenant's record exists (`tests/test_api.py::test_tenant_isolation`).
- **Fail-closed verification.** Transient DNS exhaustion → `risky`, never a false verdict (`tests/test_verify.py`).

API keys are random, `cv_`-prefixed, and stored only as a SHA-256 hash (plaintext shown once). Structured JSON logs carry a `request_id` end-to-end; Sentry is optional, env-gated, and `send_default_pii=False`.

## Status

Public, sanitized version of a real system — all sample data is synthetic, generated to protect real people's contact data. Runs end-to-end from a clean clone. **31 tests pass** across 5 files on a Python 3.11/3.12/3.13 CI matrix (ruff + pytest + pip-audit). The Parquet export writes a warehouse *layout* to the local filesystem, not to a live S3/Snowflake stage — see scope notes below.

The DNS retry/backoff/cache design, the storage and migration model, and what's deliberately out of scope are in **[ARCHITECTURE.md](ARCHITECTURE.md)**.

## License

[Apache 2.0](LICENSE).
