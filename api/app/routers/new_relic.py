"""New Relic connections: encrypted account/API-key pairs + test connection."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, crypto, newrelic
from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models import Comparison, NewRelicCredential, User
from app.schemas import (
    NewRelicCredentialCreate,
    NewRelicCredentialOut,
    NewRelicCredentialUpdate,
    NewRelicTestResult,
)

router = APIRouter(prefix="/newrelic/credentials", tags=["newrelic"])


def _to_out(cred: NewRelicCredential) -> NewRelicCredentialOut:
    return NewRelicCredentialOut(
        id=cred.id,
        label=cred.label,
        account_id=cred.account_id,
        region=cred.region,
        api_key_preview=f"••••{cred.api_key_last4}",
        created_by=cred.created_by,
        created_at=cred.created_at,
    )


@router.post("", response_model=NewRelicCredentialOut, status_code=status.HTTP_201_CREATED)
def create_credential(
    body: NewRelicCredentialCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> NewRelicCredentialOut:
    label = body.label.strip()
    api_key = body.api_key.strip()
    if not label:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "label is required")
    if not api_key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "API key is required")
    if body.account_id <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "account id must be positive")

    cred = NewRelicCredential(
        label=label,
        account_id=body.account_id,
        region=body.region,
        encrypted_api_key=crypto.encrypt(api_key),
        api_key_last4=api_key[-4:],
        created_by=user.email,
    )
    db.add(cred)
    db.flush()
    audit.record(
        db,
        "create",
        "newrelic_credential",
        cred.id,
        {"label": cred.label, "account_id": cred.account_id, "region": cred.region},
        user_id=user.email,
    )
    db.commit()
    db.refresh(cred)
    return _to_out(cred)


@router.get("", response_model=list[NewRelicCredentialOut])
def list_credentials(db: Session = Depends(get_db)) -> list[NewRelicCredentialOut]:
    creds = db.scalars(
        select(NewRelicCredential).order_by(NewRelicCredential.created_at.desc())
    ).all()
    return [_to_out(c) for c in creds]


@router.put("/{cred_id}", response_model=NewRelicCredentialOut)
def update_credential(
    cred_id: int,
    body: NewRelicCredentialUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> NewRelicCredentialOut:
    cred = db.get(NewRelicCredential, cred_id)
    if cred is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "New Relic connection not found")
    if body.label is not None:
        label = body.label.strip()
        if not label:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "label is required")
        cred.label = label
    if body.account_id is not None:
        if body.account_id <= 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "account id must be positive")
        cred.account_id = body.account_id
    if body.region is not None:
        cred.region = body.region
    if body.api_key is not None and body.api_key.strip():
        api_key = body.api_key.strip()
        cred.encrypted_api_key = crypto.encrypt(api_key)
        cred.api_key_last4 = api_key[-4:]
    audit.record(
        db,
        "update",
        "newrelic_credential",
        cred.id,
        {"label": cred.label, "account_id": cred.account_id, "region": cred.region},
        user_id=user.email,
    )
    db.commit()
    db.refresh(cred)
    return _to_out(cred)


@router.delete("/{cred_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(
    cred_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    cred = db.get(NewRelicCredential, cred_id)
    if cred is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "New Relic connection not found")

    used_by = db.scalars(
        select(Comparison.name).where(Comparison.nr_credential_id == cred_id)
    ).all()
    if used_by:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"connection is used by comparison(s): {', '.join(used_by)}",
        )

    db.delete(cred)
    audit.record(db, "delete", "newrelic_credential", cred_id, user_id=user.email)
    db.commit()


@router.post("/{cred_id}/test", response_model=NewRelicTestResult)
def test_credential(
    cred_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> NewRelicTestResult:
    cred = db.get(NewRelicCredential, cred_id)
    if cred is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "New Relic connection not found")
    try:
        api_key = crypto.decrypt(cred.encrypted_api_key)
    except Exception:  # noqa: BLE001 - key rotation or a corrupted row
        return NewRelicTestResult(
            ok=False,
            message="stored API key could not be decrypted — re-add this connection",
        )
    try:
        account_name = newrelic.test_connection(
            api_key=api_key,
            account_id=cred.account_id,
            region=cred.region,
        )
    except newrelic.NewRelicError as exc:
        return NewRelicTestResult(ok=False, message=str(exc))
    return NewRelicTestResult(
        ok=True,
        message=f"Connected to {account_name}",
        account_name=account_name,
    )
