# Release 1 P0 Configuration Findings

Status: findings from source/config inspection and isolated P0 execution.

## 1. Verified versions

| Component | Version | Evidence |
|---|---|---|
| Python | 3.12.16 | worker image |
| Celery | 5.4.0 | worker requirements/image |
| Kombu | 5.4.2 | worker requirements/image |
| redis-py | 5.2.1 | worker requirements/image |
| Redis | 7-alpine | P0 compose |
| PostgreSQL | 16-alpine | P0 compose |
| boto3 | 1.35.36 | worker image |
| SQLAlchemy | 2.0.36 | worker image |
| psycopg | 3.2.3 | worker image |

## 2. Celery configuration (production source, not changed)

`worker/app/celery_app.py`:

- `task_acks_late=True`
- `task_reject_on_worker_lost=True`
- `worker_prefetch_multiplier=1`
- `task_track_started=True`
- `result_expires=3600`
- no `visibility_timeout`
- no `task_time_limit` / `task_soft_time_limit`
- no `task_acks_on_failure_or_timeout` override
- broker/result Redis DBs 1/2
- beat: scan 60 s, cleanup 3600 s, reaper 300 s, health 60 s

## 3. Redis configuration

P0 Redis: `--appendonly yes --save ""`; AOF enabled.
Production compose: `redis-server --appendonly yes`; no `maxmemory`/eviction
policy, no explicit persistence tuning.

P0 findings:

- AOF key survived restart: `p0:aof_probe=persisted`.
- A queued Celery message survived a Redis restart (`LLEN p0` 1 before/after;
  one start after restart).
- Unacked visibility behavior is **not** a reliable timer (P0-13).

## 4. Visibility timeout findings

- Celery 5.4 Redis default is 3600 s; production does not set it explicitly.
- P0 used 5 s to test the mechanism.
- With two solo workers already running, a 10 s task was **not** redelivered
  within 18 s; Redis kept the delivery unacked.
- Starting a new worker restored the unacked task and produced a duplicate
  start (P0-13b).
- Kombu 5.4.2 `QoS.restore_visible` is poll/startup-triggered and runs every
  10th call, not a guaranteed wall-clock timer.

### Implication

Visibility timeout is a broker detail, not a recovery guarantee. A DB-driven
lease-expiry re-dispatch is required.

## 5. Acknowledgement/termination findings

- `acks_late` works: message remained unacked during execution.
- `task_reject_on_worker_lost` + SIGKILL: new worker started the task again
  (P0-14).
- `self.retry` countdown 1 s executed twice (P0-15).
- Hard `time_limit=3` on prefork killed the task child; no normal end (P0-16).
- SIGTERM warm shutdown let a 5 s task finish in 4.6 s (P0-18).
- 23 h/24 h limits were not tested.

## 6. Result expiry

Production `result_expires=3600`; P0 app used 120. A 24 h job would lose Celery
result state long before completion. The DB is authoritative; recommendation:
`ignore_result=True` for `run_job` or a longer expiry.

P0 did not wait 120 s to inspect expiry; this is source/config evidence, not
runtime evidence.

## 7. Worker/DB pool

- Worker engine uses SQLAlchemy defaults (5 + 10 overflow) unless configured.
- `WORKER_CONCURRENCY=4` default; live resize can exceed pool capacity.
- Heartbeat/progress writes add DB pressure. Size the pool to concurrency +
  margin before resizing high.

## 8. Timing/configuration recommendations

| Setting | Current | P0 finding | Recommended |
|---|---|---|---|
| `visibility_timeout` | unset (3600 default) | Not a recovery timer | Explicit; do not rely on it |
| DB re-dispatch | none | Required | Add lease-expiry reconciler |
| `task_time_limit` | unset | Hard limit works in short test | Business decision (24 h candidate) |
| `task_soft_time_limit` | unset | Not tested | Business decision |
| `result_expires` | 3600 | Too short for long jobs | ignore_result or > max runtime |
| Redis AOF | on | queued message survived restart | Keep; noeviction/memory headroom |
| Docker stop grace | default | Short task finish | 60-120 s before SIGKILL |
| `progress_at` | new | SQL gating works | Persist/measure |
| Lease TTL | 600 proposed | No production evidence | Measure; provisional |
| Heartbeat | 60 proposed | No production evidence | Measure |
| Progress timeout | 3600 proposed | No production evidence | Measure silent stages |
| Reaper grace | 60 proposed | No production evidence | Keep short |

## 9. Production measurements required

- p99/p999 chunk duration and max silent interval.
- p99 Last9 request/retry chain.
- p99 zip/summary/finalization.
- p99 DB query/lock wait.
- max legitimate attempt runtime.
- Redis memory/unacked growth under long jobs.
- Docker stop/SIGTERM behavior for multi-hour tasks.
- Real S3 provider behavior.

## 10. Configuration verdict

The P0 stack proved the DB/Celery primitives, but **production values are not
approved**. D8/D9 remain provisional; D9 requires the DB re-dispatch reconciler
and a business runtime-limit decision.
