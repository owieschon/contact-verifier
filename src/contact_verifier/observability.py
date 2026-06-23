"""Request tracing and error reporting.

Every request gets a request id that is bound into the structured logs (so a
whole request is greppable by one id and returned to the caller in a header).
Sentry is wired but stays off unless CV_SENTRY_DSN is set — this service holds
contact data, so error payloads should not leave the box by default.
"""

from __future__ import annotations

import time
import uuid

import structlog
from fastapi import FastAPI, Request

from contact_verifier.config import Settings
from contact_verifier.logging import get_logger

log = get_logger()


def init_sentry(settings: Settings) -> None:
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk
    except ImportError:  # optional dependency
        log.warning("sentry_dsn set but sentry-sdk not installed; skipping")
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        # Don't ship request bodies / PII to the error backend by default.
        send_default_pii=False,
    )
    log.info("sentry_enabled", environment=settings.environment)


def install_request_tracing(app: FastAPI) -> None:
    @app.middleware("http")
    async def _trace(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            log.info(
                "request",
                method=request.method,
                path=request.url.path,
                elapsed_ms=elapsed_ms,
            )
            structlog.contextvars.clear_contextvars()
        response.headers["x-request-id"] = request_id
        return response
