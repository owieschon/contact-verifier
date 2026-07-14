"""Delivery export — write a tenant's verified contacts to the warehouse.

This stands in for the "deliver verified data to the customer's warehouse" path
(Snowflake external stage / S3). Output is written under a partitioned layout,
`warehouse/tenant=<id>/contacts-<timestamp>.<ext>`, the same shape a data lake or
external stage expects. Parquet is the default (columnar, typed); CSV is offered
for quick inspection.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import select
from sqlalchemy.orm import Session

from contact_verifier.db.models import Contact
from contact_verifier.logging import get_logger

log = get_logger()

_COLUMNS = [
    "id", "email", "normalized_email", "full_name", "company", "domain",
    "status", "heuristic_score", "mail_routing_state", "duplicate_of_id",
    "verified_at", "created_at",
]


@dataclass(frozen=True)
class ExportResult:
    path: str
    n_rows: int
    fmt: str


def _rows(session: Session, tenant_id: str):
    """Stream a tenant's contacts. yield_per keeps memory flat for large tenants
    instead of materializing every row at once."""
    stmt = (
        select(Contact)
        .where(Contact.tenant_id == tenant_id)
        .order_by(Contact.created_at.asc())
        .execution_options(yield_per=500)
    )
    for contact in session.scalars(stmt):
        yield {
            "id": contact.id,
            "email": contact.email,
            "normalized_email": contact.normalized_email,
            "full_name": contact.full_name,
            "company": contact.company,
            "domain": contact.domain,
            "status": contact.status.value,
            "heuristic_score": contact.heuristic_score,
            "mail_routing_state": contact.mail_routing_state,
            "duplicate_of_id": contact.duplicate_of_id,
            "verified_at": contact.verified_at.isoformat() if contact.verified_at else None,
            "created_at": contact.created_at.isoformat(),
        }


def export_tenant_contacts(
    session: Session,
    tenant_id: str,
    warehouse_dir: str,
    fmt: str = "parquet",
    now: datetime | None = None,
) -> ExportResult:
    if fmt not in ("parquet", "csv"):
        raise ValueError(f"unsupported export format: {fmt!r}")

    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S")
    partition = os.path.join(warehouse_dir, f"tenant={tenant_id}")
    os.makedirs(partition, exist_ok=True)
    path = os.path.join(partition, f"contacts-{stamp}.{fmt}")

    # Stream in batches so memory stays flat regardless of tenant size.
    n_rows = 0
    if fmt == "parquet":
        schema = _arrow_schema()
        with pq.ParquetWriter(path, schema) as writer:
            for batch in _batched(_rows(session, tenant_id), 500):
                writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                n_rows += len(batch)
    else:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            csv_writer = csv.DictWriter(fh, fieldnames=_COLUMNS)
            csv_writer.writeheader()
            for row in _rows(session, tenant_id):
                csv_writer.writerow(row)
                n_rows += 1

    log.info("export", tenant_id=tenant_id, fmt=fmt, n_rows=n_rows, path=path)
    return ExportResult(path=path, n_rows=n_rows, fmt=fmt)


def _batched(iterable, size: int):
    batch: list = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _arrow_schema() -> pa.Schema:
    # Explicit types so an empty export still writes a well-typed file.
    return pa.schema([
        ("id", pa.string()), ("email", pa.string()), ("normalized_email", pa.string()),
        ("full_name", pa.string()), ("company", pa.string()), ("domain", pa.string()),
        ("status", pa.string()), ("heuristic_score", pa.float64()),
        ("mail_routing_state", pa.string()), ("duplicate_of_id", pa.string()),
        ("verified_at", pa.string()), ("created_at", pa.string()),
    ])
