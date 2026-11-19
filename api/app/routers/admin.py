"""Admin: audit log viewer + settings readout.

ponytail: no user/role management yet - auth/SSO was deferred (Phase 1 decision).
These endpoints are read-only views over the audit trail and env config.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, notifications, tasks_client
from app.config import get_settings
from app.database import get_db
from app.deps import require_admin
from app.models import AppSetting, AuditLog, User
from app.redis_client import get_redis
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
    # Blank on save means "keep the stored one" - it is never sent to the
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
    - no restart, unlike the env vars this replaces (which remain the fallback)."""
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


# --- system health alerts ----------------------------------------------------

HEALTH_ALERTS_KEY = "health_alerts"

HEALTH_ALERT_DEFAULTS: dict[str, object] = {
    "enabled": True,
    "cpu_threshold_pct": 85,
    "memory_threshold_pct": 85,
    "disk_threshold_pct": 85,
    # Blank = the export volume, which is the one whose exhaustion breaks Postgres.
    "disk_path": "",
    "cooldown_minutes": 30,
    "slack": True,
    "email": False,
    "recipients": [],
    "notify_on_recovery": True,
}


class HealthAlertConfig(BaseModel):
    enabled: bool = True
    cpu_threshold_pct: float = 85
    memory_threshold_pct: float = 85
    disk_threshold_pct: float = 85
    # Blank = the export volume. The worker falls back to it when this path does
    # not exist, so a typo cannot point the alert at an empty directory.
    disk_path: str = ""
    cooldown_minutes: int = 30
    slack: bool = True
    # Off until a recipient is configured - an on-but-empty channel would
    # silently deliver nothing.
    email: bool = False
    recipients: list[str] = []
    notify_on_recovery: bool = True


class HealthAlertConfigOut(HealthAlertConfig):
    """Response shape. The path actually sampled is in ``/health/metrics``."""


def _validate_health(body: HealthAlertConfig) -> None:
    for field in ("cpu_threshold_pct", "memory_threshold_pct", "disk_threshold_pct"):
        value = getattr(body, field)
        if not 1 <= value <= 100:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{field} must be between 1 and 100",
            )
    if not 1 <= body.cooldown_minutes <= 1440:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "cooldown_minutes must be between 1 and 1440",
        )
    if body.disk_path and not body.disk_path.startswith("/"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "disk_path must be an absolute path (or blank for the export volume)",
        )
    if body.email and not body.recipients:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "email alerts need at least one recipient (or switch email off)",
        )


@router.get("/settings/health-alerts", response_model=HealthAlertConfigOut)
def get_health_alerts(
    db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> HealthAlertConfigOut:
    row = db.get(AppSetting, HEALTH_ALERTS_KEY)
    saved = dict(row.value) if row and row.value else {}
    merged = {
        **HEALTH_ALERT_DEFAULTS,
        **{k: v for k, v in saved.items() if k in HEALTH_ALERT_DEFAULTS},
    }
    # The configured value, so the admin form can round-trip it. The path the
    # sampler actually used is in /health/metrics, which is what the meters show.
    return HealthAlertConfigOut(**merged)


@router.put("/settings/health-alerts")
def update_health_alerts(
    body: HealthAlertConfig,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    _validate_health(body)
    value = body.model_dump()
    value["recipients"] = [r.strip() for r in value["recipients"] if r and r.strip()]
    value["disk_path"] = str(value.get("disk_path") or "").strip()
    row = db.get(AppSetting, HEALTH_ALERTS_KEY)
    if row is None:
        db.add(AppSetting(key=HEALTH_ALERTS_KEY, value=value, updated_by=user.email))
    else:
        row.value = value
        row.updated_by = user.email
    audit.record(
        db,
        "update",
        "settings",
        None,
        {
            "group": "health_alerts",
            "cpu": value["cpu_threshold_pct"],
            "memory": value["memory_threshold_pct"],
            "disk": value["disk_threshold_pct"],
        },
        user_id=user.email,
    )
    db.commit()
    return {"ok": True, "message": "Health alert settings saved."}


@router.post("/settings/health-alerts/test")
def test_health_alert(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    """Send one alert through the configured channels, using the live sample.

    Returns what each channel actually did. The old version reported a blanket
    success even when email was switched off or SMTP rejected the message, which
    made "no email arrived" impossible to diagnose from the UI.
    """
    row = db.get(AppSetting, HEALTH_ALERTS_KEY)
    saved = dict(row.value) if row and row.value else {}
    cfg = {
        **HEALTH_ALERT_DEFAULTS,
        **{k: v for k, v in saved.items() if k in HEALTH_ALERT_DEFAULTS},
    }
    sample = _health_sample() or {}
    results = notifications.send_health_alert(
        subject="LogVault: test health alert",
        body=(
            "This is a test of the LogVault system-health alert channel.\n\n"
            f"CPU: {sample.get('cpu_pct', 'n/a')}%\n"
            f"Memory: {sample.get('memory_pct', 'n/a')}%\n"
            f"Disk: {sample.get('disk_pct', 'n/a')}%\n"
        ),
        slack=bool(cfg.get("slack")),
        email=bool(cfg.get("email")),
        recipients=[str(r).strip() for r in (cfg.get("recipients") or []) if str(r).strip()],
    )

    delivered = [name for name, detail in results.items() if detail.get("ok")]
    failed = {
        name: str(detail.get("reason"))
        for name, detail in results.items()
        if detail.get("attempted") and not detail.get("ok")
    }
    skipped = {
        name: str(detail.get("reason"))
        for name, detail in results.items()
        if not detail.get("attempted")
    }

    if delivered and not failed:
        message = f"Test alert sent via {', '.join(delivered)}."
    elif delivered and failed:
        message = f"Sent via {', '.join(delivered)}, but " + "; ".join(
            f"{name} failed: {reason}" for name, reason in failed.items()
        )
    elif failed:
        message = "Nothing was delivered - " + "; ".join(
            f"{name}: {reason}" for name, reason in failed.items()
        )
    else:
        message = "Nothing was sent - " + "; ".join(
            f"{name}: {reason}" for name, reason in skipped.items()
        )

    return {
        "ok": bool(delivered),
        "message": message,
        "channels": results,
        "failed": failed,
        "skipped": skipped,
    }


def _health_sample() -> dict | None:
    try:
        raw = get_redis().get("logvault:health:sample")
    except Exception:  # noqa: BLE001
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


@router.get("/health/metrics")
def health_metrics(db: Session = Depends(get_db)) -> dict:
    """Latest sample published by the worker's health monitor.

    Includes the active thresholds so any signed-in user can colour the widget
    without needing the admin-only settings endpoint.
    """
    row = db.get(AppSetting, HEALTH_ALERTS_KEY)
    saved = dict(row.value) if row and row.value else {}
    cfg = {
        **HEALTH_ALERT_DEFAULTS,
        **{k: v for k, v in saved.items() if k in HEALTH_ALERT_DEFAULTS},
    }
    thresholds = {
        "cpu": float(cfg["cpu_threshold_pct"]),
        "memory": float(cfg["memory_threshold_pct"]),
        "disk": float(cfg["disk_threshold_pct"]),
    }
    sample = _health_sample()
    if sample is None:
        return {
            "available": False,
            "message": "No sample yet - the worker publishes one every health-check interval.",
            "thresholds": thresholds,
            "enabled": bool(cfg.get("enabled")),
        }
    return {
        "available": True,
        **sample,
        "thresholds": thresholds,
        "enabled": bool(cfg.get("enabled")),
    }


# --- worker capacity --------------------------------------------------------


class WorkerConcurrency(BaseModel):
    concurrency: int


@router.get("/admin/worker")
def worker_capacity(_: User = Depends(require_admin)) -> dict:
    return tasks_client.worker_capacity()


@router.post("/admin/worker/concurrency")
def set_worker_concurrency(
    body: WorkerConcurrency,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    if not 1 <= body.concurrency <= 64:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "concurrency must be between 1 and 64"
        )
    result = tasks_client.set_worker_concurrency(body.concurrency)
    audit.record(
        db,
        "update",
        "worker",
        None,
        {"concurrency": body.concurrency, "previous": result.get("previous")},
        user_id=user.email,
    )
    db.commit()
    return result
