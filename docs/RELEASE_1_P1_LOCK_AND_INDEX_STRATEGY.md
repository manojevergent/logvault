# Release 1 P1 Lock and Index Strategy

Status: **design only.** No migration, index, schema, or configuration change was
made. P1 remains unauthorized.

Companion documents:

- [`RELEASE_1_P1_MIGRATION_EXECUTION_STRATEGY.md`](./RELEASE_1_P1_MIGRATION_EXECUTION_STRATEGY.md)
- [`RELEASE_1_P1_MIGRATION_SEQUENCE.md`](./RELEASE_1_P1_MIGRATION_SEQUENCE.md)
- [`RELEASE_1_P1_MIGRATION_SAFETY_PREFLIGHT.md`](./RELEASE_1_P1_MIGRATION_SAFETY_PREFLIGHT.md)

## 1. Lock policy

### 1.1 Lock modes in P1

| Operation | Lock on `jobs` | Blocks |
|---|---|---|
| `ALTER TABLE ... ADD COLUMN` | `ACCESS EXCLUSIVE` | All reads and writes |
| `CREATE INDEX` (normal) | `SHARE` | Writes; reads continue |
| `CREATE INDEX CONCURRENTLY` | `SHARE UPDATE EXCLUSIVE` | Other DDL; reads/writes continue |
| `CREATE TABLE` (new table) | `ACCESS EXCLUSIVE` on the new table | Nothing existing |
| `CREATE INDEX` on a new empty table | `SHARE` on the new table | Nothing existing |

`ALTER TABLE` is metadata-only for constant defaults on PostgreSQL 11+, but the
lock is still `ACCESS EXCLUSIVE` and is held until the transaction commits.

### 1.2 Lock acquisition timeout versus lock holding duration

These are different controls and must not be conflated:

| Control | Bounds | Does not bound |
|---|---|---|
| `lock_timeout` | How long a statement waits to **acquire** a lock | How long the lock is held after acquisition |
| `statement_timeout` | How long a single statement may **execute** | Time spent idle in a transaction |
| `idle_in_transaction_session_timeout` | Idle time inside a transaction | A long-running active statement |
| Transaction boundary | How long locks are **held** | Wait time before the first lock |

PostgreSQL 16 does **not** have `transaction_timeout` (introduced in 17). P1
must therefore control lock holding by keeping transactions short, not by
expecting a session setting to cap total transaction time.

### 1.3 Recommended policy

Final production values are **not** chosen here. Use measured values.

| Policy | Initial staging test value | How to finalize |
|---|---|---|
| `lock_timeout` for metadata revisions | 3 s | Measure p99 lock wait on a production copy; set above normal wait, below tolerable API latency |
| `lock_timeout` for concurrent index revisions | 5 s | Measure wait for `SHARE UPDATE EXCLUSIVE`; retry is safe |
| `statement_timeout` for metadata DDL | 60 s | Must exceed measured metadata DDL by a safe margin |
| `statement_timeout` for index builds | 15 min | Must exceed measured build on the production-sized copy; raise only with evidence |
| Target transaction duration, metadata revision | < 5 s | Measure; if longer, split the revision |
| Target transaction duration, index revision | One index per autocommit block | Bound by measured build time |
| Retry attempts | 3 | 10 s, 30 s, 60 s backoff, then stop |
| Abort on lock timeout | Yes | Never retry with `lock_timeout=0` |

These are **test starting points**, not production promises. Apply them to the
Alembic connection with `PGOPTIONS` (for example,
`PGOPTIONS="-c lock_timeout=3s -c statement_timeout=60s" alembic upgrade 0032`)
or an approved per-connection wrapper; a `SET` in a separate psql session does
not affect Alembic.

### 1.4 Retry and abort behavior

1. On `lock_timeout`, the statement fails; the transactional revision rolls
   back. Do not continue.
2. Identify blockers with `pg_blocking_pids` and `pg_stat_activity`.
3. Do not kill a long transaction without the owner's approval.
4. Re-run after the blocker clears, up to the retry limit.
5. If retries fail, abort the window and reschedule.
6. For a concurrent index, inspect `pg_index.indisvalid` before retrying.
7. Never set `lock_timeout=0` to "make it go through."

### 1.5 How to choose final values

On a production-sized copy under realistic read/write load:

- record lock wait per revision;
- record total revision and index build duration;
- record API p99 latency and worker heartbeat during the run;
- record `pg_stat_activity` samples for blocked sessions;
- set `lock_timeout` above the normal p99 wait but below the latency budget;
- set `statement_timeout` above the measured p99.9 duration plus margin;
- if a metadata revision exceeds the target, split it rather than raising the
  timeout.

## 2. Index inventory

### 2.1 Existing-table indexes

| Index | Revision | Table | Definition | P1 query | Recommendation |
|---|---|---|---|---|---|
| `ix_jobs_lease` | `0032b` | `jobs` | `(status, lease_expires_at) WHERE lease_expires_at IS NOT NULL` | Reaper/claim expiry scan | **Create concurrently, partial** |
| `ix_jobs_owner` | `0032b` | `jobs` | `(owner_id) WHERE owner_id IS NOT NULL` | Owner lookup | **Create concurrently, partial** |
| `ix_jobs_progress` | `0032b` | `jobs` | `(status, progress_at) WHERE progress_at IS NOT NULL` | Silent-job reaper | **Create concurrently, partial** |
| `ix_jobs_retry_of` | none | `jobs` | `(retry_of) WHERE retry_of IS NOT NULL` | No P1 query | **Defer to P2/P9** |
| `ix_jobs_schedule_window_id` | none | `jobs` | `(schedule_window_id) WHERE schedule_window_id IS NOT NULL` | No P1 query | **Defer to P7** |
| `uq_jobs_schedule_attempt` | `0035b` | `jobs` | unique `(schedule_window_id, attempt_no) WHERE schedule_window_id IS NOT NULL` | Future window attempt identity | **Create concurrently in P1b or defer to P7** |
| `uq_jobs_schedule_active` | `0035b` | `jobs` | unique `(schedule_window_id) WHERE schedule_window_id IS NOT NULL AND status IN ('queued','running','paused')` | Future one-active-job guard | **Create concurrently in P1b or defer to P7** |
| `ix_jobs_s3_uploading` | `0036b` | `jobs` | `(s3_uploading_at) WHERE s3_uploading_at IS NOT NULL` | Future stale S3 scan | **Defer to P8, or concurrent** |

### 2.2 New-table indexes

These are on empty tables created in the same revision. Concurrent creation is
unnecessary; there is no existing traffic.

| Index | Revision | Table | Purpose |
|---|---|---|---|
| `ix_job_dispatch_due` | `0034` | `job_dispatch_outbox` | Due scan |
| `ix_job_dispatch_locked` | `0034` | `job_dispatch_outbox` | Stale dispatcher lock |
| `ix_schedule_windows_due` | `0035` | `schedule_windows` | Due scan |
| `ix_schedule_windows_schedule` | `0035` | `schedule_windows` | Per-schedule history |
| `uq_schedule_windows_window` | `0035` | `schedule_windows` | Window identity |

### 2.3 Why `ix_jobs_retry_of` should not be built in P1

It is a full btree over a column that is NULL on every existing row. It serves no
P1 query. A full index:

- adds an entry for every existing job, all NULL;
- increases build time and disk usage;
- may be ignored by the planner until retry code exists;
- creates an object that P2/P9 may rename or replace.

**Recommendation:** do not create it in P1. When the retry-lineage query exists,
add a **partial** concurrent index:

```sql
CREATE INDEX CONCURRENTLY ix_jobs_retry_of
  ON jobs (retry_of)
  WHERE retry_of IS NOT NULL;
```

### 2.4 Why `ix_jobs_schedule_window_id` should not be built in P1

Same issue: a full index over an all-NULL column, with no P1 query. It becomes
useful in P7 when windows link to jobs. Build it then as a partial concurrent
index:

```sql
CREATE INDEX CONCURRENTLY ix_jobs_schedule_window_id
  ON jobs (schedule_window_id)
  WHERE schedule_window_id IS NOT NULL;
```

If the P1 schema contract requires the index now, make it partial and concurrent;
do not create the full version.

### 2.5 Query usability

| Index | Query predicate | Partial predicate implied? |
|---|---|---|
| `ix_jobs_lease` | `status='running' AND lease_expires_at < now() - grace` | Yes (`<` implies NOT NULL) |
| `ix_jobs_progress` | `status='running' AND progress_at < now() - timeout` | Yes |
| `ix_jobs_owner` | `owner_id = :owner` | Yes |
| `ix_jobs_retry_of` | `retry_of = :id` | Yes |
| `ix_jobs_schedule_window_id` | `schedule_window_id = :id` | Yes |
| `ix_jobs_s3_uploading` | `s3_uploading_at < now()` | Yes |

Verify with `EXPLAIN (ANALYZE, BUFFERS)` on a production-sized copy. A partial
index is only used when the planner can prove the query predicate implies the
index predicate.

### 2.6 Unique indexes versus unique constraints

`CREATE UNIQUE INDEX CONCURRENTLY` creates a unique index, not a named table
constraint. If the design requires a real constraint:

1. create the unique index concurrently;
2. `ALTER TABLE ... ADD CONSTRAINT ... UNIQUE USING INDEX ...`.

Step 2 takes a brief `ACCESS EXCLUSIVE` lock. For P1, a unique index is
sufficient for enforcement and avoids the additional lock. Document that choice.

## 3. `CREATE INDEX CONCURRENTLY` implications

| Property | Implication |
|---|---|
| Cannot run in a transaction | Must use `autocommit_block()` or an external step |
| Takes `SHARE UPDATE EXCLUSIVE` | Reads/writes continue; other DDL waits |
| Waits for old transactions | `lock_timeout` bounds the wait; long transactions can block |
| Takes longer than normal build | Two scans plus wait for snapshots |
| Can leave an invalid index | Must inspect `pg_index.indisvalid` |
| `IF NOT EXISTS` can hide invalid index | Validate, drop, rebuild |
| Unique build can fail on duplicates | Audit before build; do not force |
| `autocommit_block` commits preceding work | Put it in a dedicated revision |
| Version stamp happens after the block | Partial index state is possible on failure |

### 3.1 Retry safety

| Index type | Retry after failure |
|---|---|
| Transactional new-table index | Revision rolled back; retry is safe |
| Concurrent non-unique | Drop invalid index if present; retry |
| Concurrent unique | Drop invalid index; audit duplicates; retry |
| Multiple concurrent indexes in one block | Earlier indexes may remain; validate each |

### 3.2 Lock hold versus build time

`lock_timeout` does not stop a concurrent index that has acquired its lock and is
building. `statement_timeout` is the bound. If the build legitimately exceeds the
timeout, split or schedule a longer window rather than disabling the timeout
without a plan.

## 4. Recommended index revision split

| Revision | Indexes | Transaction model |
|---|---|---|
| `0032` | No indexes | One short transaction |
| `0032b` | `ix_jobs_lease`, `ix_jobs_owner`, `ix_jobs_progress` | `autocommit_block`, one index per block |
| `0033` | No indexes | One short transaction |
| `0034` | New-table indexes | One short transaction |
| `0035` | New-table indexes only | One short transaction |
| `0035b` | `uq_jobs_schedule_attempt`, `uq_jobs_schedule_active` (optional) | `autocommit_block`, one index per block |
| `0036` | No indexes | One short transaction |
| `0036b` | `ix_jobs_s3_uploading` (optional) | `autocommit_block` |

Deferred indexes:

- `ix_jobs_retry_of` -> P2/P9.
- `ix_jobs_schedule_window_id` -> P7.
- `ix_jobs_s3_uploading` -> P8 unless P1b includes it.
- Schedule unique indexes -> P7 unless the P1 contract requires them now.

## 5. Decision summary

| Question | Decision |
|---|---|
| Concurrent indexes on `jobs`? | Yes, in dedicated index revisions |
| Separate migration revision? | Yes for existing-table indexes; no for empty new tables |
| Retry after failure? | Only after catalog validation; drop invalid indexes |
| Partial index? | Yes for lease, progress, owner, retry, window, S3 |
| Can P1 queries use them? | Lease/progress/owner yes; retry/window/S3 have no P1 query |
| Full all-NULL indexes? | No |
| Unique constraint vs index? | Unique index is sufficient for P1; constraint needs a brief lock |

## 6. Stop condition

This is a design proposal. No index or migration was created. P1 remains
unauthorized.
