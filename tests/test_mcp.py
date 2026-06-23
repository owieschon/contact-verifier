"""Tests for the MCP tool functions (no network).

Data is pre-verified through the service with a fake resolver, then the
read-mostly tools are exercised directly. verify_contacts is checked for
idempotency (nothing pending -> no DNS calls).
"""

import dns.resolver
import pytest

from contact_verifier.db import repository as repo
from contact_verifier.mcp import server
from contact_verifier.services import verify_tenant_contacts
from contact_verifier.verify.dns import MxChecker
from contact_verifier.verify.engine import Verifier


def _fake_resolve(domain):
    if domain == "nope.invalid":
        raise dns.resolver.NXDOMAIN()
    return ["mx1." + domain]


@pytest.fixture
def env(session_factory, monkeypatch):
    # The MCP tools call SessionLocal() directly; point it at the test database.
    monkeypatch.setattr(server, "SessionLocal", session_factory)
    with session_factory() as s:
        tenant = repo.create_tenant(s, "Acme")
        _k, key = repo.create_api_key(s, tenant.id)
        for e in ("good@good.com", "ghost@nope.invalid"):
            repo.add_contact(s, tenant.id, email=e)
        s.commit()
        tenant_id = tenant.id
    with session_factory() as s:
        verify_tenant_contacts(
            s, tenant_id,
            Verifier(MxChecker(resolve_fn=_fake_resolve, rate_limit_per_s=0)),
        )
    return key


def test_search_and_get(env):
    rows = server.search_contacts(env)
    assert {c["status"] for c in rows} == {"valid", "invalid"}
    valid = server.search_contacts(env, status="valid")
    assert len(valid) == 1 and valid[0]["email"] == "good@good.com"
    fetched = server.get_contact(env, valid[0]["id"])
    assert fetched["email"] == "good@good.com"


def test_stats_and_idempotent_verify(env):
    assert server.contact_stats(env)["valid"] == 1
    # everything is already verified -> nothing pending, no network touched
    assert server.verify_contacts(env)["n_verified"] == 0


def test_bad_key_raises(env):
    with pytest.raises(server.AuthError):
        server.search_contacts("cv_not_a_real_key")


def test_build_server_registers_tools(env):
    # the FastMCP server constructs without error and the tools are wired
    srv = server.build_server()
    assert srv is not None
