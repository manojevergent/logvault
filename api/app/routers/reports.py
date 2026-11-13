"""Customer-wise scheduled-extraction reporting.

Every number here comes from rows the scheduler actually created
(``jobs.created_by = "schedule:<id>"``), so the report cannot drift from the
job history:

- Counts are ``rows_written`` from **completed** runs only. A failed or
  canceled run contributes its status to the day, never phantom rows.
- A day is keyed by the UTC date the run started (``created_at``), which is
  what "today's extraction" means to an operator.
- Comparisons use today, yesterday, and the same weekday last week; a
  percentage is omitted (null) when the baseline is zero rather than shown as
  an infinite increase.
- "Missed" is only reported for schedules that are enabled and expected to run
  at least daily, and only when nothing has run for 36 hours. A weekly schedule
  is never labeled missed just because it has no job today.

Retention is a view setting (AppSetting ``reports``): the page can look back at
most this many days. Raw job history and files are untouched.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import audit
from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models import AppSetting, IndexTarget, Job, Schedule, User
from app.schemas import (
    ReportAlertOut,
    ReportCustomerOut,
    ReportDayOut,
    ReportOut,
    ReportScheduleOut,
    ReportSettingsOut,
    ReportSettingsUpdate,
    ReportTotalsOut,
)

router = APIRouter(prefix="/reports", tags=["reports"])

REPORTS_KEY = "reports"
DEFAULT_RETENTION_DAYS = 90
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 365
UNASSIGNED = "(unassigned)"
ACTIVE_STATUSES = {"queued", "running", "paused"}
# A daily schedule gets a full day plus slack before it is called missed.
MISSED_AFTER_HOURS = 36


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _utc_date(value: datetime | None) -> date | None:
    value = _aware(value)
    return value.astimezone(UTC).date() if value else None


def _clamp_days(value: int) -> int:
    return max(MIN_RETENTION_DAYS, min(MAX_RETENTION_DAYS, max(1, int(value))))


def _retention(db: Session) -> tuple[int, AppSetting | None]:
    row = db.get(AppSetting, REPORTS_KEY)
    saved: dict[str, Any] = dict(row.value) if row and isinstance(row.value, dict) else {}
    try:
        days = _clamp_days(int(saved.get("retention_days", DEFAULT_RETENTION_DAYS)))
    except (TypeError, ValueError):
        days = DEFAULT_RETENTION_DAYS
    return days, row


def _pct(current: int, baseline: int | None) -> float | None:
    """Percentage change, or None when there is no baseline to compare to."""
    if baseline is None or baseline == 0:
        return None
    return round((current - baseline) * 100.0 / baseline, 1)


def _rows(jobs: list[Job]) -> int:
    return sum(int(job.rows_written or 0) for job in jobs if job.status == "completed")


def _expected_daily(schedule: Schedule | None) -> bool:
    if schedule is None:
        return False
    return bool(schedule.calendar_day or (schedule.interval_seconds or 0) <= 86400)


def _day_status(
    jobs: list[Job],
    day: date,
    today: date,
    schedule: Schedule | None,
    expected_daily: bool,
) -> str:
    if not jobs:
        if schedule is None:
            return "none"
        if not schedule.enabled:
            return "off"
        if expected_daily:
            return "pending" if day == today else "missed"
        return "none"
    statuses = {job.status for job in jobs}
    if "failed" in statuses:
        return "failed"
    if statuses & ACTIVE_STATUSES:
        return "running"
    completed = "completed" in statuses
    canceled = "canceled" in statuses
    if canceled:
        return "partial" if completed else "canceled"
    return "ok"


def _job_customer(job: Job) -> str:
    spec = job.filter_spec or {}
    return str(spec.get("customer") or "").strip() or UNASSIGNED


def _job_name(job: Job) -> str:
    spec = job.filter_spec or {}
    return str(spec.get("label") or "").strip() or "Scheduled run"


def _latest(jobs: list[Job]) -> Job | None:
    if not jobs:
        return None
    return max(
        jobs,
        key=lambda job: (_aware(job.created_at) or datetime.min.replace(tzinfo=UTC), job.id),
    )


def _build_schedule(
    *,
    schedule_id: int | None,
    name: str,
    customer: str,
    enabled: bool,
    interval_seconds: int | None,
    calendar_day: bool,
    source: str | None,
    schedule: Schedule | None,
    schedule_last_run_at: datetime | None,
    jobs: list[Job],
    day_keys: list[date],
    today: date,
) -> ReportScheduleOut:
    by_day: dict[date, list[Job]] = defaultdict(list)
    for job in jobs:
        day = _utc_date(job.created_at)
        if day is not None:
            by_day[day].append(job)

    expected_daily = _expected_daily(schedule)
    # Include yesterday and the same weekday last week even when they fall
    # outside a 7-day view - the comparison is the point of the row.
    comparison_days = {today - timedelta(days=1), today - timedelta(days=7)}
    tracked_days = set(day_keys) | comparison_days
    day_rows: dict[date, int] = {
        day: _rows(by_day.get(day, [])) for day in tracked_days
    }

    days_out = [
        ReportDayOut(
            date=day.isoformat(),
            status=_day_status(by_day.get(day, []), day, today, schedule, expected_daily),
            rows=day_rows[day],
            runs=len(by_day.get(day, [])),
            completed=sum(1 for job in by_day.get(day, []) if job.status == "completed"),
            failed=sum(1 for job in by_day.get(day, []) if job.status == "failed"),
        )
        for day in day_keys
    ]

    today_rows = day_rows.get(today, 0)
    yesterday = today - timedelta(days=1)
    last_week = today - timedelta(days=7)
    yesterday_rows = day_rows.get(yesterday, 0)
    last_week_rows = day_rows.get(last_week, 0)

    latest = _latest(jobs)
    today_status = next((d.status for d in days_out if d.date == today.isoformat()), "none")

    return ReportScheduleOut(
        schedule_id=schedule_id,
        name=name,
        customer=customer,
        enabled=enabled,
        interval_seconds=interval_seconds,
        calendar_day=calendar_day,
        source=source,
        last_run_at=_aware(latest.created_at if latest else schedule_last_run_at),
        latest_job_id=latest.id if latest else None,
        today_status=today_status,
        today_rows=today_rows,
        yesterday_rows=yesterday_rows,
        last_week_rows=last_week_rows,
        pct_vs_yesterday=_pct(today_rows, yesterday_rows),
        pct_vs_last_week=_pct(today_rows, last_week_rows),
        pct_yesterday_vs_last_week=_pct(yesterday_rows, last_week_rows),
        failed_today=sum(
            1
            for job in by_day.get(today, [])
            if job.status == "failed"
        ),
        days=days_out,
    )


def _schedule_customer(schedule: Schedule, jobs: list[Job]) -> str:
    spec = schedule.filter_spec or {}
    customer = str(spec.get("customer") or "").strip()
    if customer:
        return customer
    latest = _latest(jobs)
    return _job_customer(latest) if latest else UNASSIGNED


def _schedule_source(schedule: Schedule | None, jobs: list[Job], sources: dict[int, str]) -> str | None:
    if schedule is not None and schedule.index_target_id is not None:
        return sources.get(schedule.index_target_id)
    latest = _latest(jobs)
    if latest is not None:
        return sources.get(latest.index_target_id)
    return None


@router.get("/settings", response_model=ReportSettingsOut)
def get_report_settings(db: Session = Depends(get_db)) -> ReportSettingsOut:
    days, row = _retention(db)
    return ReportSettingsOut(
        retention_days=days,
        updated_at=row.updated_at if row else None,
        updated_by=row.updated_by if row else None,
    )


@router.put("/settings", response_model=ReportSettingsOut)
def update_report_settings(
    body: ReportSettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> ReportSettingsOut:
    days = _clamp_days(body.retention_days)
    row = db.get(AppSetting, REPORTS_KEY)
    value = dict(row.value) if row and isinstance(row.value, dict) else {}
    value["retention_days"] = days
    if row is None:
        db.add(AppSetting(key=REPORTS_KEY, value=value, updated_by=user.email))
    else:
        row.value = value
        row.updated_by = user.email
    audit.record(db, "update", "reports", None, {"retention_days": days}, user_id=user.email)
    db.commit()
    row = db.get(AppSetting, REPORTS_KEY)
    return ReportSettingsOut(
        retention_days=days,
        updated_at=row.updated_at if row else None,
        updated_by=row.updated_by if row else None,
    )


@router.get("", response_model=ReportOut)
def get_report(
    days: int = Query(30, ge=1, le=365, description="look-back window in days"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),  # noqa: ARG001 - auth gate
) -> ReportOut:
    now = datetime.now(UTC)
    today = now.date()
    retention, _ = _retention(db)
    window = min(_clamp_days(days), retention)
    start_day = today - timedelta(days=window - 1)
    day_keys = [start_day + timedelta(days=i) for i in range(window)]

    # Scheduled jobs only. Dates are compared in Python: the tests run on
    # SQLite (which stores naive timestamps) while production is Postgres
    # timestamptz, and a SQL-side comparison would disagree between the two.
    jobs = (
        db.query(Job)
        .filter(Job.created_by.like("schedule:%"))
        .order_by(Job.created_at)
        .all()
    )
    # Keep the full scheduled history in memory: a 7-day view still needs the
    # same weekday last week for its comparison, and that day is outside the
    # window. Alert grouping below trims to the visible window.

    schedules = db.query(Schedule).order_by(Schedule.name).all()
    schedule_by_id = {schedule.id: schedule for schedule in schedules}
    sources = {
        target.id: (f"{target.name} · {target.region_code}")
        for target in db.query(IndexTarget).all()
    }

    jobs_by_schedule: dict[int, list[Job]] = defaultdict(list)
    orphan_jobs: list[Job] = []
    for job in jobs:
        owner = job.created_by or ""
        try:
            schedule_id = int(owner.split(":", 1)[1])
        except (IndexError, ValueError):
            continue
        if schedule_id in schedule_by_id:
            jobs_by_schedule[schedule_id].append(job)
        else:
            orphan_jobs.append(job)

    schedule_reports: list[ReportScheduleOut] = []
    for schedule in schedules:
        sched_jobs = jobs_by_schedule.get(schedule.id, [])
        schedule_reports.append(
            _build_schedule(
                schedule_id=schedule.id,
                name=schedule.name,
                customer=_schedule_customer(schedule, sched_jobs),
                enabled=bool(schedule.enabled),
                interval_seconds=schedule.interval_seconds,
                calendar_day=bool(schedule.calendar_day),
                source=_schedule_source(schedule, sched_jobs, sources),
                schedule=schedule,
                schedule_last_run_at=schedule.last_run_at,
                jobs=sched_jobs,
                day_keys=day_keys,
                today=today,
            )
        )

    # Runs whose schedule was deleted still deserve a row - otherwise a silent
    # failure disappears with the schedule.
    orphan_groups: dict[tuple[str, str], list[Job]] = defaultdict(list)
    for job in orphan_jobs:
        day = _utc_date(job.created_at)
        # A deleted schedule only belongs in the visible window; an old orphan
        # row would otherwise add a customer with a permanent row of zeros.
        if day is None or day < start_day:
            continue
        orphan_groups[(_job_customer(job), _job_name(job))].append(job)
    for (customer, name), group in orphan_groups.items():
        schedule_reports.append(
            _build_schedule(
                schedule_id=None,
                name=name,
                customer=customer,
                enabled=False,
                interval_seconds=None,
                calendar_day=False,
                source=_schedule_source(None, group, sources),
                schedule=None,
                schedule_last_run_at=None,
                jobs=group,
                day_keys=day_keys,
                today=today,
            )
        )

    customers: dict[str, list[ReportScheduleOut]] = defaultdict(list)
    for report in schedule_reports:
        customers[report.customer].append(report)

    customer_out: list[ReportCustomerOut] = []
    for customer, rows in customers.items():
        rows.sort(key=lambda r: r.name.lower())
        rows_today = sum(r.today_rows for r in rows)
        rows_yesterday = sum(r.yesterday_rows for r in rows)
        rows_last_week = sum(r.last_week_rows for r in rows)
        customer_out.append(
            ReportCustomerOut(
                customer=customer,
                schedules=rows,
                rows_today=rows_today,
                rows_yesterday=rows_yesterday,
                rows_last_week=rows_last_week,
                pct_vs_yesterday=_pct(rows_today, rows_yesterday),
                pct_vs_last_week=_pct(rows_today, rows_last_week),
                failed_today=sum(r.failed_today for r in rows),
            )
        )
    # Failures first, then the biggest customers; deterministic and useful.
    customer_out.sort(key=lambda c: (-c.failed_today, c.customer.lower()))

    today_jobs = [job for job in jobs if _utc_date(job.created_at) == today]
    completed_today = sum(1 for job in today_jobs if job.status == "completed")
    failed_today = sum(1 for job in today_jobs if job.status == "failed")
    active_today = sum(1 for job in today_jobs if job.status in ACTIVE_STATUSES)
    rows_today = sum(int(job.rows_written or 0) for job in today_jobs if job.status == "completed")
    rows_yesterday = sum(
        int(job.rows_written or 0)
        for job in jobs
        if job.status == "completed" and _utc_date(job.created_at) == today - timedelta(days=1)
    )
    rows_last_week = sum(
        int(job.rows_written or 0)
        for job in jobs
        if job.status == "completed" and _utc_date(job.created_at) == today - timedelta(days=7)
    )
    decided_today = completed_today + failed_today

    alerts: list[ReportAlertOut] = []
    failed_groups: dict[tuple[str, str, int | None], list[Job]] = defaultdict(list)
    for job in jobs:
        if job.status != "failed":
            continue
        day = _utc_date(job.created_at)
        if day is None or day < start_day:
            continue
        owner = job.created_by or ""
        try:
            schedule_id: int | None = int(owner.split(":", 1)[1])
        except (IndexError, ValueError):
            schedule_id = None
        if schedule_id not in schedule_by_id:
            schedule_id = None
        failed_groups[(_job_customer(job), _job_name(job), schedule_id)].append(job)

    for (customer, name, schedule_id), group in failed_groups.items():
        latest = _latest(group)
        schedule = schedule_by_id.get(schedule_id) if schedule_id is not None else None
        alerts.append(
            ReportAlertOut(
                kind="failed",
                customer=customer,
                job_name=name,
                schedule_id=schedule_id,
                job_id=latest.id if latest else None,
                at=_aware(latest.created_at if latest else None),
                error=(latest.error_message if latest else None) or "Scheduled run failed.",
                occurrences=len(group),
                recipients=list(schedule.alert_recipients or []) if schedule else [],
            )
        )

    # Enabled daily schedules that have produced nothing for 36 hours. This is
    # the failure the job list cannot show: no job was ever created.
    for schedule in schedules:
        if not schedule.enabled or not _expected_daily(schedule):
            continue
        created = _aware(schedule.created_at)
        if created is not None and now - created < timedelta(hours=MISSED_AFTER_HOURS):
            continue
        recent = any(
            (_aware(job.created_at) or datetime.min.replace(tzinfo=UTC))
            >= now - timedelta(hours=MISSED_AFTER_HOURS)
            for job in jobs_by_schedule.get(schedule.id, [])
        )
        if recent:
            continue
        sched_jobs = jobs_by_schedule.get(schedule.id, [])
        latest = _latest(sched_jobs)
        alerts.append(
            ReportAlertOut(
                kind="missed",
                customer=_schedule_customer(schedule, sched_jobs),
                job_name=schedule.name,
                schedule_id=schedule.id,
                job_id=None,
                at=_aware(schedule.last_run_at or (latest.created_at if latest else created)),
                error=f"No scheduled run in the last {MISSED_AFTER_HOURS} hours.",
                occurrences=1,
                recipients=list(schedule.alert_recipients or []),
            )
        )

    alerts.sort(
        key=lambda alert: (
            0 if alert.kind == "failed" else 1,
            -(alert.at.timestamp() if alert.at else 0),
        )
    )

    return ReportOut(
        generated_at=now,
        retention_days=retention,
        window_days=window,
        timezone="UTC",
        totals=ReportTotalsOut(
            customers=len(customer_out),
            # Configured schedules, not the pseudo-rows for runs whose
            # schedule was deleted.
            schedules=len(schedules),
            enabled_schedules=sum(1 for schedule in schedules if schedule.enabled),
            runs_today=len(today_jobs),
            completed_today=completed_today,
            failed_today=failed_today,
            active_today=active_today,
            rows_today=rows_today,
            rows_yesterday=rows_yesterday,
            rows_last_week=rows_last_week,
            pct_vs_yesterday=_pct(rows_today, rows_yesterday),
            pct_vs_last_week=_pct(rows_today, rows_last_week),
            success_rate_today=(
                round(completed_today * 100.0 / decided_today, 1) if decided_today else None
            ),
        ),
        customers=customer_out,
        alerts=alerts[:200],
    )
