"""Export/import: turn a job or schedule's credential/index into a portable
reference (label/org_slug, name/region_code) instead of a database id, so a
config exported from one environment can be recreated in another where the
ids won't line up — and resolve those references back on import."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IndexTarget, Last9Credential
from app.schemas import CredentialRef, IndexRef


def credential_ref(cred: Last9Credential) -> CredentialRef:
    return CredentialRef(label=cred.label, org_slug=cred.org_slug)


def index_ref(idx: IndexTarget) -> IndexRef:
    return IndexRef(name=idx.name, region_code=idx.region_code)


def resolve_credential(db: Session, ref: CredentialRef) -> Last9Credential:
    cred = db.scalars(
        select(Last9Credential).where(Last9Credential.org_slug == ref.org_slug)
    ).first()
    if cred is None:
        cred = db.scalars(select(Last9Credential).where(Last9Credential.label == ref.label)).first()
    if cred is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"no credential found for org_slug={ref.org_slug!r} or label={ref.label!r} "
            "— create it in this environment first",
        )
    return cred


def resolve_index(db: Session, ref: IndexRef) -> IndexTarget:
    idx = db.scalars(
        select(IndexTarget).where(
            IndexTarget.region_code == ref.region_code, IndexTarget.name == ref.name
        )
    ).first()
    if idx is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"no index target named {ref.name!r} in region {ref.region_code!r} "
            "— create it in this environment first",
        )
    return idx
