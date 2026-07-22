"""Pin tenant isolation at the MCP tool boundary."""

from contact_verifier.db import repository as repo
from contact_verifier.mcp import server


def test_mcp_key_cannot_list_or_fetch_another_tenants_contact(
    session_factory,
    monkeypatch,
):
    monkeypatch.setattr(server, "SessionLocal", session_factory)
    with session_factory() as session:
        tenant_a = repo.create_tenant(session, "Acorn")
        _stored_a, key_a = repo.create_api_key(session, tenant_a.id)
        tenant_b = repo.create_tenant(session, "Birch")
        _stored_b, key_b = repo.create_api_key(session, tenant_b.id)
        contact = repo.add_contact(session, tenant_a.id, email="owner@acorn.example")
        contact_id = contact.id
        session.commit()

    assert [row["id"] for row in server.search_contacts(key_a)] == [contact_id]
    assert server.get_contact(key_a, contact_id)["email"] == "owner@acorn.example"
    assert server.search_contacts(key_b) == []
    assert server.get_contact(key_b, contact_id) is None
