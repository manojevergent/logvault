"""Minimal Last9 OAuth for the API's needs: validate a refresh token and read
its expiry, so 'test connection' works and we can cache the access token.

ponytail: this duplicates a few lines of the worker's last9.tokens (oauth POST +
expiry parse). The API only needs validate-and-cache, not the full refresh/retry
client. If a third consumer appears, promote last9 to a shared package and import
it in both.
"""

from __future__ import annotations

import time
from datetime import datetime

import httpx

from app import last9_config

_ASSUMED_LIFETIME = 24 * 3600
_EXPIRING_WINDOW = 3600  # within 1h of expiry => "expiring"


def refresh_access_token(refresh_token: str, api_base: str | None = None) -> dict:
    """POST the refresh token; return {access_token, expires_at, refresh_token?}.

    `api_base` defaults to the active endpoint (admin setting, else the env
    fallback). Callers that already resolved it pass it in to avoid a second
    settings read.

    Raises httpx.HTTPError on transport failure, ValueError on a non-200 or a
    response missing access_token.
    """
    base = (api_base or last9_config.api_base()).rstrip("/")
    url = f"{base}/oauth/access_token"
    resp = httpx.post(url, json={"refresh_token": refresh_token}, timeout=15.0)
    if resp.status_code != 200:
        raise ValueError(f"Last9 returned HTTP {resp.status_code}")
    payload = resp.json()
    if not payload.get("access_token"):
        raise ValueError("response missing access_token")
    return {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token"),
        "expires_at": _parse_expiry(payload),
    }


def token_status(expires_at: int | None, now: float | None = None) -> str:
    if expires_at is None:
        return "unknown"
    now = time.time() if now is None else now
    if now >= expires_at:
        return "expired"
    if now >= expires_at - _EXPIRING_WINDOW:
        return "expiring"
    return "valid"


def _parse_expiry(payload: dict) -> int:
    value = payload.get("expires_at")
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
    if payload.get("expires_in") is not None:
        return int(time.time() + float(payload["expires_in"]))
    return int(time.time() + _ASSUMED_LIFETIME)
