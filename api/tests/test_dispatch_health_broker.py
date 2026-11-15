"""Broker telemetry: unavailable must never look like healthy, or like zero."""

from datetime import UTC, datetime, timedelta

from app.dispatch_health import collect_broker, evaluate_broker, heartbeat_age, parse_heartbeat


class FakeRedis:
    def __init__(self, depth=0, lock_ttl=-2, heartbeat=None, fail=False):
        self.depth = depth
        self.lock_ttl = lock_ttl
        self.heartbeat = heartbeat
        self.fail = fail

    def llen(self, key):
        if self.fail:
            raise ConnectionError("down")
        return self.depth

    def ttl(self, key):
        if self.fail:
            raise ConnectionError("down")
        return self.lock_ttl

    def get(self, key):
        if self.fail:
            raise ConnectionError("down")
        return self.heartbeat


def test_healthy_broker():
    m = {"celery_queue_depth": 0, "beat_lock_present": 1, "beat_lock_ttl_s": 80,
         "beat_heartbeat_age_s": 5, "worker_online": 1}
    result = evaluate_broker(m)
    assert result["status"] == "ok"
    assert result["checks"]["beat_lock"]["state"] == "ok"


def test_queue_depth_thresholds():
    assert evaluate_broker({"celery_queue_depth": 100})["checks"]["celery_queue_depth"]["state"] == "warn"
    assert evaluate_broker({"celery_queue_depth": 5000})["status"] == "critical"


def test_missing_beat_lock_is_critical():
    result = evaluate_broker({"beat_lock_present": 0})
    assert result["status"] == "critical"
    assert result["checks"]["beat_lock"]["state"] == "critical"


def test_short_beat_lock_ttl_warns():
    result = evaluate_broker({"beat_lock_present": 1, "beat_lock_ttl_s": 10})
    assert result["checks"]["beat_lock"]["state"] == "warn"


def test_no_workers_is_critical():
    assert evaluate_broker({"worker_online": 0})["status"] == "critical"


def test_unavailable_telemetry_is_unknown_not_zero():
    result = evaluate_broker({"celery_queue_depth": None, "beat_lock_present": None,
                              "worker_online": None})
    assert result["status"] == "unknown"
    assert result["checks"]["celery_queue_depth"]["value"] is None


def test_collect_broker_survives_redis_failure():
    metrics = collect_broker(FakeRedis(fail=True))
    assert metrics["celery_queue_depth"] is None
    assert metrics["beat_lock_present"] is None
    assert evaluate_broker(metrics)["status"] == "unknown"


def test_collect_broker_reads_values():
    metrics = collect_broker(FakeRedis(depth=7, lock_ttl=42, heartbeat=None))
    assert metrics["celery_queue_depth"] == 7
    assert metrics["beat_lock_present"] == 1
    assert metrics["beat_lock_ttl_s"] == 42


# --- the defect these tests exist for: lock read from the wrong Redis DB ---


def test_lock_is_read_from_the_broker_database_not_the_telemetry_database():
    """Beat holds the lock in the broker DB; the telemetry DB has no such key."""
    telemetry = FakeRedis(lock_ttl=-2)          # REDIS_URL db, no lock
    broker = FakeRedis(lock_ttl=80)             # CELERY_BROKER_URL db, lock held
    metrics = collect_broker(telemetry, broker)
    assert metrics["beat_lock_present"] == 1
    assert metrics["beat_lock_ttl_s"] == 80
    assert evaluate_broker(metrics)["checks"]["beat_lock"]["state"] == "ok"


def test_lock_present_only_in_telemetry_database_is_not_trusted():
    telemetry = FakeRedis(lock_ttl=80)          # wrong database holding a key
    broker = FakeRedis(lock_ttl=-2)             # real broker DB: no lock
    metrics = collect_broker(telemetry, broker)
    assert metrics["beat_lock_present"] == 0
    assert evaluate_broker(metrics)["status"] == "critical"


def test_queue_depth_comes_from_the_broker_database():
    telemetry = FakeRedis(depth=0)
    broker = FakeRedis(depth=250)
    metrics = collect_broker(telemetry, broker)
    assert metrics["celery_queue_depth"] == 250
    assert evaluate_broker(metrics)["checks"]["celery_queue_depth"]["state"] == "warn"


def test_short_ttl_is_warning_not_ok():
    metrics = collect_broker(FakeRedis(), FakeRedis(lock_ttl=12))
    result = evaluate_broker(metrics)
    assert result["checks"]["beat_lock"]["state"] == "warn"
    assert result["status"] in {"warn", "unknown"}


def test_broker_unavailable_while_telemetry_works():
    telemetry = FakeRedis(heartbeat=None)
    broker = FakeRedis(fail=True)
    metrics = collect_broker(telemetry, broker)
    assert metrics["beat_lock_present"] is None
    assert metrics["celery_queue_depth"] is None


# --- heartbeat parsing: the writer emits ISO-8601, not epoch seconds ---


def _iso(delta_seconds: int, tz=UTC) -> str:
    return (datetime.now(tz) - timedelta(seconds=delta_seconds)).isoformat()


def test_fresh_utc_heartbeat_is_ok():
    metrics = collect_broker(FakeRedis(heartbeat=_iso(2)), FakeRedis(lock_ttl=80))
    result = evaluate_broker(metrics)
    assert metrics["beat_heartbeat_age_s"] < 10
    assert result["checks"]["beat_heartbeat_age_s"]["state"] == "ok"


def test_stale_heartbeat_warns_then_goes_critical():
    warn = collect_broker(FakeRedis(heartbeat=_iso(150)), FakeRedis(lock_ttl=80))
    assert evaluate_broker(warn)["checks"]["beat_heartbeat_age_s"]["state"] == "warn"
    critical = collect_broker(FakeRedis(heartbeat=_iso(400)), FakeRedis(lock_ttl=80))
    assert evaluate_broker(critical)["status"] == "critical"


def test_z_suffix_and_offsets_are_parsed_in_utc():
    from datetime import timezone

    now = datetime.now(UTC)
    z = (now - timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    plus = (now.astimezone(timezone(timedelta(hours=5, minutes=30)))
            - timedelta(seconds=30)).isoformat()
    minus = (now.astimezone(timezone(timedelta(hours=-8)))
             - timedelta(seconds=30)).isoformat()
    for raw in (z, plus, minus):
        age = heartbeat_age(raw)
        assert age is not None and 25 <= age <= 40, (raw, age)


def test_missing_and_malformed_heartbeat_are_unknown():
    assert heartbeat_age(None) is None
    assert heartbeat_age("") is None
    assert heartbeat_age("not-a-date") is None
    assert heartbeat_age("1234567890") is None


def test_future_timestamp_is_not_healthy():
    future = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
    assert heartbeat_age(future) is None
    metrics = collect_broker(FakeRedis(heartbeat=future), FakeRedis(lock_ttl=80))
    assert evaluate_broker(metrics)["checks"]["beat_heartbeat_age_s"]["state"] == "unknown"


# --- worker availability is independent of Beat ---


def test_worker_online_without_beat_heartbeat():
    metrics = collect_broker(FakeRedis(heartbeat=None), FakeRedis(lock_ttl=80),
                             worker_probe=lambda: True)
    result = evaluate_broker(metrics)
    assert metrics["worker_online"] == 1.0
    assert result["checks"]["worker_online"]["state"] == "ok"
    assert result["checks"]["beat_heartbeat_age_s"]["state"] == "unknown"


def test_beat_healthy_but_no_workers_is_critical():
    metrics = collect_broker(FakeRedis(heartbeat=_iso(2)), FakeRedis(lock_ttl=80),
                             worker_probe=lambda: False)
    assert metrics["worker_online"] == 0.0
    assert evaluate_broker(metrics)["status"] == "critical"


def test_probe_timeout_is_unknown_not_dead():
    def boom():
        raise TimeoutError("broker did not answer")

    metrics = collect_broker(FakeRedis(heartbeat=_iso(2)), FakeRedis(lock_ttl=80),
                             worker_probe=boom)
    assert metrics["worker_online"] is None
