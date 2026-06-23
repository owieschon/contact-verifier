def _auth(key):
    return {"X-API-Key": key}


def test_auth_is_required(client):
    assert client.get("/v1/contacts").status_code == 401
    assert client.get("/v1/contacts", headers=_auth("cv_wrong")).status_code == 401


def test_ingest_verify_list_flow(client, provision):
    key = provision()
    ingest = client.post(
        "/v1/contacts",
        headers=_auth(key),
        json={"contacts": [
            {"email": "jane@good.com", "full_name": "Jane"},
            {"email": "bad-syntax", "company": "Oops"},
            {"email": "ghost@nope.invalid"},
        ]},
    )
    assert ingest.status_code == 201
    assert ingest.json()["created"] == 3

    verify = client.post("/v1/contacts/verify", headers=_auth(key))
    assert verify.status_code == 200
    assert verify.json()["n_verified"] == 3

    rows = client.get("/v1/contacts", headers=_auth(key)).json()
    by_email = {c["email"]: c for c in rows["items"]}
    assert by_email["jane@good.com"]["status"] == "valid"
    assert by_email["bad-syntax"]["status"] == "invalid"
    assert by_email["ghost@nope.invalid"]["status"] == "invalid"

    stats = client.get("/v1/stats", headers=_auth(key)).json()
    assert stats["total"] == 3
    assert stats["by_status"]["valid"] == 1
    assert stats["by_status"]["invalid"] == 2


def test_status_filter(client, provision):
    key = provision()
    client.post("/v1/contacts", headers=_auth(key), json={"contacts": [
        {"email": "a@good.com"}, {"email": "b@nope.invalid"},
    ]})
    client.post("/v1/contacts/verify", headers=_auth(key))
    valid = client.get("/v1/contacts?status=valid", headers=_auth(key)).json()
    assert valid["total"] == 1 and valid["items"][0]["email"] == "a@good.com"


def test_dedup_flags_later_duplicate(client, provision):
    key = provision()
    client.post("/v1/contacts", headers=_auth(key), json={"contacts": [
        {"email": "dup@good.com"}, {"email": "DUP@good.com"},
    ]})
    client.post("/v1/contacts/verify", headers=_auth(key))
    items = client.get("/v1/contacts", headers=_auth(key)).json()["items"]
    flagged = [c for c in items if c["duplicate_of_id"]]
    assert len(flagged) == 1, "the second (normalized-equal) contact is the duplicate"


def test_tenant_isolation(client, provision):
    key_a, key_b = provision("TenantA"), provision("TenantB")
    created = client.post(
        "/v1/contacts", headers=_auth(key_a),
        json={"contacts": [{"email": "secret@good.com"}]},
    ).json()
    a_id = created["ids"][0]

    # Tenant B sees none of A's data and cannot fetch A's contact by id.
    assert client.get("/v1/contacts", headers=_auth(key_b)).json()["total"] == 0
    assert client.get(f"/v1/contacts/{a_id}", headers=_auth(key_b)).status_code == 404
    # Tenant A still can.
    assert client.get(f"/v1/contacts/{a_id}", headers=_auth(key_a)).status_code == 200


def test_pagination(client, provision):
    key = provision()
    client.post("/v1/contacts", headers=_auth(key), json={"contacts": [
        {"email": f"user{i}@good.com"} for i in range(5)
    ]})
    page = client.get("/v1/contacts?limit=2&offset=0", headers=_auth(key)).json()
    assert page["total"] == 5 and len(page["items"]) == 2
    page2 = client.get("/v1/contacts?limit=2&offset=4", headers=_auth(key)).json()
    assert len(page2["items"]) == 1
