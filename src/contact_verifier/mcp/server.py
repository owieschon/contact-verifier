"""Serve the same syntax and DNS assessment through tenant-scoped MCP tools.

Exposes read-mostly, tenant-scoped tools over stdio so an AI agent (or any MCP
client) can search and fetch assessed contacts. The tools take an `api_key`
because this stdio transport does not carry the REST authentication header; the
key resolves to a tenant exactly as the REST auth does, so an agent can only ever
see one tenant's data. Verification is the only state-changing tool, and it is
idempotent.

The status values classify syntax and DNS evidence. ``heuristic_score`` is an
ordinal rule score, not mailbox-existence or delivery probability.
"""

from __future__ import annotations

from sqlalchemy import select

from contact_verifier.auth import hash_key
from contact_verifier.db import repository as repo
from contact_verifier.db.base import SessionLocal, init_db
from contact_verifier.db.models import ApiKey, EmailStatus
from contact_verifier.services import verify_tenant_contacts


class AuthError(ValueError):
    """The api_key did not resolve to a tenant."""


def _tenant_id(session, api_key: str) -> str:
    row = session.scalar(
        select(ApiKey).where(ApiKey.key_hash == hash_key(api_key), ApiKey.revoked_at.is_(None))
    )
    if row is None:
        raise AuthError("invalid or revoked api_key")
    return row.tenant_id


def _contact_dict(c) -> dict:
    return {
        "id": c.id, "email": c.email, "full_name": c.full_name, "company": c.company,
        "domain": c.domain, "status": c.status.value,
        "heuristic_score": c.heuristic_score,
        "mail_routing_state": c.mail_routing_state,
        "duplicate_of_id": c.duplicate_of_id,
    }


def search_contacts(api_key: str, status: str | None = None, limit: int = 25) -> list[dict]:
    """Search a tenant's contacts, optionally filtered by status
    (valid/invalid/risky/unknown). These are syntax/DNS rule outcomes, not
    mailbox-validity claims. Returns up to `limit` rows."""
    status_enum = EmailStatus(status) if status else None
    with SessionLocal() as s:
        tenant_id = _tenant_id(s, api_key)
        rows, _ = repo.list_contacts(s, tenant_id, status=status_enum, limit=min(limit, 200))
        return [_contact_dict(c) for c in rows]


def get_contact(api_key: str, contact_id: str) -> dict | None:
    """Fetch one contact by id (only within the caller's tenant)."""
    with SessionLocal() as s:
        tenant_id = _tenant_id(s, api_key)
        c = repo.get_contact(s, tenant_id, contact_id)
        return _contact_dict(c) if c else None


def contact_stats(api_key: str) -> dict:
    """Counts of a tenant's contacts by verification status."""
    with SessionLocal() as s:
        tenant_id = _tenant_id(s, api_key)
        return repo.status_counts(s, tenant_id)


def verify_contacts(api_key: str) -> dict:
    """Verify a tenant's not-yet-verified contacts (idempotent). Returns a summary."""
    with SessionLocal() as s:
        tenant_id = _tenant_id(s, api_key)
        run = verify_tenant_contacts(s, tenant_id)
        return {"n_verified": run.n_verified, "n_duplicates": run.n_duplicates}


def build_server():
    """Construct the FastMCP server with the tools registered. Imported lazily so
    the package does not hard-depend on `mcp` unless the server is run."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("contact-verifier")
    for fn in (search_contacts, get_contact, contact_stats, verify_contacts):
        server.tool()(fn)
    return server


def main() -> None:
    init_db()
    build_server().run()


if __name__ == "__main__":
    main()
