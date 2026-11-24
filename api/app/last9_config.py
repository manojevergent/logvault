"""Runtime Last9 endpoint configuration.

The base URL used to be env-only (`LAST9_API_BASE`). Moving to BYOC puts the
Last9 instance on the customer's own cloud, so the URL has to change without
rebuilding images. It is stored in `app_settings` under "last9" and read at call
time; the env var stays as the fallback so existing deployments keep working
until someone saves a value.

Read-at-call-time matters: a saved change applies to the next request/job with
no restart, the same way the notification settings behave.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from app.config import get_settings
from app.database import SessionLocal
from app.models import AppSetting

LAST9_KEY = "last9"
_FIELD = "api_base"


def normalize_api_base(value: str) -> str:
    """Validate and canonicalise a Last9 base URL.

    A BYOC install may sit behind a gateway prefix, so a path is allowed. A bare
    host gets `https://` so "last9.internal.example.com" works as typed. The
    trailing slash is dropped so callers can join paths as
    ``f"{base}/organizations/..."`` without producing a double slash.
    """
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Last9 API base URL is required")
    if "://" not in raw:
        raw = f"https://{raw}"
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        raise ValueError("Last9 API base URL must start with http:// or https://")
    if not parts.netloc:
        raise ValueError("Last9 API base URL needs a host")
    if parts.query or parts.fragment:
        raise ValueError("Last9 API base URL cannot include a query or fragment")
    return raw.rstrip("/")


def env_api_base() -> str:
    """The configured fallback (`LAST9_API_BASE`), without a trailing slash."""
    return get_settings().last9_api_base.rstrip("/")


def load_config(db=None) -> dict:
    """Return `{"api_base": ..., "source": "database"|"env"}`.

    A saved value wins; otherwise the env var is reported. `source` lets the
    admin UI say where the active URL came from, so "I saved it but it still
    uses the old one" is visible instead of a guess.

    A settings read must never be the reason a request fails: if the table is
    missing or the read errors, fall back to the env value. That keeps the API
    and worker working during a rolling deploy, before the settings row exists.
    """
    owned = db is None
    session = None
    try:
        session = db or SessionLocal()
        row = session.get(AppSetting, LAST9_KEY)
        stored = (row.value or {}) if row else {}
        saved = stored.get(_FIELD)
        if saved:
            return {"api_base": saved, "source": "database"}
    except Exception:  # noqa: BLE001 - fall back to the env default
        pass
    finally:
        if owned and session is not None:
            session.close()
    return {"api_base": env_api_base(), "source": "env"}


def api_base(db=None) -> str:
    """The active Last9 base URL. Callers join paths onto this."""
    return load_config(db)["api_base"]


def save_config(db, api_base: str, updated_by: str | None = None) -> str:
    """Persist a validated base URL. Returns the canonical form."""
    base = normalize_api_base(api_base)
    row = db.get(AppSetting, LAST9_KEY)
    if row is None:
        row = AppSetting(key=LAST9_KEY, value={})
        db.add(row)
    row.value = {**(row.value or {}), _FIELD: base}
    row.updated_by = updated_by
    return base
