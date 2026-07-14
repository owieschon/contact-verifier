import pyarrow.parquet as pq

from contact_verifier import config
from contact_verifier.db import repository as repo
from contact_verifier.export import export_tenant_contacts


def _seed(session_factory, name, emails):
    with session_factory() as s:
        tenant = repo.create_tenant(s, name)
        for e in emails:
            repo.add_contact(s, tenant.id, email=e)
        s.commit()
        return tenant.id


def test_parquet_export_is_partitioned_and_tenant_scoped(session_factory, tmp_path):
    a = _seed(session_factory, "A", ["x@a.com", "y@a.com"])
    b = _seed(session_factory, "B", ["z@b.com"])

    with session_factory() as s:
        result = export_tenant_contacts(s, a, str(tmp_path), fmt="parquet")

    assert result.n_rows == 2
    assert f"tenant={a}" in result.path and result.path.endswith(".parquet")
    table = pq.read_table(result.path)
    assert table.num_rows == 2
    assert set(table.column_names) >= {
        "email", "status", "heuristic_score", "mail_routing_state", "domain"
    }

    # B's data is not in A's export.
    with session_factory() as s:
        b_result = export_tenant_contacts(s, b, str(tmp_path), fmt="parquet")
    assert b_result.n_rows == 1


def test_export_endpoint(client, provision, tmp_path, monkeypatch):
    monkeypatch.setattr(config.get_settings(), "warehouse_dir", str(tmp_path))
    key = provision()
    client.post("/v1/contacts", headers={"X-API-Key": key},
                json={"contacts": [{"email": "a@good.com"}]})
    r = client.post("/v1/export?format=csv", headers={"X-API-Key": key})
    assert r.status_code == 200
    body = r.json()
    assert body["n_rows"] == 1 and body["format"] == "csv"
    # the response is a warehouse object key, not the server filesystem path
    assert body["object_key"].startswith("tenant=")
    assert str(tmp_path) not in body["object_key"]
