"""API-key authentication, resolving a request to its tenant.

Keys are random, prefixed, and stored only as a SHA-256 hash. The plaintext is
returned once at provisioning and never persisted, so a database leak does not
hand over working credentials.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from contact_verifier.db.base import get_session
from contact_verifier.db.models import ApiKey, Tenant

_KEY_PREFIX = "cv_"


def generate_key() -> str:
    return _KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def require_tenant(
    session: Annotated[Session, Depends(get_session)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Tenant:
    """FastAPI dependency: the authenticated tenant, or 401."""
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing X-API-Key header",
        )
    row = session.scalar(
        select(ApiKey).where(
            ApiKey.key_hash == hash_key(x_api_key),
            ApiKey.revoked_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or revoked API key",
        )
    return row.tenant
