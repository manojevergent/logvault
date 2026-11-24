"""Credentials CRUD + test-connection.

Refresh tokens are encrypted at rest and never returned. test-connection
validates the credential against Last9 and caches the resulting access token.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, crypto, last9_config
from app.database import get_db
from app.deps import require_admin
from app.last9_oauth import refresh_access_token, token_status
from app.models import IndexTarget, Last9Credential, User
from app.schemas import CredentialCreate, CredentialOut, TestConnectionResult

router = APIRouter(prefix="/credentials", tags=["credentials"])


def _to_out(c: Last9Credential) -> CredentialOut:
    return CredentialOut(
        id=c.id,
        label=c.label,
        org_slug=c.org_slug,
        owner_scope=c.owner_scope,
        created_by=c.created_by,
        created_at=c.created_at,
        refresh_token_preview=f"••••{c.refresh_token_last4}",
        access_token_expires_at=c.access_token_expires_at,
        token_status=token_status(c.access_token_expires_at),
    )


def _get_or_404(db: Session, cred_id: int) -> Last9Credential:
    cred = db.get(Last9Credential, cred_id)
    if cred is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "credential not found")
    return cred


@router.post("", response_model=CredentialOut, status_code=status.HTTP_201_CREATED)
def create_credential(
    body: CredentialCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> CredentialOut:
    cred = Last9Credential(
        label=body.label,
        org_slug=body.org_slug,
        encrypted_refresh_token=crypto.encrypt(body.refresh_token),
        refresh_token_last4=body.refresh_token[-4:],
        encrypted_access_token=crypto.encrypt(body.access_token) if body.access_token else None,
        owner_scope=body.owner_scope,
    )
    db.add(cred)
    db.flush()
    audit.record(db, "create", "credential", cred.id, {"label": cred.label}, user_id=user.email)
    db.commit()
    db.refresh(cred)
    return _to_out(cred)


@router.get("", response_model=list[CredentialOut])
def list_credentials(db: Session = Depends(get_db)) -> list[CredentialOut]:
    creds = db.scalars(select(Last9Credential).order_by(Last9Credential.created_at.desc())).all()
    return [_to_out(c) for c in creds]


@router.delete("/{cred_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(
    cred_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    # No FK on these columns, so a delete used to silently orphan whatever
    # pointed at it — the index target kept handing the dead id to the wizard.
    used_by = db.scalars(select(IndexTarget.name).where(IndexTarget.credential_id == cred_id)).all()
    if used_by:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"credential is used by index target(s): {', '.join(used_by)}",
        )
    db.delete(_get_or_404(db, cred_id))
    audit.record(db, "delete", "credential", cred_id, user_id=user.email)
    db.commit()


@router.post("/{cred_id}/test", response_model=TestConnectionResult)
def test_connection(cred_id: int, db: Session = Depends(get_db)) -> TestConnectionResult:
    cred = _get_or_404(db, cred_id)
    try:
        result = refresh_access_token(
            crypto.decrypt(cred.encrypted_refresh_token),
            api_base=last9_config.api_base(db),
        )
    except (ValueError, httpx.HTTPError) as exc:
        return TestConnectionResult(ok=False, message=str(exc), token_status="expired")

    # Cache the fresh access token (and rotated refresh token, if any).
    cred.encrypted_access_token = crypto.encrypt(result["access_token"])
    cred.access_token_expires_at = result["expires_at"]
    if result.get("refresh_token"):
        cred.encrypted_refresh_token = crypto.encrypt(result["refresh_token"])
        cred.refresh_token_last4 = result["refresh_token"][-4:]
    db.commit()

    return TestConnectionResult(
        ok=True,
        message="Connection successful",
        token_status=token_status(result["expires_at"]),
        expires_at=result["expires_at"],
    )
