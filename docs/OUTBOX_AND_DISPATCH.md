# Outbox and Dispatch

Status: design proposal for Release 1. Not implemented.

Scope: job creation -> broker publish -> Celery delivery -> worker claim.
Companion: [`WORKER_OWNERSHIP.md`](./WORKER_OWNERSHIP.md) for the claim that
makes duplicate delivery safe.

Legend: **[V]** verified current behavior, **[P]** proposed, **[A]** unverified
assumption, **[D]** decision needed.

## 1. Current flow and gap

### 1.1 Verified flow

1. `create_job` validates, inserts `Job(status="queued")`, audits, commits
   **[V]** (`api/app/routers/jobs.py:263-327`).
2. After the commit, `dispatch_job(job.id)` calls
   `send_task("logvault.run_job", args=[job_id])` **[V]**
   (`tasks_client.py:17-22`; `jobs.py:326`).
3. Batch/group: all jobs commit, then a loop dispatches each; a failure aborts
   later dispatches **[V]** (`jobs.py:474-478`; `groups.py:216-225`).
4. Schedule scan: inserts jobs, updates `last_run_at`, commits, then dispatches
   each with a per-job `try/except` **[V]** (`scheduler.py:140-188`).
5. Retry/rollup create a new job, commit, then dispatch **[V]**
   (`jobs.py:628-655`, `953-1003`).
6. `run_job` loads the job, checks disk, and calls the runner **[V]**
   (`tasks.py:139-177`).

### 1.2 The gap

The job row and the dispatch intent are not atomic. If the broker is
unreachable after the commit:

- the API returns 500, but the row exists as `queued`;
- the client has no id to reconcile; a retry creates a second job;
- in a batch, earlier jobs are published and later jobs stay queued;
- there is no sweeper for `queued` rows; the reaper only handles `running`.

This is a verified structural gap **[V]**. It is not a claim that every broker
failure produces a duplicate; it is the absence of a durable intent.

## 2. Requirements

1. A committed job must eventually be published, even if the API process dies
   or the broker is down.
2. A broker failure must not make the create request look successful when the
   job will never run, nor leave the client unable to reconcile.
3. Batch/group creation must be all-or-nothing for the job rows and their
   dispatch intents.
4. Duplicate publishes must be harmless.
5. A lost publish after the outbox mark must be recoverable.
6. The solution must use the existing Postgres + Celery/Redis stack; no new
   queue, broker, or library.
7. Monitoring must show pending age, attempts, and terminal failures.

## 3. Options

### Option A - direct dispatch (current)

- Simple.
- No durability across process death or broker outage.
- Batch partial dispatch.
- Rejected for Release 1.

### Option B - queued-job sweeper only

- A beat task scans `status='queued'` older than N seconds and dispatches.
- No new table.
- Recovers any orphaned queued job, including manual DB inserts.
- Cannot record a dispatch attempt/error atomically with the job; needs
  additional columns or an event to avoid dispatching a job that is merely
  waiting for a busy worker. Duplicate dispatch is safe, so this is acceptable.
- Less auditability than an outbox.

### Option C - transactional outbox

- Insert a `job_dispatch_outbox` row in the same transaction as the job.
- A dispatcher claims due rows, publishes, marks published/failed with
  attempts/backoff.
- Strong durability and audit.
- Extra table and dispatcher.
- At-least-once publish; duplicate execution prevented by the claim.

### Recommendation

**Option C, with an inline fast path and a queued-job reconciliation fallback.**

- The outbox is the durable intent.
- After commit, the API may attempt an immediate publish and mark the row
  published. If that fails, the dispatcher picks it up. This keeps current
  latency for the common case.
- A periodic reconciliation finds queued jobs whose outbox row is missing or
  stale-published and reopens/inserts a row. This covers old API instances,
  manual inserts, and a message lost after the publish mark.
- A plain queued-job sweeper is a subset of the reconciliation; no separate
  mechanism is needed.

## 4. Outbox schema

```sql
CREATE TABLE job_dispatch_outbox (
  id bigserial PRIMARY KEY,
  job_id integer NOT NULL,
  task_name varchar(80) NOT NULL DEFAULT 'logvault.run_job',
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status varchar(16) NOT NULL DEFAULT 'pending',  -- pending|published|failed
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

Add `CHECK (status IN ('pending','published','failed'))` and
`CHECK (attempts >= 0)` in the migration. The table is additive and can be
dropped without affecting job history.

Notes:

- `payload` holds `{}` for `run_job`; for S3 it holds
  `{"attempt_token": N}` and optional artifact paths. Keep it small.
- `UNIQUE (job_id, task_name)` prevents duplicate intents for the same logical
  action. A retry creates a new job id, so it gets a new row.
- `status='failed'` means "gave up after max attempts"; it is visible and
  manually retryable.
- `locked_by`/`locked_until` support a portable claim without relying on
  `FOR UPDATE SKIP LOCKED` in SQLite tests.

## 5. Atomic creation

### 5.1 Single job

In one transaction:

1. Insert `jobs` row.
2. Insert `job_dispatch_outbox(job_id, task_name='logvault.run_job')`.
3. Audit.
4. Commit.

Then, after commit, attempt the inline fast path:

```
publish(job_id)
  -> on success: mark outbox published
  -> on failure: leave pending; log/metric
```

If the inline publish succeeds but the mark fails, the dispatcher republishes;
duplicate is safe.

### 5.2 Batch and group

- Validate all plans first (existing behavior).
- Insert the group (if any), all jobs, and all outbox rows.
- Audit all.
- Commit once.
- After commit, attempt inline dispatch for each; failures leave rows pending.

The all-or-nothing property now includes the dispatch intents. A validation
failure rolls back everything.

### 5.3 Schedule scan

- Compute owed windows.
- For each window, insert the job and outbox row in the same transaction as
  `last_run_at` (or per schedule).
- Use the partial unique schedule window (Release 1 M5) and
  `ON CONFLICT DO NOTHING`.
- Commit.
- Dispatch after commit or let the dispatcher handle it. Do not dispatch inside
  the transaction.

### 5.4 Retry and rollup

- New job + outbox row in one transaction.
- No direct `dispatch_job` required; the inline fast path is optional.
- `retry_of` links the new job if D3 approves.

## 6. Dispatcher

### 6.1 Task

A Celery beat task, e.g. `logvault.dispatch_outbox`, every
`OUTBOX_DISPATCH_INTERVAL_SECONDS` (proposed 30 s).

Algorithm:

1. Claim due rows:

```sql
UPDATE job_dispatch_outbox
SET locked_by = :owner,
    locked_until = now() + :lock_ttl,
    status = 'pending'
WHERE id IN (
  SELECT id
  FROM job_dispatch_outbox
  WHERE status = 'pending'
    AND next_attempt_at <= now()
    AND (locked_until IS NULL OR locked_until < now())
  ORDER BY id
  LIMIT :batch
  FOR UPDATE SKIP LOCKED
)
RETURNING id, job_id, task_name, payload, attempts;
```

On SQLite tests, use a single-threaded claim without `SKIP LOCKED`:
`UPDATE ... WHERE id = (SELECT ... LIMIT 1) AND (locked_until ...) RETURNING`.

2. Commit the claim.
3. For each row, publish:

```python
if task_name == "logvault.run_job":
    send_task(task_name, args=[job_id], task_id=f"dispatch-{outbox_id}")
else:
    # e.g. logvault.upload_job_s3(job_id, attempt_token=..., artifacts=...)
    send_task(task_name, args=[job_id], kwargs=payload,
              task_id=f"dispatch-{outbox_id}")
```

4. On success:

```sql
UPDATE job_dispatch_outbox
SET status='published', published_at=now(), locked_by=NULL, locked_until=NULL,
    last_error=NULL
WHERE id=:id;
```

5. On failure:

```sql
UPDATE job_dispatch_outbox
SET attempts=attempts+1,
    next_attempt_at=now() + :backoff,
    locked_by=NULL, locked_until=NULL,
    last_error=:error,
    status=CASE WHEN attempts+1 >= :max_attempts THEN 'failed' ELSE 'pending' END
WHERE id=:id;
```

Backoff: `min(300, 2 ** attempts)` seconds, with jitter.

6. A row whose `attempts >= max` becomes `failed` and raises a metric/alert.

### 6.2 Lock expiry

If the dispatcher crashes after claiming but before publishing, `locked_until`
expires and another dispatcher picks it up. If it crashes after publishing but
before marking, the row is republished; duplicate is safe.

### 6.3 Exactly-once wording

The outbox provides **at-least-once publish**. Execution is **at-most-once**
per claim because of the lease. This is the correct guarantee for this system.

## 7. Inline fast path

Why keep it:

- Current create latency is low; a 30 s dispatcher delay for every job is a
  visible regression.
- The outbox row is the durability; the inline publish is an optimization.

Rules:

- Inline publish happens after the commit.
- If it succeeds, mark the outbox row published.
- If the mark fails, leave it pending; the dispatcher republishes.
- If the publish fails, leave pending; the dispatcher retries.
- The API response does not depend on the inline publish. It returns the
  committed job (201) regardless. Do not return 500 after a commit.

This changes the current behavior: a broker outage no longer produces a 500
with an orphaned row. It produces a 201 with a queued job and a pending
outbox row. That is the intended reliability improvement.

**Residual:** if the HTTP response is lost after the commit, a client retry can
create a second job. The outbox does not solve that. Release 2 should add an
`Idempotency-Key` for create/batch/group. Release 1 acceptance is "no duplicate
execution of the same job", not "no duplicate job creation".

## 8. Duplicate delivery and Celery

### 8.1 Existing settings

- `task_acks_late=True` **[V]** (`celery_app.py:20`).
- `task_reject_on_worker_lost=True` **[V]**.
- `worker_prefetch_multiplier=1` **[V]**.
- `task_track_started=True`, `result_expires=3600` **[V]**.
- Redis broker/result backend **[V]** (`docker-compose.yml:68-69`).
- No `visibility_timeout` set **[V]**. Celery 5.4's Redis default is **3600 s**
  **[V]** (official Celery 5.4 docs).
- No `task_time_limit`/`task_soft_time_limit` **[V]**. A hung process can hold a
  worker slot indefinitely.

Revised configuration:

```python
broker_transport_options = {"visibility_timeout": 3600}
result_backend_transport_options = {"visibility_timeout": 3600}
task_acks_late = True
task_reject_on_worker_lost = True
worker_prefetch_multiplier = 1
task_acks_on_failure_or_timeout = True
```

Also consider `ignore_result=True` for `run_job`, or raise `result_expires` to
exceed the maximum job duration. The DB is the source of truth; the Celery
result is not.

A high soft/hard runtime limit is recommended as a backstop for a hung process
that holds a slot; this is a business decision (D9). A hard limit kills the
child and redelivery resumes from the checkpoint. A soft limit must be caught by
the runner and leave a recoverable state.

### 8.2 Long jobs and redelivery

A multi-hour job can be redelivered by Redis while the original worker is
still running. This is normal, not exceptional. The worker must handle it:

| Situation | Behavior |
|---|---|
| Job queued | First claim wins; duplicates exit. |
| Job running, fresh lease, not redelivered | Duplicate dispatch; exit and ack. The original owns. |
| Job running, fresh lease, redelivered | Do not steal. Schedule a bounded retry for the remaining lease time; do not ack the only recovery path. |
| Job running, expired lease, redelivered | Claim; token increments. |
| Job terminal/paused | Exit and ack. |
| Lease lost during run | Abort; no terminal write. |

Recommended `run_job` shape:

```python
@celery.task(bind=True, name="logvault.run_job")
def run_job(self, job_id: int) -> None:
    redelivered = bool(self.request.redelivered)
    lease = acquire(...)
    if lease is None:
        state = read_job_state(...)
        if redelivered and state.status == "running" and state.lease_valid:
            raise self.retry(countdown=min(state.remaining + 5, 300), max_retries=3)
        return
    ...
```

If `max_retries` is exhausted, return (ack) and let the reaper handle the dead
owner. The reaper fails after the progress timeout + lease expiry + reaper
grace; a manual retry is required. Do not retry forever.

### 8.3 Visibility timeout

Celery 5.4's Redis default is 3600 s **[V]**. Make it explicit:

```python
broker_transport_options = {"visibility_timeout": 3600}
result_backend_transport_options = {"visibility_timeout": 3600}
```

Operational consequence: any job longer than one hour can be redelivered. The
claim/token makes that safe, but the redelivered task must not steal a live
lease. Do not raise the timeout to 24 h as a substitute for fencing; it delays
crash recovery and still does not solve multiple owners. This is D9.

### 8.4 Acknowledgement on failure

- `task_acks_on_failure_or_timeout` defaults to true; keep it true. A failed job
  is recorded on the row; requeueing the same message would loop.
- If `_mark_failed` itself cannot reach the DB, raise; the message may be acked
  and the job stays running until the reaper. That is acceptable and visible.
- A `LeaseLost` exit is normal; return, do not raise.

### 8.5 Duplicate execution guarantees

- The claim is the gate. No other dedupe mechanism is required.
- A deterministic `task_id` (`dispatch-<outbox_id>`) is useful for tracing but
  is not a guarantee that Celery/Redis dedupes. Do not rely on it.
- Do not add a distributed lock around the task; the DB claim is the lock.

## 9. Orphaned queued jobs

Two recovery paths:

### 9.1 Outbox reconciliation

Every `OUTBOX_RECONCILE_SECONDS` (proposed 300 s):

- Find `status='queued'` jobs older than `QUEUED_GRACE` (proposed 5 min).
- For each:
  - if no outbox row for `logvault.run_job`, insert one;
  - if the outbox row is `published` but `published_at` is older than the
    grace and the job has never started (`started_at IS NULL`), reset it to
    `pending` with a new attempt.
- This covers a message lost after the publish mark, an old API instance that
  did not write an outbox row, and manual DB inserts.
- A duplicate publish is harmless; the job may be waiting for a busy worker, in
  which case the duplicate exits at claim.

### 9.2 Migration backfill

On the outbox migration, insert pending rows for all existing `status='queued'`
jobs with no row. This prevents a deploy from stranding pre-existing queued
jobs.

## 10. Monitoring

Metrics/logs:

- `outbox_pending_count`
- `outbox_pending_age_seconds` (oldest pending)
- `outbox_publish_total{result=ok|error}`
- `outbox_attempts_total`
- `outbox_failed_total`
- `outbox_duplicate_publish_total` (a republish after a mark)
- `queued_job_age_seconds` (oldest queued)
- `queued_job_without_outbox_total`
- `queue_reconcile_total{action=insert|reopen}`

Alerts:

- pending outbox older than 5 min;
- any `failed` outbox row;
- queued job older than 10 min with no outbox or a stale published row;
- a spike in duplicate publishes (may indicate mark failures).

Logs include `outbox_id`, `job_id`, `task_name`, `attempts`, `result`,
`error`. Do not log payload secrets (there are none for run_job; S3 payload is
ids/paths, not credentials).

## 11. Batch/group and schedule specifics

- Batch/group validation is already all-or-nothing; the outbox insert must be
  in the same transaction. A failure to insert an outbox row rolls back all
  jobs.
- Schedule scan uses the `schedule_windows` ledger; insert/update the window,
  job, and outbox row in one transaction with the scan lock. A failure rolls
  back the window, so it is retried next tick.
- `schedule_windows` unique `(schedule_id, window_key)` and the one-active-job
  partial index are the correctness guards: two beats cannot create two active
  jobs/outbox rows for one window. The scan lock is an efficiency/overlap guard.

## 12. S3 dispatch

The outbox is generic enough for `logvault.upload_job_s3`:

- API retry claims the S3 attempt, then inserts/updates an outbox row
  (`task_name='logvault.upload_job_s3'`, payload `{attempt_token}`) in the same
  transaction.
- The dispatcher publishes with the same retry/backoff.
- `UNIQUE (job_id, task_name)` means one pending S3 row per job; a new retry
  resets it to pending with a new token.
- If the inline fast path is used, the same duplicate rules apply.

Alternatively, call `dispatch_s3_upload` directly after the attempt claim; the
outbox is more durable and consistent. Recommend outbox.

## 13. Testing

See [`RELEASE_1_TEST_PLAN.md`](./RELEASE_1_TEST_PLAN.md), tests T13-T17 and
T24-T27:

- broker down at create -> job+outbox committed, API 201, dispatch later;
- dispatcher crash after publish before mark -> republish, one execution;
- batch failure -> no jobs, no outbox;
- schedule two scans -> one job/outbox;
- queued reconciliation -> one row;
- duplicate delivery -> one claim;
- S3 retry -> one attempt.

## 14. Rollout and flags

- `DISPATCH_MODE=direct` (current), `dual` (new API writes outbox and still
  direct-dispatches), `outbox` (dispatcher only).
- Deploy the table + dispatcher first with `direct`.
- Set `dual` on the API; verify outbox rows and dispatcher.
- Set `outbox` after all API instances are new.
- Keep `dispatch_job` for rollback.
- If rolling back, set `direct`; pending outbox rows can be drained manually or
  left for the dispatcher if it remains running.

## 15. Open decisions

- D6: outbox vs sweeper. Recommendation: outbox + inline fast path.
- D9: visibility timeout / retry bound.
- Inline fast path on/off per route. Recommendation: on for single/batch/group,
  optional for schedule (the dispatcher is enough).
- Outbox retention: keep published rows for 7-30 days for audit, then delete.
  Recommendation: 30 days.
- Whether to use `FOR UPDATE SKIP LOCKED` (Postgres) only or the portable lock
  columns. Recommendation: use `SKIP LOCKED` on Postgres, lock columns as the
  fallback/test path.
- Whether S3 dispatch uses the same outbox or a separate table. Recommendation:
  same table with `task_name`.
