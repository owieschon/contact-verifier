"""Runtime configuration, read from the environment (12-factor style).

Nothing here is secret in the repo; real values come from the environment or a
local `.env` that is gitignored. SQLite is the default so the service runs from a
clean clone with no external services; set DATABASE_URL to a Postgres DSN to use
Postgres instead.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CV_", env_file=".env", extra="ignore"
    )

    # Storage. SQLite by default; e.g. postgresql+psycopg://user:pass@host/db
    database_url: str = "sqlite:///./contact_verifier.db"

    # DNS/MX verification of the external dependency.
    dns_timeout_s: float = 3.0
    dns_max_retries: int = 3
    dns_rate_limit_per_s: float = 20.0
    verify_cache_ttl_s: int = 3600
    verify_cache_maxsize: int = 10_000

    # Delivery export (the warehouse / S3 stand-in).
    warehouse_dir: str = "./warehouse"

    # Observability. Sentry is off unless a DSN is provided.
    log_level: str = "INFO"
    log_json: bool = True
    sentry_dsn: str | None = None
    environment: str = "dev"


_settings: Settings | None = None


def get_settings() -> Settings:
    """Process-wide settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
