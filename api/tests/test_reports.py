"""Customer-wise scheduled-run reports."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from app.models import Job, Schedule


def _at(days_ago: int, hour: int = 1) -> datetime:
    today = datetime.now(UTC).date()
    return datetime.combine(today - timedelta(days=days_ago), time(hour), tzinfo=UTC)


def _schedule(
    *,
    id: int,
    name: str,
    customer: str,
    enabled: bool = True,
    interval_seconds: int = 86400,
    calendar_day: bool = True,
    recipients: list[str] | None = None,
    created_at: datetime | None = None,
    last_run_at: datetime | None = None,
) -> Schedule:
    return Schedule(
        id=id,
        name=name,
        enabled=enabled,
        interval_seconds=interval_seconds,
        lookback_seconds=86400,
        calendar_day=calendar_day,
        region_code="ap-southeast-1",
        index_target_id=1,
        credential_id=1,
        chunk_hours=1,
        id_batch_size=100,
        output_format="csv",
        filter_spec={"customer": customer},
        alert_recipients=recipients or [],
        created_at=created_at or _at(10),
        last_run_at=last_run_at,
    )


def _job(
    *,
    id: int,
    schedule_id: int | None,
    name: str,
    customer: str,
    status: str,
    rows: int,
    created_at: datetime,
    error: str | None = None,
) -> Job:
    return Job(
        id=id,
        status=status,
        region_code="ap-southeast-1",
        index_target_id=1,
        credential_id=1,
        start_epoch=int(created_at.timestamp()) - 3600,
        end_epoch=int(created_at.timestamp()),
        filter_spec={"label": name, "customer": customer},
        rows_written=rows,
        error_message=error,
        is_preview=False,
        created_by=f"schedule:{schedule_id}" if schedule_id is not None else "manual@example.com",
        created_at=created_at,
    )


def _seed(client) -> None:
    with client.session_factory() as db:
        db.add_all(
            [
                _schedule(id=1, name="Daily A", customer="ACME", recipients=["ops@acme.test"]),
                _schedule(id=2, name="Daily B", customer="BETA"),
                _schedule(id=3, name="Off C", customer="GAMMA", enabled=False),
            ]
        )
        db.add_all(
            [
                _job(
                    id=1,
                    schedule_id=1,
                    name="Daily A",
                    customer="ACME",
                    status="completed",
                    rows=100,
                    created_at=_at(0, 2),
                ),
                _job(
                    id=2,
                    schedule_id=1,
                    name="Daily A",
                    customer="ACME",
                    status="failed",
                    rows=0,
                    created_at=_at(0, 3),
                    error="Last9 502",
                ),
                _job(
                    id=3,
                    schedule_id=1,
                    name="Daily A",
                    customer="ACME",
                    status="completed",
                    rows=80,
                    created_at=_at(1, 2),
                ),
                _job(
                    id=4,
                    schedule_id=1,
                    name="Daily A",
                    customer="ACME",
                    status="completed",
                    rows=50,
                    created_at=_at(7, 2),
                ),
                _job(
                    id=5,
                    schedule_id=2,
                    name="Daily B",
                    customer="BETA",
                    status="completed",
                    rows=10,
                    created_at=_at(0, 4),
                ),
                _job(
                    id=6,
                    schedule_id=2,
                    name="Daily B",
                    customer="BETA",
                    status="completed",
                    rows=20,
                    created_at=_at(1, 4),
                ),
                # A run whose schedule was deleted still has to be visible.
                _job(
                    id=7,
                    schedule_id=999,
                    name="Removed job",
                    customer="ZETA",
                    status="failed",
                    rows=0,
                    created_at=_at(0, 5),
                    error="schedule deleted",
                ),
            ]
        )
        db.commit()


def test_report_totals_comparisons_and_status(client):
    _seed(client)
    response = client.get("/reports?days=14")
    assert response.status_code == 200, response.text
    body = response.json()

    totals = body["totals"]
    assert totals["rows_today"] == 110  # A 100 + B 10, failed runs add nothing
    assert totals["rows_yesterday"] == 100  # A 80 + B 20
    assert totals["rows_last_week"] == 50  # A 50 (B has none)
    assert totals["pct_vs_yesterday"] == 10.0
    assert totals["pct_vs_last_week"] == 120.0
    assert totals["completed_today"] == 2
    assert totals["failed_today"] == 1
    assert totals["runs_today"] == 3
    assert totals["success_rate_today"] == 66.7
    assert totals["schedules"] == 3
    assert totals["enabled_schedules"] == 2

    by_customer = {c["customer"]: c for c in body["customers"]}
    assert set(by_customer) == {"ACME", "BETA", "GAMMA"}
    assert "ZETA" not in by_customer

    acme = by_customer["ACME"]["schedules"][0]
    assert acme["today_rows"] == 100
    assert acme["yesterday_rows"] == 80
    assert acme["last_week_rows"] == 50
    assert acme["pct_vs_yesterday"] == 25.0
    assert acme["pct_vs_last_week"] == 100.0
    assert acme["today_status"] == "failed"  # a failed run marks the day
    assert acme["failed_today"] == 1
    days = {d["date"]: d for d in acme["days"]}
    assert days[datetime.now(UTC).date().isoformat()]["status"] == "failed"
    # Enabled daily schedule, no run: yesterday - 1 is missed.
    two_days_ago = (datetime.now(UTC).date() - timedelta(days=2)).isoformat()
    assert days[two_days_ago]["status"] == "missed"

    beta = by_customer["BETA"]["schedules"][0]
    assert beta["pct_vs_yesterday"] == -50.0
    assert beta["pct_vs_last_week"] is None  # no baseline, never infinity

    gamma = by_customer["GAMMA"]["schedules"][0]
    assert gamma["enabled"] is False
    assert all(d["status"] == "off" for d in gamma["days"])

    # A 7-day window still has to show the same-weekday comparison, even though
    # that day sits just outside the visible strip.
    short = client.get("/reports?days=7").json()
    assert short["window_days"] == 7
    assert short["totals"]["rows_last_week"] == 50
    assert short["totals"]["pct_vs_last_week"] == 120.0
    short_acme = next(c for c in short["customers"] if c["customer"] == "ACME")["schedules"][0]
    assert short_acme["last_week_rows"] == 50
    assert short_acme["pct_vs_last_week"] == 100.0


def test_failed_alerts_include_customer_job_and_recipients(client):
    _seed(client)
    body = client.get("/reports?days=14").json()
    failed = [a for a in body["alerts"] if a["kind"] == "failed"]
    assert {(a["customer"], a["job_name"]) for a in failed} == {("ACME", "Daily A")}
    acme = next(a for a in failed if a["customer"] == "ACME")
    assert acme["occurrences"] == 1
    assert acme["error"] == "Last9 502"
    assert acme["recipients"] == ["ops@acme.test"]
    assert acme["job_id"] == 2
    assert acme["schedule_id"] == 1


def test_missed_alert_for_silent_daily_schedule(client):
    with client.session_factory() as db:
        db.add(
            _schedule(
                id=10,
                name="Silent daily",
                customer="SILENT",
                created_at=_at(4),
                last_run_at=_at(4),
            )
        )
        db.commit()

    body = client.get("/reports?days=7").json()
    missed = [a for a in body["alerts"] if a["kind"] == "missed"]
    assert any(a["customer"] == "SILENT" and a["job_name"] == "Silent daily" for a in missed)
    row = body["customers"][0]["schedules"][0]
    assert row["today_status"] == "pending"
    past = [d for d in row["days"] if d["date"] != datetime.now(UTC).date().isoformat()]
    assert any(d["status"] == "missed" for d in past)


def test_weekly_schedule_is_not_reported_as_missed(client):
    with client.session_factory() as db:
        db.add(
            _schedule(
                id=11,
                name="Weekly",
                customer="WEEKLY",
                interval_seconds=7 * 86400,
                calendar_day=False,
                created_at=_at(20),
                last_run_at=_at(10),
            )
        )
        db.commit()

    body = client.get("/reports?days=7").json()
    assert all(a["job_name"] != "Weekly" for a in body["alerts"])
    row = body["customers"][0]["schedules"][0]
    assert all(d["status"] == "none" for d in row["days"])


def test_report_settings_default_retention_and_clamp(client):
    assert client.get("/reports/settings").json()["retention_days"] == 90

    updated = client.put("/reports/settings", json={"retention_days": 7})
    assert updated.status_code == 200, updated.text
    assert updated.json()["retention_days"] == 7

    # A wider request cannot exceed the configured retention.
    body = client.get("/reports?days=30").json()
    assert body["retention_days"] == 7
    assert body["window_days"] == 7
    assert len(body["customers"]) == 0


def test_report_settings_requires_admin(member_client):
    assert member_client.put("/reports/settings", json={"retention_days": 30}).status_code == 403
    assert member_client.get("/reports/settings").status_code == 200


def test_report_excludes_manual_jobs(client):
    with client.session_factory() as db:
        db.add(
            _job(
                id=20,
                schedule_id=None,
                name="Manual",
                customer="MANUAL",
                status="completed",
                rows=999,
                created_at=_at(0, 1),
            )
        )
        db.commit()

    body = client.get("/reports?days=7").json()
    assert body["totals"]["rows_today"] == 0
    assert body["customers"] == []


def test_deleting_schedule_removes_its_report_but_keeps_jobs(client):
    with client.session_factory() as db:
        db.add(_schedule(id=30, name="Delete me", customer="DELETE"))
        db.add(
            _job(
                id=3000,
                schedule_id=30,
                name="Delete me",
                customer="DELETE",
                status="completed",
                rows=10,
                created_at=_at(0, 1),
            )
        )
        db.commit()

    before = client.get("/reports?days=7").json()
    assert any(c["customer"] == "DELETE" for c in before["customers"])

    assert client.delete("/schedules/30").status_code == 204

    after = client.get("/reports?days=7").json()
    assert all(c["customer"] != "DELETE" for c in after["customers"])
    assert all(a["customer"] != "DELETE" for a in after["alerts"])
    # The schedule is gone, but the job history and its files are not.
    with client.session_factory() as db:
        assert db.get(Job, 3000) is not None
