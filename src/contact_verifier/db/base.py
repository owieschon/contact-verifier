"""Database engine and session wiring.

Backend-agnostic: the same models and queries run on SQLite (the zero-setup
default) or Postgres (set DATABASE_URL). The session is provided to request
handlers via a FastAPI dependency so every handler gets a scoped session that is
always closed.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from contact_verifier.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _make_engine():
    url = get_settings().database_url
    # SQLite needs this to be usable across the threadpool FastAPI runs handlers on.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables. (Alembic owns migrations; this is for tests and the demo.)"""
    from contact_verifier.db import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: a request-scoped session, always closed."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
