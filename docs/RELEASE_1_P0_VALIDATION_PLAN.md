# Release 1 P0 Validation Plan

Status: plan only. **Do not implement P0 yet.** No test harness, script, schema,
or runtime behavior has been created.

> **Execution update:** P0 has since been executed. Results: 19 executed, 18
> passed, 1 failed (P0-13 visibility), real S3 provider blocked. See
> [`RELEASE_1_P0_EXECUTION_REPORT.md`](./RELEASE_1_P0_EXECUTION_REPORT.md).
> The tests below are the original plan; the result documents are authoritative.

## 1. Purpose

P0 is a **validation foundation**, not the Release 1 implementation. It must
prove the primitives the architecture depends on before any production schema or
worker behavior is changed.

P0 must answer:

- Does Postgres row locking make conditional claim/fencing deterministic?
- Does a zero-row guarded update reliably stop a second writer?
- Does Redis/Celery redeliver long/unacked tasks as documented?
- Does worker termination recover without duplicate execution?
- Can two dispatchers publish the same intent without duplicate execution?
- Can two beats be prevented from scanning/creating duplicate work?
- Can two attempts write artifacts without sharing paths?

P0 may create **test-only tables/fixtures**, but must not alter the application
schema or production code. If a test requires a proposed field, it uses a
scratch table or a test-local model, not a migration.

## 2. Minimal environment

| Component | Version | Source |
|---|---|---|
| PostgreSQL | 16 | existing compose image |
| Redis | 7 | existing compose image |
| Celery | 5.4.0 | existing requirements |
| Kombu | 5.4.2 | existing requirements |
| redis-py | 5.2.1 | existing requirements |
| Python | 3.12 | worker image |
| S3 | fake client or MinIO | test-only |
| OS | Linux container preferred | closer to production |

Local:
- Docker Compose Postgres/Redis, or existing compose services.
- pytest with `pg`, `broker`, `fs`, `s3` markers.
- Two DB engines/sessions and a barrier.
- A test Celery worker process with a small queue.

Production-like:
- Redis AOF restart.
- Worker SIGKILL/OOM-like termination.
- S3-compatible multipart/listing.
- Network latency/timeouts.
- Docker stop grace.

## 3. P0 test harness design

### 3.1 Postgres fixture

- Dedicated database name with a guard (`*_test`).
- Create `Base.metadata` or a **scratch** `p0_leases` table.
- Two independent engines/sessions.
- `statement_timeout`/`lock_timeout` to fail fast.
- Barrier for simultaneous updates.
- Truncate between tests.

### 3.2 Scratch lease table (test-only)

If the real fields are not migrated yet:

```sql
CREATE TABLE p0_leases (
  id integer PRIMARY KEY,
  owner text,
  token bigint NOT NULL DEFAULT 0,
  lease_expires_at timestamptz,
  progress_at timestamptz,
  status text NOT NULL DEFAULT 'queued'
);
```

Tests use the exact proposed SQL shape; this validates the primitive without
changing `jobs`.

### 3.3 Celery/Redis fixture

- Dedicated Redis DBs for broker/result/lock.
- A test task that sleeps/communicates via an event.
- A real worker process started by the test harness.
- Kill -9 / SIGTERM helpers.
- `task_acks_late`, `task_reject_on_worker_lost`, visibility values under test.

### 3.4 Artifact fixture

- Temp storage root.
- Two writer processes/threads writing unique attempt paths.
- Assert no shared path, no truncation, no cross-write.
- Fake S3 client with latency/failure injection.

## 4. P0 validation cases

| ID | Validates | Setup | Action | Assertion |
|---|---|---|---|---|
| P0-1 | Postgres row lock | scratch lease row queued | two conditional claims | one wins, one 0 rows |
| P0-2 | Token fence | token 1 row | token 1 vs token 2 writes | only token 2 affects row |
| P0-3 | Lease expiry | expired lease | claim vs heartbeat | one wins; no dual owner |
| P0-4 | Progress-aware renewal | scratch row; progress event | heartbeat with/without progress | `progress_at` advances only with progress |
| P0-5 | Reaper condition | expired/stale progress | reaper update | only expired/stale row changes |
| P0-6 | Redis visibility | test task > visibility | wait | message redelivered; duplicate can be detected |
| P0-7 | acks_late/reject | test task killed | SIGKILL | message redelivered; DB claim token prevents duplicate |
| P0-8 | Soft/hard limit | test task sleeps | limits | soft catch/kill behavior recorded (if approved) |
| P0-9 | Retry ETA | test task `self.retry` | countdown | new message; no visibility loop |
| P0-10 | Outbox claim | scratch outbox | two dispatchers | one claim; one publish |
| P0-11 | Publish crash | scratch outbox | crash after publish before mark | republish; one execution |
| P0-12 | Beat lock | Redis lock | two starts | one acquires; loser skips |
| P0-13 | Artifact isolation | temp dir | two writers unique paths | no shared bytes/truncation |
| P0-14 | S3 attempt prefix | fake S3 | two attempts | unique keys; stale publish can be rejected |
| P0-15 | Worker termination | real worker | SIGTERM vs SIGKILL | warm/cold behavior recorded; no duplicate DB execution |

## 5. What P0 must not do

- Do not add production fields/tables.
- Do not enable fencing in the app.
- Do not modify `run_job`/`runner` behavior.
- Do not add outbox/schedule ledger production schema.
- Do not change deployment configuration.
- Do not use SQLite as evidence for P0-1/P0-2/P0-4/P0-5/P0-10/P0-11/P0-12.

## 6. Local vs production-like

| Test | Local | Production-like |
|---|---|---|
| P0-1/2/3/5 | Yes (Postgres container) | Recommended for staging |
| P0-4 | Yes (scratch row) | Yes |
| P0-6/7/9/15 | Yes (Redis/Celery container) | **Required** for redelivery/shutdown |
| P0-8 | Maybe | **Required** if time limits approved |
| P0-10/11 | Yes (scratch outbox) | Yes |
| P0-12 | Yes (Redis) | Yes |
| P0-13 | Yes (temp dir) | Yes |
| P0-14 | Fake S3 | **Required** for MinIO/S3-compatible |

## 7. CI requirements

- `pytest -m pg` uses a Postgres service container.
- `pytest -m broker` uses Redis and a real worker.
- `pytest -m fs` uses a temp directory.
- `pytest -m s3` uses a fake or MinIO service.
- Default unit suite stays SQLite-only and fast.
- Record test durations; P0 must be practical for CI (<10 min target, adjust).
- Artifacts: test DB queries, logs, metric deltas.

## 8. P0 exit criteria

1. P0-1..P0-5 prove one-winner/fence semantics on Postgres.
2. P0-6/7/9/15 record actual Celery/Redis behavior for the installed versions.
3. P0-10/11 prove outbox claim/republish does not duplicate execution.
4. P0-12 proves two beats cannot both scan under the lock.
5. P0-13/14 prove attempt isolation and unique S3 keys.
6. Results are documented; any assumption contradicted by P0 is revised before
   P1.

## 9. P0 non-goals

P0 does not prove the full job lifecycle, artifact publication, schedule
recovery, or API compatibility. It proves the primitives those designs depend
on. If P0 fails, stop and revise the architecture before implementation.
