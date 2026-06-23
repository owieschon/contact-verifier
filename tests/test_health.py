from fastapi.testclient import TestClient

from contact_verifier.app import create_app


def test_healthz_and_request_id_header():
    client = TestClient(create_app())
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    # the tracing middleware echoes a request id on every response
    assert r.headers.get("x-request-id")
