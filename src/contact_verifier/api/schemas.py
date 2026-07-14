"""Request/response models. Pydantic does the input validation at the edge."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from contact_verifier.db.models import EmailStatus


class ContactIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    full_name: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    source: str = Field(default="api", max_length=100)


class IngestRequest(BaseModel):
    contacts: list[ContactIn] = Field(min_length=1, max_length=1000)


class IngestResponse(BaseModel):
    created: int
    ids: list[str]


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str | None
    company: str | None
    domain: str | None
    status: EmailStatus
    heuristic_score: float
    mail_routing_state: str | None
    duplicate_of_id: str | None
    verified_at: datetime | None
    created_at: datetime


class ContactsPage(BaseModel):
    items: list[ContactOut]
    total: int
    limit: int
    offset: int


class VerifyResponse(BaseModel):
    run_id: str
    n_contacts: int
    n_verified: int
    n_duplicates: int


class StatsResponse(BaseModel):
    total: int
    by_status: dict[str, int]


class ExportResponse(BaseModel):
    # The warehouse object key (relative to the stage), e.g.
    # "tenant=<id>/contacts-<ts>.parquet" — not the server's filesystem path.
    object_key: str
    n_rows: int
    format: str
