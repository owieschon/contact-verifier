# contact-verifier

<!-- clean-docs:purpose -->
**contact-verifier ingests B2B contact records, checks email syntax and whether each domain publishes a usable mail-routing path, and serves the results three ways** — a REST API, an [MCP](https://modelcontextprotocol.io) server for agents, and a Parquet warehouse export. It does not prove that a mailbox exists or will accept a message. It's multi-tenant: many customers' contacts live in one store, and the thing it can't get wrong is letting one tenant see another's data.
<!-- clean-docs:end purpose -->


> Portfolio prototype on synthetic data only — the 15 seed contacts and any tenant you create are made up; no real PII in the tree or git history. "Verification" here means **email syntax + DNS mail-routing evidence**, not mailbox validation or live SMTP probing. Defaults to SQLite so it runs end-to-end from a clean clone; point it at Postgres when you want to.

## What "verified" means

Two checks, in order, turned into one status and a one-sentence reason a customer can actually read:

1. **Syntax** (`verify/email.py`) — a pragmatic, network-free parse (one `@`, sane local part, dotted domain with a real TLD) that also lowercases/trims to a `normalized_email` so dedup works. Stricter than RFC 5322 on purpose; it catches the malformed addresses real lists actually contain.
2. **Routing evidence** (`verify/dns.py`) — classify explicit MX, implicit MX through A/AAAA, null MX, nonexistent domains, missing address records, and transient DNS failure.

The engine (`verify/engine.py`) collapses those into four statuses:

| status | meaning | heuristic score |
|---|---|---|
| `valid` | syntax ok and DNS exposes an explicit or implicit mail route | 0.9 |
| `invalid` | bad syntax, null MX, NXDOMAIN, or no MX/A/AAAA route | 0.0 or 0.1 |
| `risky` | syntax ok, but a temporary DNS failure prevented classification | 0.5 |

These values are ordinal rule constants named `heuristic_score`; they are not calibrated probabilities.
| `unknown` | not yet verified | — |

The load-bearing distinction is between *definitive* and *unconfirmed*. **NXDOMAIN** — the domain provably does not exist — is a real, cached negative, returned immediately; retrying a definitive answer just burns time. But a **timeout or SERVFAIL** is the resolver having a bad moment, not evidence the address is dead. After bounded retries (exponential backoff + jitter) it returns `unknown` → **`risky`**, never a false `invalid`. A DNS hiccup must not silently condemn a good contact, and that fail-closed branch is unit-tested (`tests/test_verify.py`) with an injected resolver, clock, and sleep — it fires in CI with no network and no waiting.

`verify/dns.py` is where the integration craft lives, since the flaky external call is what breaks in production: per-attempt timeout, retry only on transient failures, a client-side rate limit so a bulk run paces itself, and a bounded LRU+TTL cache (the same domains recur all over a contact list).

## Tenant isolation, in one place

Every business row hangs off a `tenant_id`, and **the repository (`db/repository.py`) is the only layer that touches contacts** — by construction it has no method that reads or writes one without a `tenant_id` in the `WHERE` clause. Handlers resolve their tenant from the API key (`auth.py`; keys stored as SHA-256 hashes, plaintext shown once) and pass it down; they can't reach past it because the repository never offers a way to. A cross-tenant fetch returns **404, not 403** (`api/routes.py`), so the API won't even confirm another tenant's record exists — asserted in `tests/test_api.py::test_tenant_isolation`. One enforcement point is the design: isolation you have to remember in every handler is isolation you'll eventually forget.

## The flow

```
  REST / CLI ──ingest──▶ verify (syntax → routing state → status+score) ──▶ store ──┐
                                                                              │
                                                       SQLite / Postgres,     │
                                                       tenant-scoped repo  ◀──┘
                                                              │
                              ┌───────────────────────────────┼──────────────────────┐
                              ▼                                ▼                        ▼
                       REST (FastAPI /v1)              MCP server (stdio)        Parquet export
                                                       4 agent tools          warehouse/tenant=<id>/
```

Verification runs inline and is **idempotent** — already-verified contacts are skipped — and the same run flags duplicates (a later contact sharing a `normalized_email` points at the earliest via `duplicate_of_id`). Each run is recorded in `verification_runs`.

**Three serving surfaces, one stored truth:**

- **REST** (`api/routes.py`, prefix `/v1`): `POST /contacts`, `POST /contacts/verify`, `GET /contacts` (paginated, status filter), `GET /contacts/{id}`, `GET /stats`, `POST /export`. Every route requires an `X-API-Key`. OpenAPI at `/docs`.
- **MCP** (`mcp/server.py`): four tools — `search_contacts`, `get_contact`, `contact_stats`, `verify_contacts` — over stdio for AI agents. The tools take an `api_key` (MCP has no headers) that resolves to a tenant exactly as REST auth does, so an agent only ever sees one tenant. Only `verify_contacts` mutates, and it's idempotent.
- **Parquet export** (`export.py`): writes a tenant's contacts to `warehouse/tenant=<id>/contacts-<timestamp>.parquet` — the partitioned, columnar shape a data lake or external stage expects (CSV offered for quick inspection). Rows stream in batches so memory stays flat for large tenants.

## Run it (~2 minutes)

```bash
pip install -e ".[dev,mcp]"     # or: make install
make test                       # 31 tests, no DB, no network, no keys

## Drive the whole flow from the CLI (SQLite, real DNS):
contact-verifier provision --name "Acme"     # prints a one-time API key (cv_...)
contact-verifier seed   --key cv_...          # load 15 synthetic contacts
contact-verifier verify --key cv_...          # syntax + live MX lookup
contact-verifier export --key cv_... --format parquet
contact-verifier serve                        # REST API on :8000
```

Or the same over HTTP once `serve` is up:

```bash
curl -s -X POST localhost:8000/v1/contacts/verify -H "X-API-Key: cv_..."
curl -s "localhost:8000/v1/contacts?status=risky"  -H "X-API-Key: cv_..."
```

The MCP server is `contact-verifier-mcp` (stdio). SQLite is the default; set `CV_DATABASE_URL` to a Postgres DSN and run `alembic upgrade head` (`make db-up` starts one in Docker) to use Postgres. All config is `CV_`-prefixed env vars with working defaults — see `.env.example`.

## Status

31 tests pass across 5 files on a Python 3.11 / 3.12 / 3.13 CI matrix (ruff + pytest + pip-audit). Synthetic data only; the Parquet export writes a warehouse *layout* to the local filesystem, not to a live S3/Snowflake stage. The DNS retry/backoff/cache design, the storage and migration model, and what's deliberately out of scope live in **[ARCHITECTURE.md](ARCHITECTURE.md)**.

## License

[Apache 2.0](LICENSE).
