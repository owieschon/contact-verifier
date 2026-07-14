"""ORM models.

Every business row hangs off a `tenant_id`. Isolation is enforced in the
repository layer (every query filters by tenant), and the schema makes the tenant
boundary explicit with indexes and foreign keys.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from contact_verifier.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class EmailStatus(enum.StrEnum):
    UNKNOWN = "unknown"      # not yet verified
    VALID = "valid"          # syntax ok and domain has mail exchangers
    INVALID = "invalid"      # bad syntax, or domain cannot receive mail
    RISKY = "risky"          # syntax valid but routing evidence is transient


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="tenant")


class ApiKey(Base):
    """An API key, stored only as a SHA-256 hash. The plaintext is shown once at
    creation and never persisted."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    label: Mapped[str] = mapped_column(String(100), default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates="api_keys")


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        # The hot path: list/search a tenant's contacts, and dedup within a tenant.
        Index("ix_contacts_tenant_created", "tenant_id", "created_at"),
        Index("ix_contacts_tenant_norm_email", "tenant_id", "normalized_email"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(100), default="api")

    # As ingested.
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Derived / verified.
    normalized_email: Mapped[str] = mapped_column(String(320), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_syntax_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mail_routing_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[EmailStatus] = mapped_column(
        Enum(EmailStatus, native_enum=False,
             values_callable=lambda e: [m.value for m in e]),
        default=EmailStatus.UNKNOWN,
    )
    heuristic_score: Mapped[float] = mapped_column(Float, default=0.0)
    duplicate_of_id: Mapped[str | None] = mapped_column(
        ForeignKey("contacts.id"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class VerificationRun(Base):
    __tablename__ = "verification_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    n_contacts: Mapped[int] = mapped_column(Integer, default=0)
    n_verified: Mapped[int] = mapped_column(Integer, default=0)
    n_duplicates: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="running")
