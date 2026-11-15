# Release 1 Migration Plan

Status: design only. No migration has been created or executed. No database
schema was changed.

This document reviews every proposed schema change against the existing
PostgreSQL/Alembic model. SQLite is used by tests, not production.

## 1. Evidence and assumptions

- Production is PostgreSQL 16 in compose **[C]** (`docker-compose.yml:5`).
- The systemd installer uses a local PostgreSQL service; version is not pinned
  in the repo **[C/A]** (`install-prod.sh`).
- Alembic runs inside a transaction by default **[C]**
  (`api/migrations/env.py`).
- `deploy.sh` runs `alembic upgrade head` before recreating services **[C]**
  (`deploy.sh:21-27`).
- API/worker tests use SQLite **[T]** (`api/tests/conftest.py`;
  `worker/tests/conftest.py`); there is no Postgres migration test.
- The worker mirrors the API table with SQLAlchemy Core
  **[S]** (`worker/app/db.py:36-74`); every field must be added there.
- No `jobs.status` CHECK exists today **[S]** (`models.py:44-97`; migrations
  0001-0031).

## 2. Migration inventory

| Revision | Purpose | Additive? | Data backfill? | Risk |
|---|---|---|---|---|
| `0032_job_ownership_and_completion.py` | lease/heartbeat/progress, control requests, completion/gap, retry lineage | Yes | None (column defaults only) | Low |
| `0033_job_artifact_paths.py` | `store_path`, `spec_fingerprint`, `checkpoint_version` | Yes | None | Low |
| `0034_job_dispatch_outbox.py` | outbox table | Yes | None in P1; P6 reconciliation | Low |
| `0035_schedule_windows.py` | ledger + job window link | Yes | None in P1; P7 seeding | Medium |
| `0036_s3_attempt_publication.py` | S3 attempt fields | Yes | None | Low |
| `0037_status_constraints.py` | CHECKs | Constraint | Audit first; P9 | Medium |

Run order is linear. `deploy.sh` uses `head`; milestone branches must target
explicit revisions or ship the additive bundle once after audits. Do not assume
`upgrade 0035` skips `0034`.

## 3. `jobs` - ownership and completion (0032)

| Field | Purpose | Type | Null/default | Backfill | Index | Unique/FK | Old worker | Rollback |
|---|---|---|---|---|---|---|---|---|
| `owner_id` | Current attempt identity | `varchar(128)` | NULL | NULL | `0032b` partial `(owner_id)` | none | Ignores | Leave column |
| `lease_token` | Per-job fence | `bigint` | NOT NULL DEFAULT 0 | 0 | via `0032b` `(status,lease_expires_at)` | none | Ignores | Leave |
| `lease_expires_at` | Lease expiry (DB time) | `timestamptz` | NULL | NULL | `0032b` partial `(status,lease_expires_at)` | none | Ignores | Leave |
| `heartbeat_at` | Last renewal | `timestamptz` | NULL | None in P1; P2 baseline | none | none | Ignores | Leave |
| `progress_at` | Last main-loop progress | `timestamptz` | NULL | None in P1; P2 baseline | `0032b` partial `(status,progress_at)` | none | Ignores | Leave |
| `cancel_requested_at` | Cancel request marker | `timestamptz` | NULL | NULL | none | none | Ignores | Leave |
| `pause_requested_at` | Pause request marker | `timestamptz` | NULL | NULL | none | none | Ignores | Leave |
| `completion_state` | `unknown/complete/partial` | `varchar(16)` | NOT NULL DEFAULT `'unknown'` | Default only | none in P1 | CHECK in 0037 | Ignores | Leave |
| `gap_count` | Gap units | `integer` | NOT NULL DEFAULT 0 | Default only | none | CHECK `>=0` optional | Ignores | Leave |
| `gap_reason` | Human/machine reason | `text` | NULL | NULL | none | none | Ignores | Leave |
| `retry_of` | Retry lineage job id | `integer` | NULL | NULL | deferred P2/P9 partial `(retry_of)` | none (no FK) | Ignores | Leave |

### 3.1 Backfill (P2 activation, not P1)

P1 does not backfill. Existing rows keep column defaults until P2.

```sql
UPDATE jobs
SET owner_id = NULL,
    lease_token = 0,
    lease_expires_at = NULL,
    heartbeat_at = COALESCE(started_at, updated_at),
    progress_at = COALESCE(started_at, updated_at),
    cancel_requested_at = NULL,
    pause_requested_at = NULL,
    completion_state = 'unknown',
    gap_count = 0,
    gap_reason = NULL;
```

For large tables, batch by id. Do not guess historical completion beyond the
unambiguous skipped-batch `error_message` pattern; leave `unknown`.

### 3.2 Compatibility

- Old API/worker ignore fields; old jobs remain readable.
- New worker on old schema is **not** safe; migrate first.
- Old worker on new schema is safe until fencing enforcement; it does not write
  leases.
- Rollback: leave fields; old code ignores them. Do not drop.

## 4. `jobs` - artifact lineage (0033)

| Field | Purpose | Type | Null/default | Backfill | Index | Unique/FK | Old worker | Rollback |
|---|---|---|---|---|---|---|---|---|
| `store_path` | Published attempt-scoped distinct store | `text` | NULL | NULL | none | none | Ignores; old rollup uses canonical | Leave; copy/link shim for old rollup |
| `spec_fingerprint` | Canonical job-spec hash | `varchar(64)` | NULL | NULL | none | none | Ignores | Leave |
| `checkpoint_version` | Checkpoint protocol version | `integer` | NOT NULL DEFAULT 1 | Default only | none | none | Ignores | Leave |

`retry_of` is added by `0032`, not `0033`.

- No FK because jobs are deleted by customer cleanup and historical lineage
  should not block deletion.
- Old rollup/cleanup cannot see attempt stores; rollback needs a copy/link
  shim or keep the new worker.
- `store_path` is set only after a lease-guarded publication.

## 5. `job_dispatch_outbox` (0034)

| Field | Purpose | Type | Null/default | Backfill | Index | Unique/FK |
|---|---|---|---|---|---|---|
| `id` | Row id | `bigserial` | PK | - | PK | - |
| `job_id` | Job to dispatch | `integer` | NOT NULL | from queued jobs | via unique/due | no FK |
| `task_name` | Celery task | `varchar(80)` | NOT NULL DEFAULT `logvault.run_job` | - | unique | `UNIQUE(job_id,task_name)` |
| `payload` | Task kwargs | `jsonb`/`JSON` | NOT NULL DEFAULT `{}` | - | none | none |
| `status` | `pending/published/failed` | `varchar(16)` | NOT NULL DEFAULT `pending` | - | `(status,next_attempt_at)` | CHECK in 0037 |
| `attempts` | Publish attempts | `integer` | NOT NULL DEFAULT 0 | 0 | none | CHECK `>=0` |
| `next_attempt_at` | Backoff | `timestamptz` | NOT NULL DEFAULT now() | now() | due index | none |
| `locked_by` | Dispatcher owner | `varchar(128)` | NULL | NULL | none | none |
| `locked_until` | Lock expiry | `timestamptz` | NULL | NULL | due query | none |
| `last_error` | Last failure | `text` | NULL | NULL | none | none |
| `created_at` | Audit | `timestamptz` | NOT NULL DEFAULT now() | - | none | none |
| `published_at` | Publish time | `timestamptz` | NULL | NULL | none | none |

Backfill:

```sql
INSERT INTO job_dispatch_outbox (job_id, task_name, status, next_attempt_at)
SELECT id, 'logvault.run_job', 'pending', now()
FROM jobs j
WHERE j.status='queued'
  AND NOT EXISTS (
    SELECT 1 FROM job_dispatch_outbox o
    WHERE o.job_id=j.id AND o.task_name='logvault.run_job');
```

- `jsonb` is Postgres; use `sa.JSON` for SQLite test compatibility.
- No FK: a customer/job delete may need to clean outbox rows explicitly; add a
  delete policy.
- Rollback: keep table; set `DISPATCH_MODE=direct`.

## 6. `schedule_windows` and `jobs` window link (0035)

| Field | Purpose | Type | Null/default | Backfill | Index | Unique/FK |
|---|---|---|---|---|---|---|
| `id` | Window id | `bigserial` | PK | - | PK | - |
| `schedule_id` | Schedule | `integer` | NOT NULL | - | `(schedule_id,window_key)` | no FK |
| `window_key` | Stable slot identity (`day:`/`slot:`) | `varchar(80)` | NOT NULL | - | unique | `UNIQUE(schedule_id,window_key)` |
| `scheduled_for` | Due time | `timestamptz` | NOT NULL | - | due index | none |
| `start_epoch` | Actual window start | `bigint` | NOT NULL | - | none | none |
| `end_epoch` | Actual window end | `bigint` | NOT NULL | - | none | none |
| `status` | `pending/dispatched/running/completed/failed/canceled` | `varchar(16)` | NOT NULL DEFAULT `pending` | - | `(status,next_attempt_at)` | CHECK |
| `completion_state` | `unknown/complete/partial` | `varchar(16)` | NOT NULL DEFAULT `unknown` | - | optional | CHECK |
| `attempts` | Attempt count | `integer` | NOT NULL DEFAULT 0 | 0 | none | CHECK `>=0` |
| `max_attempts` | Retry cap | `integer` | NOT NULL DEFAULT 3 | 3 | none | none |
| `current_job_id` | Latest attempt | `integer` | NULL | - | optional | no FK |
| `next_attempt_at` | Backoff | `timestamptz` | NULL | - | due index | none |
| `last_error` | Dispatch/execution error | `text` | NULL | - | none | none |
| `config_snapshot` | Source/filter/format at creation | `jsonb`/`JSON` | NULL | - | none | none |
| `created_at` | Audit | `timestamptz` | NOT NULL DEFAULT now() | - | none | none |
| `updated_at` | Audit | `timestamptz` | NOT NULL DEFAULT now() | - | none | none |

`jobs` additions:

| Field | Purpose | Type | Null/default | Index | Unique/FK |
|---|---|---|---|---|---|
| `schedule_window_id` | Link attempt to ledger | `integer` | NULL | deferred `0035b`/P7 partial | deferred `0035b`/P7 |
| `attempt_no` | Attempt number | `integer` | NOT NULL DEFAULT 1 | via deferred unique | deferred `0035b`/P7 |

Indexes in `0035` (new table only):

```sql
CREATE UNIQUE INDEX uq_schedule_windows_window ON schedule_windows(schedule_id,window_key);
CREATE INDEX ix_schedule_windows_due ON schedule_windows(status,next_attempt_at);
CREATE INDEX ix_schedule_windows_schedule ON schedule_windows(schedule_id,scheduled_for);
```

Jobs indexes deferred to `0035b`/P7:

```sql
CREATE UNIQUE INDEX CONCURRENTLY uq_jobs_schedule_attempt
  ON jobs(schedule_window_id,attempt_no)
  WHERE schedule_window_id IS NOT NULL;
CREATE UNIQUE INDEX CONCURRENTLY uq_jobs_schedule_active
  ON jobs(schedule_window_id)
  WHERE schedule_window_id IS NOT NULL AND status IN ('queued','running','paused');
CREATE INDEX CONCURRENTLY ix_jobs_schedule_window_id
  ON jobs(schedule_window_id)
  WHERE schedule_window_id IS NOT NULL;
```

- `UNIQUE(schedule_window_id,attempt_no)` allows multiple terminal retries but
  one row per attempt.
- `uq_jobs_schedule_active` prevents two active jobs per window.
- No FK to `schedules` because schedule deletion is handled by policy; no FK to
  jobs to avoid delete coupling.
- Seed recent legacy windows on first enable; map completed/failed/canceled and
  `current_job_id`. Do not delete legacy duplicate jobs.
- Old API/worker: jobs have null window; legacy report path must remain.
- Rollback: `SCHEDULE_WINDOWS_ENABLED=false`; keep table; legacy path.

## 7. S3 attempt fields (0036)

| Field | Purpose | Type | Null/default | Backfill | Index | Unique/FK |
|---|---|---|---|---|---|---|
| `s3_attempt_token` | S3 attempt fence | `bigint` | NOT NULL DEFAULT 0 | 0 | none | CHECK `>=0` |
| `s3_uploading_at` | Retry lock | `timestamptz` | NULL | NULL | deferred P8 partial `(s3_uploading_at)` | none |
| `s3_published_attempt` | Current published attempt | `bigint` | NULL | NULL | optional | CHECK `<= s3_attempt_token` |
| `s3_manifest_uri` | Audit manifest | `text` | NULL | NULL | none | none |

- Existing `s3_uri` rows remain legacy-published when
  `s3_published_attempt IS NULL`.
- Old code reads `s3_uri`; new fields ignored.
- Rollback: stop using new fields; keep objects.

## 8. Constraints (0037)

Audit before applying:

```sql
SELECT status, count(*) FROM jobs GROUP BY status;
SELECT completion_state, count(*) FROM jobs GROUP BY completion_state;
SELECT status, count(*) FROM schedule_windows GROUP BY status;
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

- Do not add a strict `running => owner` check in the first rollout; legacy
  rows/mixed versions may violate it.
- A future seventh status requires a migration; Release 1 intentionally keeps
  six.
- Rollback: drop CHECKs; legacy values can reappear.

## 9. PostgreSQL vs SQLite

| Concern | PostgreSQL | SQLite tests |
|---|---|---|
| `jsonb` | Use `jsonb` or `JSON` | `sa.JSON`; no JSONB |
| `timestamptz` | Native | stored text/naive; timezone handling differs |
| `make_interval` | Native | not available; use `datetime()`/Python |
| `RETURNING` | Supported | supported in recent SQLite; verify driver |
| Row-level lock / `FOR UPDATE` | Supported | database-level writer lock; no SKIP LOCKED |
| Partial unique indexes | Supported | supported; semantics differ |
| `CREATE INDEX CONCURRENTLY` | Supported outside transaction | not applicable |
| CHECK constraints | Supported | supported; migration tests still needed |

**Mandatory real-Postgres tests:** claim/fence, cancel/pause, reaper,
outbox `SKIP LOCKED`, schedule unique/active index, migration upgrade/downgrade,
CHECK behavior, `jsonb` round-trip.

## 10. Deployment execution

1. Preflight audits (status/completion/duplicates/backups).
2. Apply additive migrations before code (`0032`, `0032b`, `0033`, `0034`, `0035`, `0036`).
3. Run backfills in batches; verify counts.
4. Add 0037 constraints only after audits are clean.
5. Deploy code with flags off; enable per deployment plan.
6. `CREATE INDEX CONCURRENTLY` (if used) must be outside the Alembic
   transaction or in a maintenance window.
7. Run real-Postgres migration tests in staging before production.

## 11. Rollback

| Change | Rollback | Data loss |
|---|---|---|
| 0032 fields | Leave columns; disable flags/code | No |
| 0033 `store_path`/`spec_fingerprint`/`checkpoint_version` | Leave; old code ignores; shim store path | No (attempt stores remain) |
| 0034 outbox | Keep table; `DISPATCH_MODE=direct`; drain | No |
| 0035 ledger | `SCHEDULE_WINDOWS_ENABLED=false`; keep table | No |
| 0036 S3 fields | `S3_ATTEMPT_FENCING=false`; old `s3_uri` reads | No |
| 0037 CHECKs | Drop constraints | No |

Never drop columns/tables while new workers may still use them. Do not delete
attempt stores or published S3 objects during rollback.

## 12. Open migration questions

- Production Postgres version for systemd installs.
- Whether to use `jsonb` or JSON for compatibility with SQLite tests.
- Whether `CREATE INDEX CONCURRENTLY` is operationally acceptable.
- Outbox retention period.
- Schedule ledger seed range and legacy duplicate policy.
- Customer/job deletion policy for outbox/ledger rows.
- Whether to backfill `completion_state` from old skipped-batch `error_message`.
