"""Anomaly threshold rules and their notification payloads."""

from __future__ import annotations

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
