"""Proxy to Last9 labels API — used by the filter builder for autocomplete."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crypto
from app.config import get_settings
from app.database import get_db
from app.last9_oauth import refresh_access_token, token_status
from app.models import Last9Credential

router = APIRouter(prefix="/credentials", tags=["labels"])

_TIMEOUT = 10.0


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
    result = refresh_access_token(crypto.decrypt(cred.encrypted_refresh_token))
    cred.encrypted_access_token = crypto.encrypt(result["access_token"])
    cred.access_token_expires_at = result["expires_at"]
    db.commit()
    return result["access_token"]


@router.get("/{cid}/labels")
async def list_labels(cid: int, db: Session = Depends(get_db)) -> list[str]:
    cred = _cred_or_404(db, cid)
    token = _resolve_token(cred, db)
    s = get_settings()
    url = f"{s.last9_api_base}/organizations/{cred.org_slug}/logs/api/v1/labels"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(url, headers=_headers(token))
    if not r.is_success:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Last9 labels failed: {r.status_code}")
    return r.json().get("data", [])


@router.get("/{cid}/labels/{label_name}/values")
async def list_label_values(cid: int, label_name: str, db: Session = Depends(get_db)) -> list[str]:
    cred = _cred_or_404(db, cid)
    token = _resolve_token(cred, db)
    s = get_settings()
    url = f"{s.last9_api_base}/organizations/{cred.org_slug}/logs/api/v1/label/{label_name}/values"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(url, headers=_headers(token))
    if not r.is_success:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Last9 label values failed: {r.status_code}"
        )
    return r.json().get("data", [])
