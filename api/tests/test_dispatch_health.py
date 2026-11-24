"""Alert-contract tests for dispatch metrics. Pure thresholds, no database."""

from app.dispatch_health import ALERTS, THRESHOLDS, evaluate


def test_healthy_system_reports_ok():
    result = evaluate({})
    assert result["status"] == "ok"
    assert all(c["state"] == "ok" for c in result["checks"].values())


def test_oldest_pending_crosses_warn_then_critical():
    warn, critical = THRESHOLDS["outbox_oldest_pending_age_s"]
    assert evaluate({"outbox_oldest_pending_age_s": warn})["status"] == "warn"
    result = evaluate({"outbox_oldest_pending_age_s": critical})
    assert result["status"] == "critical"
    assert result["checks"]["outbox_oldest_pending_age_s"]["state"] == "critical"


def test_dead_letter_is_at_least_warning():
    assert evaluate({"outbox_dead": 1})["status"] in {"warn", "critical"}
    assert evaluate({"outbox_dead": 100})["status"] == "critical"


def test_expired_lease_escalates():
    assert evaluate({"leases_expired": 1})["status"] in {"warn", "critical"}
    assert evaluate({"leases_expired": 999})["status"] == "critical"


def test_any_critical_dominates():
    result = evaluate({"outbox_dead": 0, "leases_expired": 999, "partial_jobs_24h": 1})
    assert result["status"] == "critical"


def test_unknown_metric_ignored():
    result = evaluate({"not_a_metric": 10_000})
    assert result["status"] == "ok"


def test_every_threshold_has_an_actionable_alert():
    for key in THRESHOLDS:
        assert key in ALERTS
        assert len(ALERTS[key]) > 20
        warn, critical = THRESHOLDS[key]
        assert critical >= warn
