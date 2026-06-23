"""Test harness: an isolated in-memory database and a fake DNS resolver.

The app's session and verifier are swapped via FastAPI dependency_overrides, so
tests run against a throwaway SQLite database with no network and no shared state
between tests.
"""

import dns.resolver
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from contact_verifier.api.deps import get_verifier
from contact_verifier.db import repository as repo
from contact_verifier.db.base import Base, get_session
from contact_verifier.verify.dns import MxChecker
from contact_verifier.verify.engine import Verifier

# Domains the fake resolver treats as undeliverable; everything else has MX.
_NO_MX_DOMAINS = {"nope.invalid", "ghost.example"}


def _fake_resolve(domain: str):
    if domain in _NO_MX_DOMAINS:
        raise dns.resolver.NXDOMAIN()
    return ["mx1." + domain]


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def client(session_factory, monkeypatch):
    # Never let create_app touch a real on-disk database.
    monkeypatch.setattr("contact_verifier.db.base.init_db", lambda: None)
    from contact_verifier.app import create_app

    app = create_app()

    def override_session():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_verifier] = lambda: Verifier(
        MxChecker(resolve_fn=_fake_resolve, rate_limit_per_s=0)
    )
    return TestClient(app)


@pytest.fixture
def provision(session_factory):
    """Create a tenant + API key; returns the plaintext key."""
    def _provision(name: str = "Acme") -> str:
        with session_factory() as s:
            tenant = repo.create_tenant(s, name)
            _key, plaintext = repo.create_api_key(s, tenant.id)
            s.commit()
            return plaintext

    return _provision
