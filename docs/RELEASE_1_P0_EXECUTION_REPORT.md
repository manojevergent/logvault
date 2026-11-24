# Release 1 P0 Execution Report

Status: P0 validation executed. No production code, schema, migration, API,
dependency, or deployment configuration was modified. No P1 work started.

## 1. Authorization boundary

This work was limited to `p0/` test infrastructure, scratch `p0_*` tables, a
test-only Celery app, a P0 fake S3 endpoint, and documentation.

Not changed:
- production application source;
- production models/schema/migrations;
- production API/frontend;
- production Celery/Redis/S3 config;
- deployment config;
- production data.

## 2. Environment

| Item | Value |
|---|---|
| PostgreSQL | `postgres:16-alpine`, isolated container |
| Redis | `redis:7-alpine`, isolated container, AOF |
| Python | 3.12.16 |
| Celery | 5.4.0 |
| Kombu | 5.4.2 |
| redis-py | 5.2.1 |
| SQLAlchemy | 2.0.36 |
| psycopg | 3.2.3 |
| boto3 | 1.35.36 |
| Test network | `p0_default` |
| Production stack | untouched (existing compose stack remains separate) |

## 3. How P0 was executed

```bash
docker compose -f p0/docker-compose.p0.yml -p p0 up -d

docker run --rm --init --network p0_default \
  -v "<repo>/p0:/p0" -w /p0 \
  -e P0_PG_DSN=postgresql://p0:p0@postgres:5432/p0 \
  -e P0_REDIS_URL=redis://redis:6379/0 \
  -e P0_CELERY_BROKER=redis://redis:6379/1 \
  -e P0_CELERY_BACKEND=redis://redis:6379/2 \
  -e P0_VISIBILITY=5 -e PYTHONPATH=/p0 \
  --entrypoint python last9_web_app-worker:latest /p0/run_p0.py
```

The worker image is used only for its pinned Python/Celery/psycopg/boto3
runtime. P0 tasks are test-only (`p0.sleep_task`, etc.).

## 4. Results

| Metric | Count |
|---|---|
| Executed | 19 |
| Passed | 18 |
| Failed | 1 |
| Blocked | 1 (real S3 provider) |
| Not executed | 23/24 h limits, production timing, production S3, full T1-T24 |

Detail: [`RELEASE_1_P0_TEST_RESULTS.md`](./RELEASE_1_P0_TEST_RESULTS.md).

## 5. What P0 proved

- Postgres conditional claim: exactly one winner.
- Token/owner fence: stale token 0 rows.
- Fresh lease not reclaimed; expired lease reclaimed.
- Progress marker does not advance without progress.
- Reaper reaps only stale lease.
- Cancel dominance; pause/resume fence.
- Outbox claim/republish does not duplicate execution in the model.
- Schedule ledger unique window/one active job/lock/retry/snapshot/delete in
  the model.
- Attempt-scoped files isolate bytes.
- P0 S3 stub unique prefixes/DB pointer/cleanup preservation.
- Checkpoint protocol: resume only valid; restart invalid; exact rows/counts.
- Celery worker kill/redelivery, retry/ETA, hard limit, SIGTERM.
- Redis AOF key and queued-message persistence across restart.

## 6. What P0 did not prove

- **P0-13 failed:** visibility alone did not redeliver a long task while two
  idle workers were already running; starting a new worker did (P0-13b).
  Therefore visibility is not a reliable recovery mechanism.
- 23 h/24 h hard/soft limits were not tested; only the mechanism with 3 s/2 s.
- Real S3/MinIO multipart, conditional writes, IAM, versioning, listing.
- Production Redis eviction/memory policy.
- Production Postgres isolation/latency/lock contention.
- Production-scale chunk/finalization/DB timing.
- Full T1-T24 lifecycle/API/frontend tests.
- Actual source-data mutability.

## 7. Critical findings

1. **Broker visibility is not a recovery guarantee.** DB lease-expiry
   re-dispatch is mandatory for long jobs; fencing prevents duplicate writes but
   not duplicate delivery/starts.
2. **New worker startup can restore unacked tasks.** A rolling deploy/scaling
   event can start a duplicate while the original is alive. Fencing and DB
   claim must be in place before worker scaling.
3. **Checkpoint zero-committed chunks must restart.** A row at
   `completed_chunks=0` is not recoverable work.
4. **Store-ahead resume works** when the marker is preserved; store-behind must
   restart.
5. **Warm SIGTERM can finish a short task**, but long-task shutdown behavior
   depends on the deployment stop grace.
6. **Hard limit kills the child** (short test); production limits remain a
   business decision.

## 8. P0 artifacts

- `p0/docker-compose.p0.yml`
- `p0/run_p0.py`
- `p0/celery_app.py`
- `p0/checkpoint_worker.py`
- `p0/fake_s3.py`
- `p0/probe_visibility.py`
- `p0/probe_visibility_new_worker.py`
- `p0/probe_consume.py`
- `p0/results/p0_results.json`
- `p0/results/p0_manual_evidence.json`
- `p0/results/logs/`
- `p0/results/checkpoint/`, `artifacts/`, `s3/`

## 9. P0 verdict

P0 is **complete for primitive validation**, with **one failed test** (P0-13)
that changes the Celery/Redis architecture decision, and **one blocked area**
(real S3 provider).

P0 does **not** authorize P1. It establishes that the DB-authoritative
ownership/recovery model is viable and that broker visibility cannot be the
recovery mechanism.
