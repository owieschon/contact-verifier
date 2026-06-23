"""Command line: provision a tenant, seed synthetic contacts, verify, export, serve.

Enough to drive the whole flow from a clean clone without writing any HTTP:

    contact-verifier provision --name "Acme"      # prints a one-time API key
    contact-verifier seed    --key cv_...          # load synthetic sample contacts
    contact-verifier verify  --key cv_...          # run verification (real DNS)
    contact-verifier export  --key cv_... --format parquet
    contact-verifier serve                          # run the REST API
"""

from __future__ import annotations

import argparse
import json
import sys
from importlib.resources import files

from sqlalchemy import select

from contact_verifier.auth import hash_key
from contact_verifier.config import get_settings
from contact_verifier.db import repository as repo
from contact_verifier.db.base import SessionLocal, init_db
from contact_verifier.db.models import ApiKey
from contact_verifier.export import export_tenant_contacts
from contact_verifier.logging import configure_logging
from contact_verifier.services import verify_tenant_contacts


def _tenant_for_key(session, key: str) -> str:
    row = session.scalar(
        select(ApiKey).where(ApiKey.key_hash == hash_key(key), ApiKey.revoked_at.is_(None))
    )
    if row is None:
        sys.exit("unknown or revoked API key")
    return row.tenant_id


def cmd_provision(args) -> None:
    init_db()
    with SessionLocal() as s:
        tenant = repo.create_tenant(s, args.name)
        _key, plaintext = repo.create_api_key(s, tenant.id)
        s.commit()
        print(f"tenant:  {tenant.id}  ({args.name})")
    print(f"API key (store this, shown once): {plaintext}")


def cmd_seed(args) -> None:
    init_db()
    raw = files("contact_verifier.data").joinpath("sample_contacts.json").read_text()
    contacts = json.loads(raw)
    with SessionLocal() as s:
        tenant_id = _tenant_for_key(s, args.key)
        for c in contacts:
            repo.add_contact(
                s, tenant_id, email=c["email"],
                full_name=c.get("full_name"), company=c.get("company"), source="seed",
            )
        s.commit()
    print(f"seeded {len(contacts)} synthetic contacts")


def cmd_verify(args) -> None:
    init_db()
    with SessionLocal() as s:
        tenant_id = _tenant_for_key(s, args.key)
        run = verify_tenant_contacts(s, tenant_id)
    print(f"verified {run.n_verified} contacts ({run.n_duplicates} duplicates)")


def cmd_export(args) -> None:
    init_db()
    with SessionLocal() as s:
        tenant_id = _tenant_for_key(s, args.key)
        result = export_tenant_contacts(
            s, tenant_id, get_settings().warehouse_dir, fmt=args.format
        )
    print(f"exported {result.n_rows} rows -> {result.path}")


def cmd_serve(args) -> None:
    import uvicorn

    uvicorn.run("contact_verifier.app:app", host=args.host, port=args.port)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="contact-verifier", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("provision", help="create a tenant and an API key")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_provision)

    for name, func, help_text in [
        ("seed", cmd_seed, "load synthetic sample contacts"),
        ("verify", cmd_verify, "run verification over a tenant's contacts"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--key", required=True)
        p.set_defaults(func=func)

    p = sub.add_parser("export", help="export verified contacts to the warehouse")
    p.add_argument("--key", required=True)
    p.add_argument("--format", choices=["parquet", "csv"], default="parquet")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("serve", help="run the REST API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
