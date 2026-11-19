"""Anomaly threshold rules and their notification payloads."""

from __future__ import annotations

import pytest

from app import notifications
from app.schedule_alerts import evaluate_anomaly


def _evaluate(**overrides):
    values = {
        "current_rows": 8000,
        "previous_rows": 10000,
        "rows_matched": 9900,
        "rows_unmatched": 100,
        "alert_on_row_drop": True,
        "row_drop_threshold_pct": 20,
        "alert_on_unmatched": True,
        "unmatched_threshold": 100,
    }
    values.update(overrides)
    return evaluate_anomaly(**values)


def test_row_drop_threshold_is_inclusive():
    result = _evaluate(current_rows=8000)
    assert result.drop_pct == 20.0
    assert any("Rows written dropped" in reason for reason in result.reasons)

    result = _evaluate(current_rows=8001)
    assert result.drop_pct is not None and result.drop_pct < 20
    assert not any("Rows written dropped" in reason for reason in result.reasons)


def test_row_drop_skips_missing_or_zero_baseline():
    # The unmatched rule may still fire; this asserts only the row-drop rule.
    assert not any(
        "Rows written dropped" in reason for reason in _evaluate(previous_rows=None).reasons
    )
    assert not any(
        "Rows written dropped" in reason for reason in _evaluate(previous_rows=0).reasons
    )


def test_zero_current_rows_reports_full_drop():
    result = _evaluate(current_rows=0, alert_on_unmatched=False)
    assert result.drop_pct == 100.0
    assert any("100.0%" in reason for reason in result.reasons)


def test_unmatched_threshold_is_inclusive():
    result = _evaluate(rows_matched=9900, rows_unmatched=100)
    assert any("unmatched" in reason for reason in result.reasons)

    result = _evaluate(rows_matched=9901, rows_unmatched=99)
    assert not any("unmatched" in reason for reason in result.reasons)


def test_alerts_are_opt_in():
    result = evaluate_anomaly(
        current_rows=1,
        previous_rows=10000,
        rows_matched=0,
        rows_unmatched=10000,
        alert_on_row_drop=False,
        row_drop_threshold_pct=20,
        alert_on_unmatched=False,
        unmatched_threshold=1,
    )
    assert result.reasons == []
    # The numbers remain available for an email that is triggered by another rule.
    assert result.drop_pct is not None


def test_unmatched_share_uses_parsed_rows():
    result = _evaluate(rows_matched=9900, rows_unmatched=100)
    assert result.parsed_rows == 10000
    assert result.unmatched_pct == 1.0


def test_send_anomaly_alert_uses_email_and_slack(monkeypatch):
    sent: dict = {}
    monkeypatch.setattr(
        notifications,
        "load_config",
        lambda: {
            "smtp_host": "smtp.example.com",
            "smtp_user": "u",
            "smtp_password": "p",
            "smtp_port": "587",
            "smtp_from": "alerts@example.com",
            "slack_webhook_url": "https://hooks.example/x",
        },
    )
    monkeypatch.setattr(
        notifications,
        "_send_plain_email",
        lambda cfg, recipients, subject, body: sent.update(
            email=(recipients, subject, body)
        ),
    )
    monkeypatch.setattr(
        notifications,
        "_send_slack_text",
        lambda webhook, subject, body: sent.update(slack=(webhook, subject, body)),
    )

    notifications.send_anomaly_alert(
        ["ops@example.com"],
        "Daily_aha",
        42,
        "ACME",
        reasons=["Rows written dropped 20.0% versus the previous completed run"],
        current_rows=8000,
        previous_rows=10000,
        drop_pct=20.0,
        rows_unmatched=100,
        parsed_rows=9100,
        unmatched_pct=1.0989,
        row_drop_threshold_pct=20,
        unmatched_threshold=100,
    )

    assert sent["email"][0] == ["ops@example.com"]
    assert "[ACME]" in sent["email"][1]
    assert "Rows written dropped" in sent["email"][2]
    assert sent["slack"][0] == "https://hooks.example/x"


def test_send_failure_alert_accepts_customer(monkeypatch):
    sent: dict = {}
    monkeypatch.setattr(
        notifications,
        "load_config",
        lambda: {
            "smtp_host": "smtp.example.com",
            "smtp_user": "u",
            "smtp_password": "p",
            "smtp_port": "587",
            "smtp_from": "alerts@example.com",
            "slack_webhook_url": "",
        },
    )
    monkeypatch.setattr(
        notifications,
        "_send_email",
        lambda cfg, recipients, schedule_name, job_id, error_message, customer="": sent.update(
            customer=customer
        ),
    )

    notifications.send_failure_alert(["ops@example.com"], "Daily_aha", 7, "boom", "ACME")
    assert sent["customer"] == "ACME"


def test_completion_hook_sends_once(worker_db, monkeypatch):
    from app import tasks

    sent: list[dict] = []
    monkeypatch.setattr(
        "app.notifications.send_anomaly_alert",
        lambda **kwargs: sent.append(kwargs),
    )

    with worker_db.engine().begin() as conn:
        conn.execute(
            worker_db.schedules.insert().values(
                id=1,
                name="Daily_aha",
                alert_recipients=["ops@example.com"],
                alert_on_row_drop=True,
                row_drop_threshold_pct=20,
                alert_on_unmatched=True,
                unmatched_threshold=100,
                filter_spec={"customer": "ACME"},
            )
        )
        conn.execute(
            worker_db.jobs.insert().values(
                id=100,
                status="completed",
                region_code="ap-south-1",
                index_target_id=1,
                credential_id=1,
                start_epoch=100,
                end_epoch=200,
                created_by="schedule:1",
                rows_written=10000,
            )
        )
        conn.execute(
            worker_db.jobs.insert().values(
                id=200,
                status="completed",
                region_code="ap-south-1",
                index_target_id=1,
                credential_id=1,
                start_epoch=200,
                end_epoch=300,
                created_by="schedule:1",
                rows_written=8000,
                aggregation_result={"rows_matched": 7900, "rows_unmatched": 100},
            )
        )

    tasks._send_schedule_anomaly_if_needed(200)

    assert len(sent) == 1
    assert sent[0]["recipients"] == ["ops@example.com"]
    assert sent[0]["customer"] == "ACME"
    assert any("Rows written dropped" in reason for reason in sent[0]["reasons"])
    assert any("unmatched" in reason for reason in sent[0]["reasons"])

    with worker_db.engine().connect() as conn:
        events = (
            conn.execute(
                worker_db.job_events.select().where(worker_db.job_events.c.job_id == 200)
            )
            .mappings()
            .all()
        )
    assert any("Anomaly detected" in event["message"] for event in events)

    # A Celery redelivery must not page the team twice.
    tasks._send_schedule_anomaly_if_needed(200)
    assert len(sent) == 1


def test_slack_text_raises_on_a_rejected_webhook(monkeypatch):
    """A 404 from Slack must raise, not look like a delivered alert.

    `raise_for_status` was missing, so a revoked or mistyped webhook reported
    "sent" and the caller counted the channel as ok. That is how an alert path
    can be "working" while nobody receives anything.
    """
    import httpx

    def _reject(url, **kwargs):
        return httpx.Response(404, text="no_service", request=httpx.Request("POST", url))

    monkeypatch.setattr(notifications.httpx, "post", _reject)
    with pytest.raises(httpx.HTTPStatusError):
        notifications._send_slack_text("https://hooks.slack.com/x", "subject", "body")


def test_send_anomaly_alert_reports_each_channel(monkeypatch):
    """The sender must say what happened per channel, like send_health_alert."""
    monkeypatch.setattr(
        notifications,
        "load_config",
        lambda: {
            "smtp_host": "smtp.example.com",
            "smtp_password": "pw",
            "smtp_user": "u",
            "smtp_from": "alerts@example.com",
            "slack_webhook_url": "https://hooks.slack.com/x",
        },
    )
    monkeypatch.setattr(notifications, "_send_plain_email", lambda *a, **k: None)
    monkeypatch.setattr(notifications, "_send_slack_text", lambda *a, **k: None)

    result = notifications.send_anomaly_alert(
        ["ops@example.com"],
        "Daily",
        7,
        "ACME",
        reasons=["Rows written dropped 25.0%"],
        current_rows=7500,
        previous_rows=10000,
        drop_pct=25.0,
        rows_unmatched=0,
        parsed_rows=7500,
        unmatched_pct=0.0,
        row_drop_threshold_pct=20,
        unmatched_threshold=100,
    )

    assert result["email"] == {"attempted": True, "ok": True, "reason": "sent"}
    assert result["slack"] == {"attempted": True, "ok": True, "reason": "sent"}


def test_send_anomaly_alert_reports_a_failed_channel(monkeypatch):
    """A channel that raises is reported as failed, not swallowed."""
    monkeypatch.setattr(
        notifications,
        "load_config",
        lambda: {
            "smtp_host": "smtp.example.com",
            "smtp_password": "pw",
            "smtp_user": "u",
            "smtp_from": "alerts@example.com",
            "slack_webhook_url": "",
        },
    )

    def _boom(*a, **k):
        raise OSError("smtp refused")

    monkeypatch.setattr(notifications, "_send_plain_email", _boom)
    monkeypatch.setattr(notifications, "_retry", lambda fn: fn())

    result = notifications.send_anomaly_alert(
        ["ops@example.com"],
        "Daily",
        7,
        "ACME",
        reasons=["Rows written dropped 25.0%"],
        current_rows=7500,
        previous_rows=10000,
        drop_pct=25.0,
        rows_unmatched=0,
        parsed_rows=7500,
        unmatched_pct=0.0,
        row_drop_threshold_pct=20,
        unmatched_threshold=100,
    )

    assert result["email"]["attempted"] is True
    assert result["email"]["ok"] is False
    assert "smtp refused" in result["email"]["reason"]
    assert result["slack"]["attempted"] is False


def test_partial_run_does_not_alert_on_row_drop(worker_db, monkeypatch):
    """A short run is already reported as partial; it must not also page as a drop."""
    from app import tasks

    sent: list[dict] = []
    monkeypatch.setattr("app.notifications.send_anomaly_alert", lambda **kw: sent.append(kw))

    with worker_db.engine().begin() as conn:
        conn.execute(
            worker_db.schedules.insert().values(
                id=1,
                name="Daily",
                alert_recipients=["ops@example.com"],
                alert_on_row_drop=True,
                row_drop_threshold_pct=20,
                alert_on_unmatched=False,
                unmatched_threshold=100,
                filter_spec={},
            )
        )
        conn.execute(
            worker_db.jobs.insert().values(
                id=100,
                status="completed",
                region_code="ap-south-1",
                index_target_id=1,
                credential_id=1,
                start_epoch=100,
                end_epoch=200,
                created_by="schedule:1",
                rows_written=10000,
                completion_state="complete",
            )
        )
        conn.execute(
            worker_db.jobs.insert().values(
                id=200,
                status="completed",
                region_code="ap-south-1",
                index_target_id=1,
                credential_id=1,
                start_epoch=200,
                end_epoch=300,
                created_by="schedule:1",
                rows_written=5000,
                completion_state="partial",
            )
        )

    tasks._send_schedule_anomaly_if_needed(200)
    assert sent == [], "a partial run must not be reported as a row-count drop"


def test_partial_run_is_not_used_as_a_baseline(worker_db, monkeypatch):
    """A partial run's row count is short, so it must not be the comparison point."""
    from app import tasks

    sent: list[dict] = []
    monkeypatch.setattr("app.notifications.send_anomaly_alert", lambda **kw: sent.append(kw))

    with worker_db.engine().begin() as conn:
        conn.execute(
            worker_db.schedules.insert().values(
                id=1,
                name="Daily",
                alert_recipients=["ops@example.com"],
                alert_on_row_drop=True,
                row_drop_threshold_pct=20,
                alert_on_unmatched=False,
                unmatched_threshold=100,
                filter_spec={},
            )
        )
        conn.execute(
            worker_db.jobs.insert().values(
                id=50,
                status="completed",
                region_code="ap-south-1",
                index_target_id=1,
                credential_id=1,
                start_epoch=50,
                end_epoch=100,
                created_by="schedule:1",
                rows_written=4000,
                completion_state="complete",
            )
        )
        conn.execute(
            worker_db.jobs.insert().values(
                id=100,
                status="completed",
                region_code="ap-south-1",
                index_target_id=1,
                credential_id=1,
                start_epoch=100,
                end_epoch=200,
                created_by="schedule:1",
                rows_written=10000,
                completion_state="partial",
            )
        )
        conn.execute(
            worker_db.jobs.insert().values(
                id=200,
                status="completed",
                region_code="ap-south-1",
                index_target_id=1,
                credential_id=1,
                start_epoch=200,
                end_epoch=300,
                created_by="schedule:1",
                rows_written=4000,
                completion_state="complete",
            )
        )

    tasks._send_schedule_anomaly_if_needed(200)
    # 4000 vs the complete 4000 is flat; 4000 vs the partial 10000 would be a 60% drop.
    assert sent == [], "the partial run must be skipped when choosing the baseline"


def test_failed_delivery_is_recorded_as_an_event(worker_db, monkeypatch):
    """A send that reached no channel must leave a visible trail."""
    from app import tasks

    monkeypatch.setattr(
        "app.notifications.send_anomaly_alert",
        lambda **kw: {
            "email": {"attempted": True, "ok": False, "reason": "smtp refused"},
            "slack": {"attempted": False, "ok": False, "reason": "no webhook"},
        },
    )

    with worker_db.engine().begin() as conn:
        conn.execute(
            worker_db.schedules.insert().values(
                id=1,
                name="Daily",
                alert_recipients=["ops@example.com"],
                alert_on_row_drop=True,
                row_drop_threshold_pct=20,
                alert_on_unmatched=False,
                unmatched_threshold=100,
                filter_spec={},
            )
        )
        conn.execute(
            worker_db.jobs.insert().values(
                id=100,
                status="completed",
                region_code="ap-south-1",
                index_target_id=1,
                credential_id=1,
                start_epoch=100,
                end_epoch=200,
                created_by="schedule:1",
                rows_written=10000,
                completion_state="complete",
            )
        )
        conn.execute(
            worker_db.jobs.insert().values(
                id=200,
                status="completed",
                region_code="ap-south-1",
                index_target_id=1,
                credential_id=1,
                start_epoch=200,
                end_epoch=300,
                created_by="schedule:1",
                rows_written=7000,
                completion_state="complete",
            )
        )

    tasks._send_schedule_anomaly_if_needed(200)

    with worker_db.engine().connect() as conn:
        messages = [
            row["message"]
            for row in conn.execute(
                worker_db.job_events.select().where(worker_db.job_events.c.job_id == 200)
            ).mappings()
        ]
    assert any("Anomaly detected" in message for message in messages)
    assert any("not delivered" in message for message in messages)


def test_duplicate_anomaly_marker_is_dropped_without_sending(worker_db, monkeypatch):
    """Two deliveries can both pass the SELECT before either INSERTs.

    Alembic 0036 and the worker's table mirror put a partial unique index on
    ``(job_id) WHERE message LIKE 'Anomaly detected%'``. The loser's INSERT
    raises IntegrityError and that delivery must return without sending, so the
    team is paged once instead of twice.

    A true cross-connection race is not reproducible on the in-memory SQLite
    fixture (one connection per thread), so the competing marker is inserted
    inside the same savepoint just before ours: the index still rejects the
    second row and the same handler runs.
    """
    from app import db as db_mod
    from app import tasks

    sent: list[dict] = []
    monkeypatch.setattr("app.notifications.send_anomaly_alert", lambda **kw: sent.append(kw))

    with worker_db.engine().begin() as conn:
        conn.execute(
            worker_db.schedules.insert().values(
                id=1,
                name="Daily_aha",
                alert_recipients=["ops@example.com"],
                alert_on_row_drop=True,
                row_drop_threshold_pct=20,
                alert_on_unmatched=False,
                unmatched_threshold=100,
                filter_spec={},
            )
        )
        for job_id, start, rows in ((100, 100, 10000), (200, 200, 7000)):
            conn.execute(
                worker_db.jobs.insert().values(
                    id=job_id,
                    status="completed",
                    region_code="ap-south-1",
                    index_target_id=1,
                    credential_id=1,
                    start_epoch=start,
                    end_epoch=start + 100,
                    created_by="schedule:1",
                    rows_written=rows,
                    completion_state="complete",
                )
            )

    real_add_event = db_mod.add_event

    def racing_add_event(conn, job_id, message, *args, **kwargs):
        # The other delivery's marker is already in the table when ours runs.
        real_add_event(conn, job_id, "Anomaly detected: rows dropped")
        return real_add_event(conn, job_id, message, *args, **kwargs)

    monkeypatch.setattr(db_mod, "add_event", racing_add_event)

    tasks._send_schedule_anomaly_if_needed(200)

    assert sent == [], "the duplicate delivery must not send a second alert"
