"""FastAPI application factory.

Wires logging, request-id tracing, optional Sentry, and the routers. Kept thin:
business logic lives in the service/repository layers, not in handlers.
"""

from __future__ import annotations

from fastapi import FastAPI

from contact_verifier import observability
from contact_verifier.config import get_settings
from contact_verifier.db.base import init_db
from contact_verifier.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    observability.init_sentry(settings)

    app = FastAPI(
        title="contact-verifier",
        version="0.1.0",
        summary="Ingest, verify, and serve B2B contact data (synthetic data only).",
    )
    observability.install_request_tracing(app)

    # Tables are created here for the SQLite demo; Postgres uses Alembic migrations.
    if settings.database_url.startswith("sqlite"):
        init_db()

    from contact_verifier.api.routes import router

    app.include_router(router)

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
