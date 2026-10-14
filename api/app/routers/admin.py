"""Admin: audit log viewer + settings readout.

ponytail: no user/role management yet — auth/SSO was deferred (Phase 1 decision).
These endpoints are read-only views over the audit trail and env config.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, notifications
from app.config import get_settings
from app.database import get_db
from app.deps import require_admin
from app.models import AuditLog, User
from app.routers.indexes import REGIONS
from app.schemas import AuditOut, SettingsOut

router = APIRouter(tags=["admin"])


@router.get("/audit", response_model=list[AuditOut])
def list_audit(
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[AuditOut]:
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
    return [
        AuditOut(
            id=a.id,
            user_id=a.user_id,
            action=a.action,
            entity=a.entity,
            entity_id=a.entity_id,
            metadata=a.meta,
            ts=a.ts,
        )
        for a in rows
    ]


@router.get("/settings", response_model=SettingsOut)
def settings_readout(_: User = Depends(require_admin)) -> SettingsOut:
    s = get_settings()
    return SettingsOut(
        environment=s.environment,
        default_org_slug=s.default_org_slug,
        storage_dir=s.storage_dir,
        export_retention_days=s.export_retention_days,
        download_url_ttl_seconds=s.download_url_ttl_seconds,
        region_count=len(REGIONS),
    )


class NotificationConfig(BaseModel):
    slack_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    # Blank on save means "keep the stored one" — it is never sent to the
    # browser, so the form has nothing to send back.
    smtp_password: str = ""
    smtp_from: str = ""


class NotificationConfigOut(BaseModel):
    slack_webhook_url: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_from: str
    # The password itself never leaves the server; the form shows a placeholder.
    smtp_password_set: bool


@router.get("/settings/notifications", response_model=NotificationConfigOut)
def get_notifications(
    db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> NotificationConfigOut:
    cfg = notifications.load_config(db)
    return NotificationConfigOut(
        slack_webhook_url=cfg["slack_webhook_url"],
        smtp_host=cfg["smtp_host"],
        smtp_port=int(cfg["smtp_port"]),
        smtp_user=cfg["smtp_user"],
        smtp_from=cfg["smtp_from"],
        smtp_password_set=bool(cfg["smtp_password"]),
    )


@router.patch("/settings/notifications")
def update_notifications(
    cfg: NotificationConfig,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """Persist notification config. Read at send time, so it applies immediately
    — no restart, unlike the env vars this replaces (which remain the fallback)."""
    notifications.save_config(db, cfg.model_dump(), updated_by=user.email)
    # The SMTP password is in the payload; record that it changed, never what to.
    audit.record(
        db,
        "update",
        "settings",
        None,
        {"group": "notifications", "password_changed": bool(cfg.smtp_password)},
        user_id=user.email,
    )
    db.commit()
    return {"ok": True, "message": "Notification settings saved."}
