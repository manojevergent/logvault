# Release 1 P1 Migration Sequence

Status: **design only.** No migration was created or executed. No code or
configuration was changed. P1 remains unauthorized.

Companion documents:

- [`RELEASE_1_P1_MIGRATION_EXECUTION_STRATEGY.md`](./RELEASE_1_P1_MIGRATION_EXECUTION_STRATEGY.md)
- [`RELEASE_1_P1_LOCK_AND_INDEX_STRATEGY.md`](./RELEASE_1_P1_LOCK_AND_INDEX_STRATEGY.md)
- [`RELEASE_1_P1_BACKUP_AND_RECOVERY_PLAN.md`](./RELEASE_1_P1_BACKUP_AND_RECOVERY_PLAN.md)
- [`RELEASE_1_P1_FINAL_GO_NO_GO.md`](./RELEASE_1_P1_FINAL_GO_NO_GO.md)

## 1. Pre-migration checks

Do not start the sequence until all checks pass.

| Check | Method | Pass condition |
|---|---|---|
| Revision | `alembic current` | `0031` (or the approved predecessor) |
| Tree clean | `git status` | No unexpected application/migration changes |
| P1 scope approved | Authorization record | Explicit P1 approval |
| D11 decided | Approval record | `0035` included or graph adjusted |
| Backup | Fresh dump + `pg_restore --list` | Exit 0, checksum recorded |
| Restore test | Scratch restore + old stack smoke | Pass |
| Production copy measurement | Staging/production-sized copy | Lock/duration recorded |
| Long transactions | `pg_stat_activity` | None on `jobs` |
| Locks | `pg_locks` | No conflicting `ACCESS EXCLUSIVE` |
| Disk | `df` | Sufficient for indexes + backup |
| Connections | `pg_stat_activity` | Headroom below `max_connections` |
| Backup sidecar | Compose status | Paused or dump complete |
| Old stack health | `/ready`, `/health/ops` | Healthy |
| Change window | Change record | Approved; owner named |

## 2. Session guards

Before each revision invocation, set bounded values **on the Alembic
connection**, not in a separate psql session. Use `PGOPTIONS` on the migration
process or an approved per-connection wrapper:

```bash
PGOPTIONS="-c lock_timeout=3s -c statement_timeout=60s -c idle_in_transaction_session_timeout=60s" \
  alembic upgrade 0032
```

Equivalent SQL, if set inside the same connection:

```sql
SET lock_timeout = '3s';          -- metadata revision; 5s for concurrent index
SET statement_timeout = '60s';    -- metadata; 15min for index build
SET idle_in_transaction_session_timeout = '60s';
```

A `SET` in an unrelated psql session does not affect Alembic's connection.

Final values come from the measurement procedure in
[`RELEASE_1_P1_LOCK_AND_INDEX_STRATEGY.md`](./RELEASE_1_P1_LOCK_AND_INDEX_STRATEGY.md).

`lock_timeout` bounds **acquisition**, not holding. Keep transactions short.

## 3. Revision sequence

### 3.1 Overview

```text
0031
  -> 0032   jobs ownership/completion columns (transaction)
  -> 0032b  jobs lease/owner/progress indexes (concurrent, autocommit)
  -> 0033   jobs artifact/checkpoint columns (transaction)
  -> 0034   job_dispatch_outbox table + new-table indexes (transaction)
  -> 0035   schedule_windows table + jobs window columns + new-table indexes (transaction)
  -> 0036   jobs S3 attempt columns (transaction)
```

`0035b` (schedule jobs indexes) and `0036b` (S3 index) are **not part of P1**.
They are future P7/P8 revisions.
`ix_jobs_retry_of` is deferred to P2/P9.
`ix_jobs_schedule_window_id` is deferred to P7.
`ix_jobs_s3_uploading` is deferred to P8.

### 3.2 Step 0032 — ownership/completion columns

| Item | Detail |
|---|---|
| Contents | 11 `ADD COLUMN` statements; no indexes |
| Transaction | One revision transaction |
| Lock | Brief `ACCESS EXCLUSIVE` on `jobs` |
| Expected duration | Sub-second in the observed 25 MB DB; measure on production copy |
| Verification | Columns/types/defaults; no indexes; `alembic current=0032`; API/worker healthy |
| Failure | Rollback; fix; retry |
| Retry | Safe; no partial DDL expected |

Do not add `ix_jobs_*` here. Do not add data backfill.

### 3.3 Step 0032b — jobs lease/owner/progress indexes

| Item | Detail |
|---|---|
| Contents | `ix_jobs_lease`, `ix_jobs_owner`, `ix_jobs_progress`, all partial |
| Transaction | `autocommit_block`, one index per block |
| Lock | `SHARE UPDATE EXCLUSIVE`; reads/writes continue |
| Expected duration | Measure; O(jobs rows) |
| Verification | `pg_index.indisvalid=true`; `EXPLAIN` uses partial index; no invalid indexes |
| Failure | Invalid index possible; version stays `0032` |
| Retry | Drop invalid index concurrently; recreate; validate |

Definitions:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_jobs_lease
  ON jobs (status, lease_expires_at)
  WHERE lease_expires_at IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_jobs_owner
  ON jobs (owner_id)
  WHERE owner_id IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_jobs_progress
  ON jobs (status, progress_at)
  WHERE progress_at IS NOT NULL;
```

### 3.4 Step 0033 — artifact/checkpoint columns

| Item | Detail |
|---|---|
| Contents | `store_path`, `spec_fingerprint`, `checkpoint_version` |
| Transaction | One revision transaction |
| Lock | Brief `ACCESS EXCLUSIVE` on `jobs` |
| Verification | Columns/types/defaults; no indexes; `alembic current=0033` |
| Failure | Rollback; retry |
| Retry | Safe |

### 3.5 Step 0034 — dispatch outbox

| Item | Detail |
|---|---|
| Contents | `job_dispatch_outbox` table; `ix_job_dispatch_due`; `ix_job_dispatch_locked`; unique `(job_id, task_name)` |
| Transaction | One revision transaction |
| Lock | New table only |
| Verification | Table/indexes exist; 0 rows; no readers/writers |
| Failure | Rollback; retry |
| Retry | Safe |
| Behavior | No dispatcher; no rows inserted |

### 3.6 Step 0035 — schedule windows (if D11 includes)

| Item | Detail |
|---|---|
| Contents | `schedule_windows` table; `jobs.schedule_window_id`; `jobs.attempt_no`; `ix_schedule_windows_due`; `ix_schedule_windows_schedule`; `uq_schedule_windows_window` |
| Transaction | One revision transaction |
| Lock | Brief `ACCESS EXCLUSIVE` on `jobs`; new table only |
| Verification | Table/indexes; 0 rows; all `jobs.schedule_window_id` NULL; `alembic current=0035` |
| Failure | Rollback; retry |
| Retry | Safe |
| Behavior | No scheduler; no rows inserted |

Do **not** create `ix_jobs_schedule_window_id`, `uq_jobs_schedule_attempt`, or
`uq_jobs_schedule_active` in this revision.

### 3.7 Deferred - 0035b jobs schedule indexes (P7, not P1)

**Not part of P1.** This revision is created in P7 when the scheduler writes
windows and the jobs indexes are needed.

| Item | Detail |
|---|---|
| Contents | `uq_jobs_schedule_attempt`, `uq_jobs_schedule_active`; optionally partial `ix_jobs_schedule_window_id` |
| Transaction | `autocommit_block`, one index per block |
| Lock | `SHARE UPDATE EXCLUSIVE` |
| Verification | `indisvalid`; all existing rows NULL; duplicate insert rejected |
| Failure | Invalid index; drop/recreate |
| Retry | Audit duplicates; do not force |
| Decision | Not part of P1; create in P7 if the scheduler requires the guards |
 
Future P7 definitions (not executed in P1):

```sql
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_jobs_schedule_attempt
  ON jobs (schedule_window_id, attempt_no)
  WHERE schedule_window_id IS NOT NULL;

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_jobs_schedule_active
  ON jobs (schedule_window_id)
  WHERE schedule_window_id IS NOT NULL
    AND status IN ('queued','running','paused');
```

These are unique indexes, not named constraints. If a named constraint is
required, add it with `ALTER TABLE ... ADD CONSTRAINT ... UNIQUE USING INDEX ...`
in a separate short transaction and accept the brief `ACCESS EXCLUSIVE` lock.

### 3.8 Step 0036 — S3 attempt columns

| Item | Detail |
|---|---|
| Contents | `s3_attempt_token`, `s3_uploading_at`, `s3_published_attempt`, `s3_manifest_uri` |
| Transaction | One revision transaction |
| Lock | Brief `ACCESS EXCLUSIVE` on `jobs` |
| Verification | Columns/defaults; all tokens 0; no S3 behavior |
| Failure | Rollback; retry |
| Retry | Safe |

### 3.9 Deferred - 0036b S3 index (P8, not P1)

**Not part of P1.** This index is created in P8.

| Item | Detail |
|---|---|
| Contents | `ix_jobs_s3_uploading` partial concurrent |
| Transaction | `autocommit_block` |
| Verification | `indisvalid`; no S3 code reads it |
| Decision | P8 only; not part of P1 |

## 4. D11 dependency resolution

If D11 selects **REDUCED**, exclude both `0035` and `0036`:
- do not create `0035`, `0036`, `0035b`, or `0036b`;
- graph becomes `0031 -> 0032 -> 0032b -> 0033 -> 0034`;
- later, when the ledger/S3 scope is separately approved, add new revision(s)
  after the current head.

Do not create an empty `0035` marker and do not set `0036.down_revision` in the
REDUCED graph, because `0036` is not part of P1 in that option.

## 5. Post-revision verification

After each revision:

| Check | SQL/command | Pass |
|---|---|---|
| Revision | `alembic current` | Expected revision |
| Columns | `information_schema.columns` | Exact set/type/default |
| Tables | `pg_tables` | Expected only |
| Indexes | `pg_indexes` + `pg_index.indisvalid` | Valid, expected only |
| Row counts | `jobs`, new tables | Unchanged; new tables 0 |
| Locks | `pg_locks` | No lingering `ACCESS EXCLUSIVE` |
| Blocked sessions | `pg_stat_activity` | None |
| API | `/ready`, `/jobs` | Healthy |
| Worker | heartbeat/beat freshness | Healthy |
| Errors | API/worker logs | No new schema errors |
| Behavior | No P2 flags | Confirmed off |

Abort the sequence if any verification fails.

## 6. Failure handling

| Failure | Action |
|---|---|
| Metadata revision fails | Transaction rolled back; version previous; fix and retry |
| Concurrent index fails | Inspect `pg_index.indisvalid`; drop invalid; recreate |
| Lock timeout | Abort; identify blocker; reschedule |
| Disk full | Free space; rollback/retry |
| Container kill | PostgreSQL rolls back open transaction; verify version |
| API/worker unhealthy | Stop; fix; old code remains compatible |
| Version/object mismatch | Audit catalog; do not stamp blindly |
| Wrong revision applied | Stop; do not improvise; use approved downgrade or forward-fix |

## 7. Safe retry procedures

### 7.1 Transactional revision

1. `alembic current` — confirm previous revision.
2. Check for objects from the failed revision.
3. Fix the cause.
4. Re-run the same revision.

### 7.2 Concurrent index

1. Query:

   ```sql
   SELECT indexrelid::regclass, indisvalid, indisready
   FROM pg_index
   WHERE indexrelid::regclass::text = '<index>';
   ```

2. If invalid, `DROP INDEX CONCURRENTLY <index>;`.
3. Recreate with the same definition.
4. Verify `indisvalid=true`.
5. Continue.

### 7.3 Partial autocommit revision

1. List all indexes in that revision.
2. Validate each.
3. Drop only invalid/missing ones.
4. Recreate.
5. Do not re-run the whole revision blindly if `IF NOT EXISTS` would skip an
   invalid index.

## 8. Rollback sequence

P1-only, before P2:

1. P1 index revision: downgrade `0032b`.
2. Downgrade column/table revisions in reverse order (`0036`, `0035`, `0034`,
   `0033`, `0032`).
3. Verify old API/worker still serve.

After P2 has started:

1. Disable P2 behavior.
2. Drain workers.
3. Export/discard outbox/window state deliberately.
4. Roll back P2 code.
5. Then downgrade P1.

Do not drop `schedule_windows` or `job_dispatch_outbox` after they contain live
state without a decision record.

## 9. Execution record

For each revision, record:

- revision ID;
- start/end time;
- session settings (`lock_timeout`, `statement_timeout`);
- total duration;
- max lock wait;
- blocked sessions;
- index validity;
- API/worker health;
- errors;
- operator;
- go/no-go for the next revision.

## 10. Stop condition

This is a sequence design. No migration was executed. P1 remains unauthorized.
