# Lease and Fencing Design

Status: design proposal for Release 1. Not implemented.
Companion: [`WORKER_OWNERSHIP.md`](./WORKER_OWNERSHIP.md) for phases and
scenario behavior, [`RELEASE_1_DESIGN.md`](./RELEASE_1_DESIGN.md) for scope.

Legend: **[V]** verified current behavior, **[P]** proposed, **[A]** unverified
assumption, **[D]** decision needed.

## 1. Fencing model

### 1.1 Per-job epoch

`jobs.lease_token` is a monotonically increasing integer scoped to one job. It
is not a global sequence and not a UUID.

- Initial value: `0`.
- Every successful claim/reclaim/resume/reaper increments it by 1.
- The worker receives the new value from `UPDATE ... RETURNING`.
- Every subsequent write includes `lease_token = :token`.
- A stale worker has a smaller token; its writes affect 0 rows.

Why per job:

- The protected resources are the job row, its local attempt files, and its S3
  prefix. All are keyed by job id.
- A global sequence would require a sequence/coordination and would not protect
  anything extra.
- A UUID would not give a total order; the fence only needs "newer than the
  previous owner", which an increment provides.

### 1.2 Owner id

`owner_id` identifies the attempt for logs and for the "owner present" phase.
Recommended format:

```
<hostname>:<pid>:<celery-task-id or uuid4[:8]>
```

It is not a secret. The token is the fence. Do not authorize based on
`owner_id` alone.

### 1.3 Lease authority

`lease_expires_at` is the authority, not the worker clock and not the event
timestamp. All lease comparisons use the database clock (`now()` in Postgres).
This avoids clock skew between containers and makes `UPDATE` predicates
consistent.

`heartbeat_at` is informational/ops. It is set by successful renewals but is
not used in write predicates; `lease_expires_at > now()` is.

## 2. Database support

### 2.1 Verified current model

- Postgres 16 in compose **[V]** (`docker-compose.yml:5`).
- SQLAlchemy engine with `future=True`, `pool_pre_ping=True` **[V]**
  (`api/app/database.py`; `worker/app/db.py`).
- Worker uses SQLAlchemy Core and `engine.begin()` per write **[V]**
  (`worker/app/db.py:185-186`).
- The API uses an ORM session with explicit commit **[V]**
  (`api/app/database.py`).
- No custom isolation level is set; Postgres default is READ COMMITTED
  **[A]**.
- The worker table definition is a manual mirror of the API ORM **[V]**
  (`worker/app/db.py:1-74`). New columns must be added there too.
- The worker engine uses SQLAlchemy defaults (pool 5 + 10 overflow) unless
  configured **[V]**. With `WORKER_CONCURRENCY=4` that is adequate; before a
  live resize above ~15 slots, size the worker pool to concurrency + heartbeat/
  progress margin, or heartbeat/progress writes can starve.

### 2.2 Is READ COMMITTED enough?

Yes for this design. The critical operations are single-row conditional
`UPDATE`s:

```sql
UPDATE jobs
SET ...
WHERE id = :id AND <current-state predicate>
RETURNING ...;
```

Postgres takes a row lock for the update. Concurrent updates to the same row
serialize; the second re-evaluates the `WHERE` against the committed row. This
is sufficient for claim, heartbeat, progress, finalization, pause, resume,
cancel, and reaper. No `SERIALIZABLE` isolation is required.

`SELECT ... FOR UPDATE` is not needed for the claim; the conditional `UPDATE`
is simpler and avoids a read-modify-write gap. It may be useful for multi-row
operations (group cancel), but per-row conditional updates are preferred.

### 2.3 SQLite test limitations

The current API and worker tests use SQLite **[V]** (`api/tests/conftest.py`;
`worker/tests/conftest.py`). SQLite:

- serializes writers at the database level;
- does not provide the same row-level concurrency;
- may not support `FOR UPDATE SKIP LOCKED`;
- supports `RETURNING` in recent versions but dialect differences remain.

Use SQLite for unit/serialization tests. Use Postgres for the concurrency
tests in [`RELEASE_1_TEST_PLAN.md`](./RELEASE_1_TEST_PLAN.md). Do not claim a
race is fixed based on a SQLite test.

## 3. Schema changes

### 3.1 `jobs` fields

| Field | Type | Null/default | Why |
|---|---|---|---|
| `owner_id` | `varchar(128)` | NULL | Identifies the current attempt; supports derived `claimed`/`pausing`/`canceling`; diagnostic. |
| `lease_token` | `bigint` | NOT NULL DEFAULT 0 | Monotonic fence. Every worker write compares it. |
| `lease_expires_at` | `timestamptz` | NULL | Authoritative lease expiry; claim/reaper predicate. |
| `heartbeat_at` | `timestamptz` | NULL | Last successful renewal; ops/UI; not a fence. |
| `progress_at` | `timestamptz` | NULL | Last main-loop progress mark; reaper defense-in-depth and NOC visibility. |
| `cancel_requested_at` | `timestamptz` | NULL | Separates a cancel request from terminal cancel; cancel dominance. |
| `pause_requested_at` | `timestamptz` | NULL | Separates pause request from acknowledged pause; derived `pausing`. |
| `completion_state` | `varchar(16)` | NOT NULL DEFAULT `'unknown'` | `unknown`, `complete`, `partial`; prevents partial results looking clean. |
| `gap_count` | `integer` | NOT NULL DEFAULT 0 | Number of skipped batches/sources/BQ drops. |
| `gap_reason` | `text` | NULL | Machine-readable/human-readable gap summary. |
| `store_path` | `text` | NULL | Published attempt-scoped distinct store; rollup/cleanup must use it. |
| `retry_of` | `integer` | NULL | Retry lineage; resume/restart decision. No FK to avoid delete coupling. |
| `s3_attempt_token` | `bigint` | NOT NULL DEFAULT 0 | S3 attempt fence, independent of the job lease after completion. |
| `s3_uploading_at` | `timestamptz` | NULL | S3 retry lock; prevents concurrent retries. |
| `s3_published_attempt` | `bigint` | NULL | Which attempt's S3 objects are current. |
| `s3_manifest_uri` | `text` | NULL | Audit pointer to the attempt manifest. |
| `schedule_window_id` | `integer` | NULL | Links a scheduled attempt to its `schedule_windows` row. |
| `attempt_no` | `integer` | NOT NULL DEFAULT 1 | Attempt number within a schedule window. |

`completion_state`/`gap_*` are required in Release 1, not deferred. They are
set in the terminal write; see 6.3.

### 3.2 Constraints

Recommended:

```sql
ALTER TABLE jobs
  ADD CONSTRAINT ck_jobs_lease_token_nonnegative CHECK (lease_token >= 0),
  ADD CONSTRAINT ck_jobs_s3_attempt_nonnegative CHECK (s3_attempt_token >= 0),
  ADD CONSTRAINT ck_jobs_owner_lease_pair
      CHECK (owner_id IS NOT NULL OR lease_expires_at IS NULL),
  ADD CONSTRAINT ck_jobs_published_attempt
      CHECK (s3_published_attempt IS NULL OR s3_published_attempt <= s3_attempt_token);
```

Do **not** add `status` CHECK in the first migration. Audit first (D13):

```sql
SELECT status, count(*) FROM jobs GROUP BY status;
```

Then:

```sql
ALTER TABLE jobs
  ADD CONSTRAINT ck_jobs_status CHECK (
    status IN ('queued','running','paused','completed','failed','canceled')
  ),
  ADD CONSTRAINT ck_jobs_completion_state CHECK (
    completion_state IN ('unknown','complete','partial')
  );

ALTER TABLE schedule_windows
  ADD CONSTRAINT ck_schedule_windows_status CHECK (
    status IN ('pending','dispatched','running','completed','failed','canceled')
  ),
  ADD CONSTRAINT ck_schedule_windows_completion CHECK (
    completion_state IN ('unknown','complete','partial')
  );
```

Do not add a strict `status='running' => owner_id IS NOT NULL` check in the
first rollout. Old workers and legacy rows may violate it during the mixed
period. Add it after all writers are new if desired.

### 3.3 Indexes

```sql
CREATE INDEX ix_jobs_lease
  ON jobs (status, lease_expires_at);

CREATE INDEX ix_jobs_owner
  ON jobs (owner_id)
  WHERE owner_id IS NOT NULL;

CREATE INDEX ix_jobs_progress
  ON jobs (status, progress_at);

CREATE UNIQUE INDEX uq_jobs_schedule_attempt
  ON jobs (schedule_window_id, attempt_no)
  WHERE schedule_window_id IS NOT NULL;

CREATE UNIQUE INDEX uq_jobs_schedule_active
  ON jobs (schedule_window_id)
  WHERE schedule_window_id IS NOT NULL
    AND status IN ('queued','running','paused');

CREATE UNIQUE INDEX uq_schedule_windows_window
  ON schedule_windows (schedule_id, window_key);
```

`schedule_windows` (minimum columns):

```sql
CREATE TABLE schedule_windows (
  id bigserial PRIMARY KEY,
  schedule_id integer NOT NULL,
  window_key varchar(80) NOT NULL,        -- day:YYYY-MM-DD or slot:<epoch>
  scheduled_for timestamptz NOT NULL,     -- due time for this window
  start_epoch bigint NOT NULL,
  end_epoch bigint NOT NULL,
  status varchar(16) NOT NULL DEFAULT 'pending',
  completion_state varchar(16) NOT NULL DEFAULT 'unknown',
  attempts integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  current_job_id integer,
  next_attempt_at timestamptz,
  last_error text,
  config_snapshot jsonb,                  -- source/filter/format at window creation
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
```

Notes:

- `ix_jobs_lease` supports reaper/reclaim scans.
- `ix_jobs_owner` supports orphan-owner cleanup and support queries; optional
  but cheap.
- `uq_jobs_schedule_attempt` allows multiple terminal attempts per window but
  unique attempt numbers.
- `uq_jobs_schedule_active` prevents two active jobs for one window.
- `uq_schedule_windows_window` prevents duplicate window obligations; the key is
  `day:YYYY-MM-DD` for calendar-day schedules and a fixed dispatch slot
  (`slot:<epoch>`) for interval schedules. `start_epoch` alone is not a stable
  interval identity because a rolling lookback changes every tick.
- Reports/rollups must select the successful attempt (`current_job_id` or
  `status='completed'` winner), not every terminal job for a window; otherwise a
  retry double-counts.
- On Postgres, create indexes with `CONCURRENTLY` if the table is large.
  Alembic's `env.py` wraps migrations in a transaction **[V]**
  (`api/migrations/env.py`), and `CREATE INDEX CONCURRENTLY` cannot run inside a
  transaction. Either:
  1. run it as a separate operational step outside Alembic, or
  2. use a non-concurrent index in a maintenance window, or
  3. set `transaction_per_migration` / use an autocommit block in the
     migration.
  This is a deployment decision (see deployment doc). Do not assume the
  standard Alembic transaction can create it concurrently.

### 3.4 Outbox table

See [`OUTBOX_AND_DISPATCH.md`](./OUTBOX_AND_DISPATCH.md) for the full table.
Summary:

```sql
CREATE TABLE job_dispatch_outbox (
  id bigserial PRIMARY KEY,
  job_id integer NOT NULL,
  task_name varchar(80) NOT NULL DEFAULT 'logvault.run_job',
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status varchar(16) NOT NULL DEFAULT 'pending',
  attempts integer NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  locked_by varchar(128),
  locked_until timestamptz,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz,
  UNIQUE (job_id, task_name)
);

CREATE INDEX ix_job_dispatch_due
  ON job_dispatch_outbox (status, next_attempt_at);
```

### 3.5 Why each field is necessary

| Field | Without it |
|---|---|
| `owner_id` | Cannot derive claimed/pausing/canceling; logs cannot identify the attempt; a zero-token legacy writer is harder to distinguish. |
| `lease_token` | Cannot fence an old worker after reclaim/resume/reaper. |
| `lease_expires_at` | Cannot distinguish a live worker from a dead one without relying on events/clock. |
| `heartbeat_at` | Ops cannot see renewal health; derived phase/debugging is weaker. |
| `cancel_requested_at` | Cannot tell a cancel request from a terminal cancel; cancel dominance is implicit. |
| `pause_requested_at` | Cannot tell a pause request from an acknowledged pause; resume can race. |
| `store_path` | Rollup/cleanup would read the canonical path and miss attempt stores. |
| `retry_of` | No lineage; support cannot tell a retry from an independent job. |
| `s3_attempt_token` | Concurrent S3 retries overwrite each other; no attempt identity. |
| `s3_uploading_at` | No retry lock; duplicate uploads. |
| `s3_published_attempt` | Cannot tell which attempt's objects are current. |
| `s3_manifest_uri` | No audit pointer for the artifact set. |

## 4. Claim SQL

### 4.1 Postgres

```sql
UPDATE jobs
SET status = 'running',
    owner_id = :owner,
    lease_token = lease_token + 1,
    lease_expires_at = now() + make_interval(secs => :ttl),
    heartbeat_at = now(),
    started_at = COALESCE(started_at, now()),
    finished_at = NULL,
    error_message = NULL
WHERE id = :job_id
  AND (
      status = 'queued'
      OR (
          :allow_reclaim
          AND status = 'running'
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at < now() - make_interval(secs => :grace)
      )
  )
RETURNING lease_token, status, checkpoint, output_file_path, store_path;
```

- `allow_reclaim` is true only when Celery reports `redelivered`.
- The `lease_expires_at IS NOT NULL` guard prevents an old row with no lease
  from being reclaimed until the fallback/backfill runs.
- `started_at = COALESCE` preserves the original start across reclaims.
  Current code overwrites it **[V]** (`runner.py:229-234`); this is a fix.
- `finished_at = NULL` is defensive; a reclaimable row should not have it.

### 4.2 SQLite test form

SQLite does not have `make_interval`. Use a parameterized datetime computed in
Python or `datetime('now', :ttl_seconds || ' seconds')`:

```sql
UPDATE jobs
SET status='running',
    owner_id=:owner,
    lease_token=lease_token + 1,
    lease_expires_at=datetime('now', :ttl_seconds || ' seconds'),
    heartbeat_at=datetime('now'),
    started_at=COALESCE(started_at, datetime('now')),
    finished_at=NULL,
    error_message=NULL
WHERE id=:job_id
  AND (status='queued' OR (...))
RETURNING lease_token, status, checkpoint, output_file_path, store_path;
```

The production path should use DB time; SQLite tests may use Python time.

### 4.3 Claim result

The worker stores:

```python
@dataclass(frozen=True)
class Lease:
    job_id: int
    owner_id: str
    token: int
    expires_at: datetime
```

It passes the lease to `run_extraction`/`run_rollup` and to every write helper.
If the claim returns no row, the worker decides:

- terminal/paused -> exit;
- running with a fresh lease and not redelivered -> exit (duplicate dispatch);
- running with a fresh lease and redelivered -> bounded retry (see D9);
- queued but lost the race -> exit.

## 5. Heartbeat SQL

```sql
UPDATE jobs
SET heartbeat_at = now(),
    lease_expires_at = now() + make_interval(secs => :ttl),
    progress_at = CASE WHEN :progress_changed THEN now() ELSE progress_at END
WHERE id = :job_id
  AND owner_id = :owner
  AND lease_token = :token
  AND status IN ('running','paused','canceled')
RETURNING status, cancel_requested_at, pause_requested_at;
```

- No `lease_expires_at > now()` condition: renewal is allowed to revive an
  expired lease if no one has claimed it yet.
- It races safely with a claim: the token/owner predicate serializes.
- A 0-row result means the lease was lost or the row is terminal/paused with
  owner cleared. Stop.
- `progress_at` is set only when the main loop marked progress since the last
  heartbeat. A heartbeat without progress does not advance it.
- **The thread renews only while the main loop's in-process
  `last_progress_at` is within `JOB_PROGRESS_TIMEOUT_SECONDS` (recommended
  3600 s).** If the main loop is hung, the heartbeat stops renewing even though
  the process/thread is alive. This is the difference between liveness and
  progress.

Timing recommendation: TTL 600 s, heartbeat 60 s, reclaim grace 60 s, reaper
grace 60 s. A dead process recovers in ~11 min; a hung main loop recovers in
~71 min. See [`RELEASE_1_ARCHITECTURE_DECISIONS.md`](./RELEASE_1_ARCHITECTURE_DECISIONS.md)
section 1.D8 and 2.C.

## 6. Guarded write SQL

### 6.1 Progress/checkpoint

```sql
UPDATE jobs
SET completed_chunks = :cc,
    total_chunks = :tc,
    rows_written = :rw,
    current_chunk_start = :ccs,
    checkpoint = :checkpoint,
    preview = :preview,
    aggregation_result = :agg,
    output_file_path = :path,
    store_path = :store
WHERE id = :job_id
  AND owner_id = :owner
  AND lease_token = :token
  AND lease_expires_at > now()
  AND status IN ('running','paused','canceled')
RETURNING status, cancel_requested_at, pause_requested_at;
```

- `status IN ('paused','canceled')` allows the worker to persist the chunk it
  was already writing when a pause/cancel arrived.
- If 0 rows: `LeaseLost`. Do not retry the DB write; abort the run.
- The chunk event is inserted in the same transaction with the same guard.

### 6.2 Pause finalize

```sql
UPDATE jobs
SET status = 'paused',
    owner_id = NULL,
    lease_expires_at = NULL,
    finished_at = NULL
WHERE id = :job_id
  AND owner_id = :owner
  AND lease_token = :token
  AND lease_expires_at > now()
  AND status IN ('running','paused','canceled')
  AND cancel_requested_at IS NULL
RETURNING status;
```

If `cancel_requested_at` is not null, use the cancel finalize instead. A pause
must never win over a cancel.

### 6.3 Terminal finalize

```sql
UPDATE jobs
SET status = CASE
        WHEN status = 'canceled' OR cancel_requested_at IS NOT NULL THEN 'canceled'
        ELSE :final_status  -- 'completed' or 'failed'
    END,
    finished_at = now(),
    owner_id = NULL,
    lease_expires_at = NULL,
    error_message = :error_message,
    output_file_path = :path,
    store_path = :store,
    summary_file_path = :summary,
    counts_file_path = :counts,
    unmatched_file_path = :unmatched,
    rows_written = :rows,
    completed_chunks = :completed,
    total_chunks = :total,
    aggregation_result = :agg,
    completion_state = :completion_state,  -- complete|partial|unknown
    gap_count = :gap_count,
    gap_reason = :gap_reason
WHERE id = :job_id
  AND owner_id = :owner
  AND lease_token = :token
  AND lease_expires_at > now()
  AND status IN ('running','canceled')
RETURNING status;
```

- `:final_status` is `completed` or `failed`; cancel dominance overrides it.
- If 0 rows: abort; do not publish artifacts/S3.
- The terminal event is inserted in the same transaction.
- If `schedule_window_id` is set, update `schedule_windows` in the same
  transaction: `completed`/`failed`/`canceled`, `last_error`,
  `next_attempt_at`, `current_job_id`.
- `completion_state=partial` for skipped batches, rollup skips, BQ drops,
  canceled work, or preview; `complete` only when coverage and all sources are
  clean.

### 6.4 Failure before terminal

If an exception occurs and the lease is still valid:

- final status = `canceled` if cancel requested/status canceled, else `failed`;
- use the terminal finalize SQL with `final_status='failed'` and the error;
- clear owner/lease.

If the exception is `LeaseLost`, do **not** write failed. The row belongs to
someone else or is terminal.

## 7. API control SQL

### 7.1 Pause

```sql
UPDATE jobs
SET status = 'paused',
    pause_requested_at = COALESCE(pause_requested_at, now())
WHERE id = :job_id
  AND status IN ('queued','running')
RETURNING id, status, owner_id, pause_requested_at;
```

- Do not clear owner or bump token. The worker finalizes and clears.
- If `queued`, there is no owner; the job waits for resume.
- If `running`, owner remains until the worker acknowledges.

### 7.2 Resume

```sql
UPDATE jobs
SET status = 'queued',
    pause_requested_at = NULL,
    owner_id = NULL,
    lease_expires_at = NULL,
    lease_token = lease_token + 1,
    finished_at = NULL,
    error_message = NULL
WHERE id = :job_id
  AND status = 'paused'
RETURNING id, lease_token;
```

- Clear owner/bump token immediately; this fences an old worker that has not
  acknowledged the pause.
- The subsequent claim increments again. The double bump is harmless.
- Do not reset `checkpoint`; the new attempt resumes from it.

### 7.3 Cancel

```sql
UPDATE jobs
SET status = 'canceled',
    cancel_requested_at = COALESCE(cancel_requested_at, now()),
    finished_at = CASE
        WHEN owner_id IS NULL THEN COALESCE(finished_at, now())
        ELSE finished_at
    END,
    owner_id = CASE
        WHEN owner_id IS NULL THEN NULL
        ELSE owner_id
    END,
    lease_expires_at = CASE
        WHEN owner_id IS NULL THEN NULL
        ELSE lease_expires_at
    END
WHERE id = :job_id
  AND status NOT IN ('completed','failed','canceled')
RETURNING id, status, owner_id, cancel_requested_at;
```

- Any row with no owner (queued, fully paused, or a legacy running row) has no
  worker to finalize; set `finished_at` immediately.
- Running or pausing with an owner: keep owner/lease/token so the worker can
  finalize the partial artifact. `finished_at` is set by the worker/reaper.
- Do not bump the token for a running job; the worker's terminal write uses the
  same token and cancel dominance.
- If the worker is stuck, the cancel grace/reaper clears it.

### 7.4 Bulk/group cancel

Apply 7.3 per job in one transaction or bounded batches. Do not use a bulk ORM
`status='canceled'` assignment. Return per-job skipped reasons as the current
bulk endpoint does.

### 7.5 Retry

Create a new row; do not update the old. Set `retry_of=:old_id`, status
`queued`, owner/lease/token default. If D3 resumes, copy `checkpoint` and
`chunk_hours`; ensure the copied checkpoint includes the old
`artifact_path`/`store_path` (adding them from the old row if the legacy
checkpoint lacks them). Do **not** copy `output_file_path`/`store_path` as the
new job's published pointers; the new attempt publishes its own after seeding
from the checkpoint. If D3 restarts, leave the checkpoint null.

## 8. Reaper SQL

### 8.1 Running

```sql
UPDATE jobs
SET status = CASE
        WHEN cancel_requested_at IS NOT NULL OR status = 'canceled' THEN 'canceled'
        ELSE 'failed'
    END,
    owner_id = NULL,
    lease_expires_at = NULL,
    lease_token = lease_token + 1,
    finished_at = now(),
    completion_state = CASE
        WHEN cancel_requested_at IS NOT NULL OR status = 'canceled' THEN 'partial'
        ELSE 'unknown'
    END,
    error_message = :message
WHERE id = :job_id
  AND status = 'running'
  AND (
      (lease_expires_at IS NOT NULL
       AND lease_expires_at < now() - make_interval(secs => :reaper_grace))
      OR (progress_at IS NOT NULL
          AND progress_at < now() - make_interval(secs => :progress_timeout))
  )
RETURNING id, status;
```

- `reaper_grace` is a short value (recommended 60 s). The 60-minute value is the
  **progress timeout**, not the post-expiry grace.
- The progress branch is defense-in-depth: even if the heartbeat thread were
  buggy and kept renewing, stale `progress_at` lets the reaper fence the job.
- `progress_at NULL` on legacy rows falls back to the lease/event behavior.
- The heartbeat stops renewing at the progress timeout, so a hung main loop
  reaches this branch.
- If `schedule_window_id` is set, update the window to `failed`/`canceled`.
- If 0 rows, another actor won; skip.
- Do not select all rows in one long transaction. Bound the batch and update
  per row or in small batches.

### 8.2 Canceled with owner

The grace is measured from the cancel request, not from lease expiry: a live
worker that keeps heartbeating must still be fenced after the cancel grace.

```sql
UPDATE jobs
SET owner_id = NULL,
    lease_expires_at = NULL,
    lease_token = lease_token + 1,
    finished_at = COALESCE(finished_at, now())
WHERE id = :job_id
  AND status = 'canceled'
  AND owner_id IS NOT NULL
  AND (
      cancel_requested_at IS NULL
      OR cancel_requested_at < now() - make_interval(secs => :cancel_grace)
      OR lease_expires_at IS NULL
      OR lease_expires_at < now() - make_interval(secs => :cancel_grace)
  )
RETURNING id;
```

- `cancel_requested_at IS NULL` covers a legacy canceled row with an owner;
  there is no request timestamp to wait for.
- Keeps `status='canceled'`.
- The reaper must not truncate a file that a live worker may still be writing.
  Recommended: copy the first `checkpoint.file_offset` bytes into a new
  "recovered" attempt path, publish that path in a guarded update, then clear
  the owner. If the copy fails, leave the old path or clear it and record an
  error. The old file becomes an orphan cleanup candidate.
- If the copy is not possible, the reaper can hide the artifact pointer rather
  than publish a file with an uncommitted suffix.

### 8.3 Paused with owner

```sql
UPDATE jobs
SET owner_id = NULL,
    lease_expires_at = NULL,
    lease_token = lease_token + 1
WHERE id = :job_id
  AND status = 'paused'
  AND owner_id IS NOT NULL
  AND (
      pause_requested_at < now() - make_interval(secs => :pause_grace)
      OR lease_expires_at IS NULL
      OR lease_expires_at < now() - make_interval(secs => :pause_grace)
  )
RETURNING id;
```

- Keeps `status='paused'`; the job is resumable.
- Bumping the token fences a late worker.
- A paused row with no owner is the normal acknowledged state; this cleanup only
  handles a worker that never acknowledged.

### 8.4 Legacy event fallback

During mixed versions, old workers have `owner_id=NULL`, `lease_expires_at=NULL`.
The reaper can use the existing event-age query behind
`JOB_RECLAIM_MODE=event`:

```sql
SELECT id FROM jobs
WHERE status='running'
  AND COALESCE(
      (SELECT max(ts) FROM job_events WHERE job_id=jobs.id),
      started_at
  ) < now() - :stale_job_interval
```

Do not run this in lease mode; it would fail rows that a new worker owns.

## 9. Transaction requirements

| Operation | Transaction |
|---|---|
| Claim | Single `UPDATE ... RETURNING`, commit immediately. No file I/O inside. |
| Heartbeat | Single `UPDATE`, commit immediately. |
| Progress | `UPDATE` + `INSERT job_events` in one transaction. Flush/fsync the file **before** the transaction. |
| Pause/terminal | `UPDATE` + event in one transaction; S3 after commit. |
| Pause/resume/cancel API | Single `UPDATE ... RETURNING` + audit row in one transaction. |
| Reaper | Per-row conditional `UPDATE` + event + alert in one transaction; bounded batch. |
| Outbox insert | Same transaction as the job row(s). |
| Outbox publish | Claim row -> commit -> publish -> mark published (separate transaction). Duplicate on crash is expected. |

The file write is intentionally outside the DB transaction: you cannot make a
filesystem write and a database commit atomic. The checkpoint design (fsync
first, then DB commit, copy only the committed prefix on resume) handles the
window.

## 10. Migration sequencing

Proposed order (none created in this task):

1. `0032_job_ownership_and_completion.py`
   - add `owner_id`, `lease_token`, `lease_expires_at`, `heartbeat_at`,
     `progress_at`, `cancel_requested_at`, `pause_requested_at`;
   - add `completion_state`, `gap_count`, `gap_reason`, `retry_of`;
   - add `ix_jobs_lease`, `ix_jobs_progress`, `ix_jobs_retry_of`
     (and optionally `ix_jobs_owner`);
   - no backfill: existing rows keep column defaults.
2. `0033_job_artifact_paths.py`
   - add `store_path`, `spec_fingerprint`, `checkpoint_version`.
3. `0034_job_dispatch_outbox.py`
   - create `job_dispatch_outbox` + unique/index;
   - **no rows** in P1. Existing queued jobs are reconciled when the dispatcher
     is enabled in P6, not backfilled in the schema migration.
4. `0035_schedule_windows.py`
   - create `schedule_windows`; add `jobs.schedule_window_id`,
     `jobs.attempt_no`; unique window/attempt and one-active-job indexes;
   - empty table in P1.
5. `0036_s3_attempt_publication.py`
   - add S3 attempt fields.
6. `0037_status_constraints.py`
   - add CHECKs for `jobs.status`, `completion_state`,
     `schedule_windows.status` after audit; **P9, not P1**.
7. Optional Release 2: richer gap taxonomy/backfill.

Deployment must run migrations before the new code, as `deploy.sh` already does
**[V]** (`deploy.sh:21-27`). Additive columns are safe for old code. Do not
drop or rename existing columns.

### 10.1 Backfill (P2 activation, not P1)

P1 does **not** run this backfill. Existing rows keep their column defaults, and
no runtime code reads `progress_at` until P2. Use this only as the P2 activation
baseline, after all writers are on the new version.

```sql
UPDATE jobs
SET owner_id = NULL,
    lease_token = 0,
    lease_expires_at = NULL,
    heartbeat_at = COALESCE(started_at, updated_at),
    progress_at = COALESCE(started_at, updated_at),
    cancel_requested_at = NULL,
    pause_requested_at = NULL,
    store_path = NULL,
    retry_of = NULL,
    completion_state = 'unknown',
    gap_count = 0,
    gap_reason = NULL,
    schedule_window_id = NULL,
    attempt_no = 1,
    s3_attempt_token = 0,
    s3_uploading_at = NULL,
    s3_published_attempt = NULL,
    s3_manifest_uri = NULL
WHERE owner_id IS NULL;
```

Notes:

- Do not set `cancel_requested_at` for historical canceled rows; it would
  invent a request. Leave null.
- For a running job at migration time, `heartbeat_at=started_at` is historical,
  not proof of life. Do not enable lease-based reaping until all workers are
  new. Use the event fallback during the mixed period.
- Outbox backfill (P6, when the dispatcher is enabled):

```sql
INSERT INTO job_dispatch_outbox (job_id, task_name, status, next_attempt_at)
SELECT id, 'logvault.run_job', 'pending', now()
FROM jobs j
WHERE j.status = 'queued'
  AND NOT EXISTS (
      SELECT 1 FROM job_dispatch_outbox o
      WHERE o.job_id = j.id AND o.task_name = 'logvault.run_job'
  );
```

- Schedule duplicate audit (informational; the ledger starts with new scans and
  does not auto-backfill historical windows):

```sql
SELECT created_by, start_epoch, count(*)
FROM jobs
WHERE created_by LIKE 'schedule:%'
GROUP BY created_by, start_epoch
HAVING count(*) > 1;
```

Do not auto-delete historical duplicates. Resolve manually or document them.
The new `schedule_windows` ledger prevents future duplicates; legacy jobs have
`schedule_window_id=NULL` and remain readable.

## 11. Edge cases

### 11.1 Database clock vs worker clock

Use DB `now()` for lease acquisition, renewal, and expiry. The worker may use
Python time for log timestamps and `finished_at` if preferred, but not for
fencing. If the API and DB clocks differ, the DB is authoritative.

### 11.2 Lease expiry during a long operation

The heartbeat thread keeps the lease alive while the main execution loop makes
progress. If the thread itself dies, progress writes stop at expiry and the
worker aborts. If the main loop hangs but the thread lives, renewal stops at
`JOB_PROGRESS_TIMEOUT_SECONDS`; the lease expires and the reaper recovers the
job. A worker that cannot renew cannot prove ownership.

### 11.3 Token overflow

`bigint` is sufficient. A job would need billions of claims to overflow. If it
ever approaches, treat it as a corrupted row.

### 11.4 Legacy rows with NULL lease

Claim's `running` reclaim branch requires `lease_expires_at IS NOT NULL`. An
old running row with NULL lease is not reclaimable by the new path; the reaper
uses the event fallback until it is terminal. This prevents stealing a live old
worker.

### 11.5 Reaper vs redelivery

Both are conditional updates. If redelivery claims first, the reaper's
`status='running' AND lease expired` predicate fails because the token/lease
changed. If the reaper fails first, the claim sees failed/canceled and exits.

### 11.6 API vs worker terminal write

Both are conditional. The API cancel only changes non-terminal rows. The
worker terminal write only changes running/canceled. If they race, Postgres
serializes; cancel dominance ensures the worker chooses canceled if it sees the
request.

### 11.7 Pause vs resume

Pause leaves the owner/token so the worker can finalize. Resume clears the
owner and bumps the token. If resume happens first, the worker's progress write
sees queued/owner null/stale token and aborts. If the worker finalizes pause
first, resume claims a clean paused row. Both are safe.

### 11.8 Cancel vs pause

Cancel dominates. If both are requested, the worker finalizes canceled. The
pause finalize condition includes `cancel_requested_at IS NULL`.

### 11.9 Rollup

Rollup uses the same lease. It must not write `status='running'` directly. Its
progress writes use the same guard. Its cancel path is the same terminal
finalize with cancel dominance.

### 11.10 S3

The job lease does not protect S3 after completion. Use `s3_attempt_token` and
`s3_uploading_at`; see [`ARTIFACT_PUBLICATION.md`](./ARTIFACT_PUBLICATION.md).

### 11.11 SQLite

SQLite serializes writes; it can prove the SQL syntax and basic guards, not the
race. Use Postgres for concurrency acceptance.

## 12. Mixed-version rules

| Combination | Safe? | Rule |
|---|---|---|
| Old API + old worker | Yes (current) | Baseline. |
| New API + old worker, `JOB_LEASE_MODE=observe` | Mostly | API may write new fields but must not require tokens. Cancel-fencing off. |
| New API + old worker, enforcement on | **No** | Old worker ignores tokens and can overwrite. |
| New worker + old API | Mostly | New worker claims/leases; old API cancel is unprotected. Keep cancel-fence off until API is new. |
| New API + new worker, observe | Safe | Lease written but not enforced. |
| New API + new worker, enforce | Safe | Target. |
| Mixed new workers, all new code but different versions | Safe if the schema/flags are compatible | Use flags; do not change SQL semantics mid-rollout. |

Never enable lease-based reclaim while an old worker may own a job. It has no
lease and cannot be fenced.

The schedule ledger has an additional mixed-version rule: stop/replace any old
`-B` beat before enabling `SCHEDULE_WINDOWS_ENABLED`. Old beat code inserts jobs
without ledger rows; the ledger cannot deduplicate what it never sees.

## 13. Open decisions

- D1/D2: derived vs persisted `pausing`/`canceling`.
- D3: retry resume vs restart.
- D8: TTL/heartbeat/reclaim/progress/reaper grace values. Recommendation:
  600/60/60/3600/60.
- D9: Celery redelivery retry, visibility timeout, runtime limit, result expiry.
- D10: minimum completeness in Release 1. Recommendation: include.
- D11: `schedule_windows` ledger. Recommendation: include.
- D13: status/completion/schedule CHECK timing.
- Whether `started_at` should be preserved across reclaims (recommend yes) or
  reset to the new attempt (current behavior). Preserving is better for ETA and
  audit; the attempt token distinguishes runs.
- Whether to add `ix_jobs_owner`; recommend yes if support queries need it.
