"""Injectable dependencies and their `Annotated` aliases.

The aliases keep route signatures readable and use FastAPI's recommended
`Annotated[...]` style (so the network-touching pieces can be overridden in tests
via dependency_overrides)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from contact_verifier.auth import require_tenant
from contact_verifier.config import get_settings
from contact_verifier.db.base import get_session
from contact_verifier.db.models import Tenant
from contact_verifier.verify.dns import MxChecker
from contact_verifier.verify.engine import Verifier


def get_verifier() -> Verifier:
    s = get_settings()
    return Verifier(
        MxChecker(
            timeout_s=s.dns_timeout_s,
            max_retries=s.dns_max_retries,
            rate_limit_per_s=s.dns_rate_limit_per_s,
            cache_ttl_s=s.verify_cache_ttl_s,
        )
    )


SessionDep = Annotated[Session, Depends(get_session)]
TenantDep = Annotated[Tenant, Depends(require_tenant)]
VerifierDep = Annotated[Verifier, Depends(get_verifier)]
