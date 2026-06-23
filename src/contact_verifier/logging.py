"""Structured logging. JSON in production, human-readable in a dev terminal.

Each log line within a request carries the bound request id (set by the tracing
middleware), so a single request can be traced end-to-end and a failure diagnosed
after the fact without spelunking through unstructured text.
"""

from __future__ import annotations

import logging

import structlog

from contact_verifier.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(format="%(message)s", level=settings.log_level)

    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "contact_verifier") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
