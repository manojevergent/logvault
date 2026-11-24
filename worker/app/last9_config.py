"""The Last9 base URL the admin UI saved (falls back to the env var).

The API owns the write path; the worker only reads. Read per job so a saved
BYOC endpoint applies to the next dispatch without restarting the worker —
images are baked here, so a restart would otherwise be the only way to pick it
up.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app import db
from app.config import get_settings

LAST9_KEY = "last9"


def api_base(engine: Engine | None = None) -> str:
    """Active Last9 base URL, without a trailing slash.

    A settings read must never take a job down: any failure (missing table, a
    replica that is briefly unavailable, a malformed row) falls back to the env
    value, which is what the deployment used before this setting existed.
    """
    fallback = get_settings().last9_api_base.rstrip("/")
    try:
        if engine is not None:
            with engine.connect() as conn:
                row = conn.execute(
                    select(db.app_settings.c.value).where(db.app_settings.c.key == LAST9_KEY)
                ).first()
        else:
            with db.engine().connect() as conn:
                row = conn.execute(
                    select(db.app_settings.c.value).where(db.app_settings.c.key == LAST9_KEY)
                ).first()
        saved = (row[0] or {}).get("api_base") if row else None
        return (saved or fallback).rstrip("/")
    except Exception:  # noqa: BLE001 - the env fallback is always valid
        return fallback
