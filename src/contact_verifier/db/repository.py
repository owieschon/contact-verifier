"""Data access. Every query is scoped to a tenant.

Tenant isolation is enforced here, in one place: there is no method that reads or
writes a contact without a `tenant_id` in the WHERE clause. Handlers get their
tenant from the API key and pass it down; they cannot reach across tenants because
the repository never lets them. All SQL is parameterized by SQLAlchemy.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contact_verifier.auth import generate_key, hash_key
from contact_verifier.db.models import ApiKey, Contact, EmailStatus, Tenant
from contact_verifier.verify.email import normalize


def create_tenant(session: Session, name: str) -> Tenant:
    tenant = Tenant(name=name)
    session.add(tenant)
    session.flush()
    return tenant


def create_api_key(session: Session, tenant_id: str, label: str = "default") -> tuple[ApiKey, str]:
    """Returns the row and the one-time plaintext key (never stored)."""
    plaintext = generate_key()
    key = ApiKey(tenant_id=tenant_id, key_hash=hash_key(plaintext), label=label)
    session.add(key)
    session.flush()
    return key, plaintext


def add_contact(
    session: Session,
    tenant_id: str,
    *,
    email: str,
    full_name: str | None = None,
    company: str | None = None,
    source: str = "api",
) -> Contact:
    contact = Contact(
        tenant_id=tenant_id,
        email=email,
        normalized_email=normalize(email),
        full_name=full_name,
        company=company,
        source=source,
    )
    session.add(contact)
    session.flush()
    return contact


def canonical_contact(
    session: Session, tenant_id: str, normalized_email: str
) -> Contact | None:
    """The canonical (earliest) contact in this tenant for an email. A later
    contact with the same normalized email is a duplicate of this one."""
    return session.scalar(
        select(Contact)
        .where(
            Contact.tenant_id == tenant_id,
            Contact.normalized_email == normalized_email,
        )
        .order_by(Contact.created_at.asc(), Contact.id.asc())
        .limit(1)
    )


def get_contact(session: Session, tenant_id: str, contact_id: str) -> Contact | None:
    return session.scalar(
        select(Contact).where(Contact.tenant_id == tenant_id, Contact.id == contact_id)
    )


def list_contacts(
    session: Session,
    tenant_id: str,
    *,
    status: EmailStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Contact], int]:
    """A page of contacts plus the total count, for pagination."""
    where = [Contact.tenant_id == tenant_id]
    if status is not None:
        where.append(Contact.status == status)

    total = session.scalar(select(func.count()).select_from(Contact).where(*where)) or 0
    rows = list(
        session.scalars(
            select(Contact)
            .where(*where)
            .order_by(Contact.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, total


def unverified_contacts(session: Session, tenant_id: str) -> list[Contact]:
    return list(
        session.scalars(
            select(Contact).where(
                Contact.tenant_id == tenant_id,
                Contact.status == EmailStatus.UNKNOWN,
            )
        )
    )


def status_counts(session: Session, tenant_id: str) -> dict[str, int]:
    rows = session.execute(
        select(Contact.status, func.count())
        .where(Contact.tenant_id == tenant_id)
        .group_by(Contact.status)
    ).all()
    counts = {s.value: 0 for s in EmailStatus}
    for status_value, n in rows:
        counts[status_value.value if hasattr(status_value, "value") else status_value] = n
    return counts
