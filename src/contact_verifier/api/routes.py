"""HTTP routes. Thin handlers: validate, call a service/repository, shape output.

Every route depends on `require_tenant` (via TenantDep), so there is no
unauthenticated or cross-tenant path to contact data.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from contact_verifier import export as export_mod
from contact_verifier import services
from contact_verifier.api import schemas
from contact_verifier.api.deps import SessionDep, TenantDep, VerifierDep
from contact_verifier.config import get_settings
from contact_verifier.db import repository as repo
from contact_verifier.db.models import EmailStatus

router = APIRouter(prefix="/v1", tags=["contacts"])


@router.post(
    "/contacts",
    response_model=schemas.IngestResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_contacts(
    body: schemas.IngestRequest, tenant: TenantDep, session: SessionDep
) -> schemas.IngestResponse:
    ids = [
        repo.add_contact(
            session, tenant.id,
            email=c.email, full_name=c.full_name, company=c.company, source=c.source,
        ).id
        for c in body.contacts
    ]
    session.commit()
    return schemas.IngestResponse(created=len(ids), ids=ids)


@router.post("/contacts/verify", response_model=schemas.VerifyResponse)
def run_verification(
    tenant: TenantDep, session: SessionDep, verifier: VerifierDep
) -> schemas.VerifyResponse:
    run = services.verify_tenant_contacts(session, tenant.id, verifier)
    return schemas.VerifyResponse(
        run_id=run.id, n_contacts=run.n_contacts,
        n_verified=run.n_verified, n_duplicates=run.n_duplicates,
    )


@router.get("/contacts", response_model=schemas.ContactsPage)
def list_contacts(
    tenant: TenantDep,
    session: SessionDep,
    status_filter: Annotated[EmailStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> schemas.ContactsPage:
    rows, total = repo.list_contacts(
        session, tenant.id, status=status_filter, limit=limit, offset=offset
    )
    return schemas.ContactsPage(
        items=[schemas.ContactOut.model_validate(r) for r in rows],
        total=total, limit=limit, offset=offset,
    )


@router.get("/contacts/{contact_id}", response_model=schemas.ContactOut)
def get_contact(
    contact_id: str, tenant: TenantDep, session: SessionDep
) -> schemas.ContactOut:
    contact = repo.get_contact(session, tenant.id, contact_id)
    if contact is None:
        # Same 404 whether the id is unknown or belongs to another tenant —
        # don't leak the existence of other tenants' records.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="contact not found")
    return schemas.ContactOut.model_validate(contact)


@router.get("/stats", response_model=schemas.StatsResponse)
def stats(tenant: TenantDep, session: SessionDep) -> schemas.StatsResponse:
    counts = repo.status_counts(session, tenant.id)
    return schemas.StatsResponse(total=sum(counts.values()), by_status=counts)


@router.post("/export", response_model=schemas.ExportResponse)
def export_contacts(
    tenant: TenantDep,
    session: SessionDep,
    fmt: Annotated[str, Query(alias="format", pattern="^(parquet|csv)$")] = "parquet",
) -> schemas.ExportResponse:
    result = export_mod.export_tenant_contacts(
        session, tenant.id, get_settings().warehouse_dir, fmt=fmt
    )
    return schemas.ExportResponse(path=result.path, n_rows=result.n_rows, format=result.fmt)
