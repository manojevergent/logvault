"""Proxy to Last9 labels API — used by the filter builder for autocomplete."""

from __future__ import annotations

import threading

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crypto, last9_config
from app.database import get_db
from app.last9_oauth import refresh_access_token, token_status
from app.models import Last9Credential

router = APIRouter(prefix="/credentials", tags=["labels"])

_TIMEOUT = 10.0
# A refresh rotates the token, so two concurrent requests must not both spend the
# same refresh token; serialize them and let the second read the new one.
_refresh_lock = threading.Lock()


def _cred_or_404(db: Session, cid: int) -> Last9Credential:
    c = db.get(Last9Credential, cid)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "credential not found")
    return c


def _headers(access_token: str) -> dict[str, str]:
    return {"X-LAST9-API-TOKEN": f"Bearer {access_token}"}


def _resolve_token(cred: Last9Credential, db: Session) -> str:
    """Return a valid access token, refreshing from Last9 if expired."""
    if token_status(cred.access_token_expires_at) == "valid" and cred.encrypted_access_token:
        return crypto.decrypt(cred.encrypted_access_token)
    with _refresh_lock:
        # Another request may have refreshed while this one waited for the lock.
        db.refresh(cred)
        if token_status(cred.access_token_expires_at) == "valid" and cred.encrypted_access_token:
            return crypto.decrypt(cred.encrypted_access_token)
        result = refresh_access_token(
            crypto.decrypt(cred.encrypted_refresh_token),
            api_base=last9_config.api_base(db),
        )
        cred.encrypted_access_token = crypto.encrypt(result["access_token"])
        cred.access_token_expires_at = result["expires_at"]
        if result.get("refresh_token"):
            cred.encrypted_refresh_token = crypto.encrypt(result["refresh_token"])
            cred.refresh_token_last4 = result["refresh_token"][-4:]
        db.commit()
        return result["access_token"]


# Sync endpoints on purpose: the DB session and the token refresh are blocking,
# and an `async def` would run them on the event loop and stall every other
# request for the duration of the Last9 call.
@router.get("/{cid}/labels")
def list_labels(cid: int, db: Session = Depends(get_db)) -> list[str]:
    cred = _cred_or_404(db, cid)
    token = _resolve_token(cred, db)
    base = last9_config.api_base(db)
    url = f"{base}/organizations/{cred.org_slug}/logs/api/v1/labels"
    with httpx.Client(timeout=_TIMEOUT) as client:
        r = client.get(url, headers=_headers(token))
    if not r.is_success:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Last9 labels failed: {r.status_code}")
    return r.json().get("data", [])


@router.get("/{cid}/labels/{label_name}/values")
def list_label_values(cid: int, label_name: str, db: Session = Depends(get_db)) -> list[str]:
    cred = _cred_or_404(db, cid)
    token = _resolve_token(cred, db)
    base = last9_config.api_base(db)
    url = f"{base}/organizations/{cred.org_slug}/logs/api/v1/label/{label_name}/values"
    with httpx.Client(timeout=_TIMEOUT) as client:
        r = client.get(url, headers=_headers(token))
    if not r.is_success:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Last9 label values failed: {r.status_code}"
        )
    return r.json().get("data", [])
