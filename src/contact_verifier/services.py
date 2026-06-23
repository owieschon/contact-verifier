"""Application services: the use-cases handlers call.

Thin orchestration over the repository and the verifier. Kept separate from HTTP
so it can be driven from the API, the CLI, or a test with the same code.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from contact_verifier.db import repository as repo
from contact_verifier.db.models import VerificationRun
from contact_verifier.logging import get_logger
from contact_verifier.verify.engine import Verifier

log = get_logger()


def verify_tenant_contacts(
    session: Session, tenant_id: str, verifier: Verifier | None = None
) -> VerificationRun:
    """Verify every not-yet-verified contact for one tenant, flag duplicates, and
    record the run. Idempotent: already-verified contacts are skipped."""
    verifier = verifier or Verifier()
    run = VerificationRun(tenant_id=tenant_id)
    session.add(run)
    session.flush()

    pending = repo.unverified_contacts(session, tenant_id)
    n_verified = n_duplicates = 0
    for contact in pending:
        result = verifier.verify(contact.email)
        contact.normalized_email = result.normalized_email
        contact.domain = result.domain
        contact.email_syntax_ok = result.syntax_ok
        contact.domain_has_mx = result.domain_has_mx
        contact.status = result.status
        contact.confidence = result.confidence
        contact.verified_at = datetime.now(UTC)
        n_verified += 1

        canonical = repo.canonical_contact(session, tenant_id, contact.normalized_email)
        if canonical is not None and canonical.id != contact.id:
            # An earlier contact owns this email; this one is the duplicate.
            contact.duplicate_of_id = canonical.id
            n_duplicates += 1

    run.n_contacts = len(pending)
    run.n_verified = n_verified
    run.n_duplicates = n_duplicates
    run.finished_at = datetime.now(UTC)
    run.status = "done"
    session.commit()
    log.info(
        "verification_run",
        tenant_id=tenant_id,
        n_contacts=run.n_contacts,
        n_verified=n_verified,
        n_duplicates=n_duplicates,
    )
    return run
