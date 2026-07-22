# contact-verifier

<!-- sourcebound:purpose -->
contact-verifier is a local, multi-tenant contact-assessment service for teams that need explainable email syntax and domain mail-routing evidence without turning those signals into mailbox or identity claims. It stores each result under one tenant and serves the same record through REST, stdio MCP tools, and local Parquet or CSV exports.
<!-- sourcebound:end purpose -->

All committed fixtures use synthetic contacts. Local operator data stays outside version control.
Verification means syntax plus DNS evidence. It does not prove that a mailbox exists, accepts mail,
belongs to a person, or may be contacted. An MX record is a clue, not a person.

## What each result means

Stored contacts begin as `unknown`, which means not yet assessed. The verifier then assigns one of
three compatibility wire values and keeps the underlying routing state alongside it:

| Status | Evidence represented | `heuristic_score` |
| --- | --- | ---: |
| `valid` | Syntax passed and DNS exposed explicit MX or an implicit A/AAAA mail route. | `0.9` |
| `invalid` | Syntax failed, the domain did not exist, the domain published null MX, or no MX/A/AAAA route existed. | `0.0` or `0.1` |
| `risky` | Syntax passed, but bounded DNS retries ended in a transient failure. | `0.5` |
| `unknown` | The stored contact has not been assessed yet. | `0.0` |

These scores are ordinal rule constants, not calibrated probabilities. The API field is named
`heuristic_score`; `mail_routing_state` preserves the narrower DNS outcome.

## How a contact moves through the service

1. REST or the CLI ingests contacts for the tenant resolved from an API key.
2. The verifier normalizes each address, checks syntax, and classifies domain routing evidence.
3. The service stores the result under the same tenant and flags later duplicate addresses.
4. REST, stdio MCP tools, and tenant-partitioned local exports read that stored record.

The DNS client retries only transient failures. It returns definitive answers such as `nxdomain`
and `null_mx` immediately, paces bulk calls, and bounds its cache. Tests inject the resolver, clock,
and sleep function, so the retry, rate-limit, and cache paths run without network access or waiting.

## Run the local flow

Install the application and its development and MCP extras, then run the hermetic checks:

```bash
pip install -e ".[dev,mcp]"
pytest
ruff check src tests
```

Provision a tenant and carry its one-time API key through the CLI flow:

```bash
KEY=$(contact-verifier provision --name "Acme" | awk '/API key/{print $NF}')
contact-verifier seed --key "$KEY"
contact-verifier verify --key "$KEY"
contact-verifier export --key "$KEY"
```

The verify command performs live DNS queries. The export command writes a local object under
`warehouse/tenant=<id>/`; it does not upload to a remote warehouse.

To use the HTTP interface, start the service and send the same tenant key with each request:

```bash
contact-verifier serve

curl -s -X POST localhost:8000/v1/contacts \
  -H "X-API-Key: $KEY" \
  -H 'content-type: application/json' \
  -d '{"contacts":[{"email":"jane@example.com"},{"email":"bad-syntax"}]}'
curl -s -X POST localhost:8000/v1/contacts/verify -H "X-API-Key: $KEY"
curl -s "localhost:8000/v1/contacts?status=valid" -H "X-API-Key: $KEY"
```

OpenAPI is available at `http://127.0.0.1:8000/docs`. SQLite is the default. To use Postgres,
install the `postgres` extra, set `CV_DATABASE_URL`, and run `alembic upgrade head`.

To expose the stored records to an MCP client, start the stdio server:

```bash
contact-verifier-mcp
```

The server registers `search_contacts`, `get_contact`, `contact_stats`, and `verify_contacts`.
Each tool accepts an API key because stdio MCP calls do not carry the REST header.

## Tenant and side-effect boundaries

Every repository method that reads or writes a contact requires a tenant ID. REST and MCP resolve
the tenant from the supplied API key before calling that layer. Negative tests prove that a second
tenant can neither list nor fetch another tenant's contact. REST returns 404 for a cross-tenant ID,
so it does not confirm that the record exists.

Only `verify_contacts` changes state through MCP, and repeated calls skip contacts that already have
an assessment. API keys are stored as SHA-256 hashes; plaintext appears once at creation. Sentry is
off unless a DSN is configured. Verification itself is the only external call in the assessment
path.

Read [Architecture](ARCHITECTURE.md) for the data path, DNS failure model, storage boundary, and
declared limits.

## License

[Apache License 2.0](LICENSE).
