# Release 1 P1 Scope and Migration

Status: **proposal only.** P1 is **not authorized**. This document defines the
exact additive boundary to approve or reject. No migration or source file has
been created.

**Preflight update:** the migration safety review in
[`RELEASE_1_P1_MIGRATION_SAFETY_PREFLIGHT.md`](./RELEASE_1_P1_MIGRATION_SAFETY_PREFLIGHT.md)
finds the bundle **NO-GO as currently specified** for live
`alembic upgrade head` because the current `env.py` runs all revisions in one
transaction and holds `ACCESS EXCLUSIVE` on `jobs` for the entire bundle. The
boundary below remains the proposed scope; execution strategy and index
definitions must be resolved before authorization.

**Execution redesign:** the final revision graph is
`0031 -> 0032 -> 0032b -> 0033 -> 0034 -> 0035 -> 0036`.
`0032` contains columns only; `0032b` contains the approved concurrent indexes;
`0035` contains the schedule-window table and `jobs` columns but no jobs indexes;
`0036` depends on `0035` and contains S3 columns only. `0035b`, `0036b`,
`ix_jobs_retry_of`, `ix_jobs_schedule_window_id`, and `ix_jobs_s3_uploading`
are deferred and are **not** part of P1. See
[`RELEASE_1_P1_IMPLEMENTATION_SPECIFICATION.md`](./RELEASE_1_P1_IMPLEMENTATION_SPECIFICATION.md)
and [`RELEASE_1_P1_FINAL_OPERATOR_RUNBOOK.md`](./RELEASE_1_P1_FINAL_OPERATOR_RUNBOOK.md).

P1 is limited to **additive schema and inert state primitives**. It must not
enable fencing, re-dispatch, outbox publishing, schedule scanning, attempt-path
selection, S3 publication, or any change in production execution behavior.

Related:

- [`RELEASE_1_FINAL_ARCHITECTURE_APPROVAL.md`](./RELEASE_1_FINAL_ARCHITECTURE_APPROVAL.md)
- [`RELEASE_1_FINAL_DECISION_REGISTER.md`](./RELEASE_1_FINAL_DECISION_REGISTER.md)
- [`LEASE_AND_FENCING.md`](./LEASE_AND_FENCING.md)
- [`OUTBOX_AND_DISPATCH.md`](./OUTBOX_AND_DISPATCH.md)
- [`ARTIFACT_PUBLICATION.md`](./ARTIFACT_PUBLICATION.md)
- [`RELEASE_1_SCHEDULE_WINDOW_CONTRACT.md`](./RELEASE_1_SCHEDULE_WINDOW_CONTRACT.md)

## 1. P1 boundary

### 1.1 In scope

| Area | P1 does |
|---|---|
| Migrations | Adds `0032`, `0032b`, `0033`, `0034`, `0035`, `0036`, all additive |
| Tables | Creates `job_dispatch_outbox` and `schedule_windows` |
| Columns | Adds inert columns to `jobs` |
| Indexes | `0032b` adds partial concurrent lease/owner/progress indexes; new-table indexes are created with their tables. Deferred jobs indexes are not in P1. |
| ORM/mirror | Declares the new columns/tables with defaults only in API and worker table mirrors |
| Constants | Optionally adds status/completion constants; no branching logic |
| Tests | Migration up/down and compatibility tests |
| Docs | This scope and rollback record |

**D11 decision:** the final recommendation is the full calendar+interval
ledger. `0035` is included and `0036.down_revision = "0035"`. If D11 selects
**REDUCED**, exclude both `0035` and `0036`; the P1 graph becomes
`0031 -> 0032 -> 0032b -> 0033 -> 0034`. Do not retain `0036` under REDUCED.
`0035b` is not part of P1.

### 1.2 Explicitly out of scope

- Any read or write of the new columns by API routers, worker tasks, scheduler,
  cleanup, rollup, reports, or UI.
- Claim, fencing, heartbeat, progress renewal, cancel/pause request semantics.
- Lease-expiry detection or re-dispatch.
- Outbox row creation, claiming, publishing, or retry.
- Schedule window creation, scanning, locking, or job creation.
- Attempt-scoped path selection or pointer publication.
- S3 attempt token increment, upload, pointer publication, or cleanup.
- CHECK constraints.
- Runtime flags, feature toggles, or environment settings.
- Dependency changes.
- Deployment or Redis/S3/Celery configuration changes.
- Production migration execution.

## 2. Migration 0032 - job ownership and completion

File: `api/migrations/versions/0032_job_ownership_and_completion.py`
Revision: `0032`, down revision `0031`.

### 2.1 Added columns on `jobs`

| Column | Type | Null | Default | Purpose |
|---|---|---|---|---|
| `owner_id` | `varchar(128)` | YES | NULL | Attempt identity for diagnostics and derived phase |
| `lease_token` | `bigint` | NO | `0` | Monotonic fence |
| `lease_expires_at` | `timestamptz` | YES | NULL | Authoritative expiry |
| `heartbeat_at` | `timestamptz` | YES | NULL | Last successful renewal |
| `progress_at` | `timestamptz` | YES | NULL | Last observed progress |
| `pause_requested_at` | `timestamptz` | YES | NULL | Pause request time |
| `cancel_requested_at` | `timestamptz` | YES | NULL | Cancel request time |
| `completion_state` | `varchar(16)` | NO | `'unknown'` | `unknown`/`complete`/`partial` |
| `gap_count` | `integer` | NO | `0` | Skipped batch/source count |
| `gap_reason` | `text` | YES | NULL | Human/machine-readable gap summary |
| `retry_of` | `integer` | YES | NULL | Retry lineage job id; no FK by design |

### 2.2 Indexes

**`0032` creates no indexes.** The approved concurrent jobs indexes are in
`0032b`; this keeps the `ACCESS EXCLUSIVE` lock in `0032` limited to metadata
changes.

## 2A. Migration 0032b - concurrent jobs indexes

File: `api/migrations/versions/0032b_jobs_lease_indexes.py`
Revision: `0032b`, down revision `0032`.

These indexes are created with `CREATE INDEX CONCURRENTLY` inside
`autocommit_block`. `transaction_per_migration=True` must already be active.

| Index | Definition | Query served |
|---|---|---|
| `ix_jobs_lease` | `(status, lease_expires_at) WHERE lease_expires_at IS NOT NULL` | Reaper/expiry scan |
| `ix_jobs_owner` | `(owner_id) WHERE owner_id IS NOT NULL` | Owner lookup |
| `ix_jobs_progress` | `(status, progress_at) WHERE progress_at IS NOT NULL` | Silent-job scan |

`ix_jobs_retry_of` is **not** created in P1. It is deferred to P2/P9 as a
partial concurrent index:

```sql
CREATE INDEX CONCURRENTLY ix_jobs_retry_of
  ON jobs (retry_of)
  WHERE retry_of IS NOT NULL;
```

**Constraints:** none. These are unique/ordinary indexes, not table constraints.

### 2.3 Constraints (0032)

**None in P1.** All CHECK constraints are deferred to `0037` (P9). See
section 7.

## 3. Migration 0033 - job artifact and checkpoint pointers

File: `api/migrations/versions/0033_job_artifact_paths.py`
Revision: `0033`, down revision `0032b`.

### 3.1 Added columns on `jobs`

| Column | Type | Null | Default | Purpose |
|---|---|---|---|---|
| `store_path` | `text` | YES | NULL | Published attempt-scoped distinct store |
| `spec_fingerprint` | `varchar(64)` | YES | NULL | Canonical job-spec hash for checkpoint identity |
| `checkpoint_version` | `integer` | NO | `1` | Checkpoint protocol version |

Existing pointer columns are unchanged and remain authoritative:
`output_file_path`, `summary_file_path`, `counts_file_path`,
`unmatched_file_path`, `s3_uri`, `s3_summary_uri`, `s3_counts_uri`.

### 3.2 Added indexes

**None.** These columns are read by job id or by the existing job scans.

### 3.3 Constraints

**None in P1.**

## 4. Migration 0034 - dispatch outbox

File: `api/migrations/versions/0034_job_dispatch_outbox.py`
Revision: `0034`, down revision `0033`.

### 4.1 New table `job_dispatch_outbox`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | `bigserial` | NO | identity | PK |
| `job_id` | `integer` | NO | — | Logical reference to `jobs.id` |
| `task_name` | `varchar(80)` | NO | `'logvault.run_job'` | Logical action |
| `payload` | `json` | NO | `'{}'` | Small task payload; use `sa.JSON` for SQLite/Postgres portability |
| `status` | `varchar(16)` | NO | `'pending'` | `pending`/`published`/`failed` |
| `attempts` | `integer` | NO | `0` | Publish attempts |
| `next_attempt_at` | `timestamptz` | NO | `now()` | Backoff gate |
| `locked_by` | `varchar(128)` | YES | NULL | Dispatcher claim owner |
| `locked_until` | `timestamptz` | YES | NULL | Dispatcher claim expiry |
| `last_error` | `text` | YES | NULL | Last publish error |
| `created_at` | `timestamptz` | NO | `now()` | — |
| `published_at` | `timestamptz` | YES | NULL | — |

### 4.2 Constraints and indexes

| Object | Definition | Purpose |
|---|---|---|
| Unique | `UNIQUE (job_id, task_name)` | One logical intent per job/action |
| Index | `ix_job_dispatch_due (status, next_attempt_at)` | Due scan |
| Index | `ix_job_dispatch_locked (locked_until) WHERE locked_until IS NOT NULL` | Stale-lock recovery |

**Foreign key:** intentionally **none**. Deleting a job must not fail because of
an outbox row; cleanup handles rows explicitly. This also keeps SQLite tests
portable.

**CHECK constraints:** none in P1; deferred to `0037`.

**JSON type:** use `sa.JSON` in both the migration and models so the SQLite unit
suite can create the same schema. If Postgres-only `JSONB` is preferred, the
models must use a dialect variant and the SQLite tests must be given an
equivalent; do not let the two drift.

### 4.3 Rows in P1

**None are created.** The table is empty and unread.

## 5. Migration 0035 - schedule windows

File: `api/migrations/versions/0035_schedule_windows.py`
Revision: `0035`, down revision `0034`.

### 5.1 New table `schedule_windows`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | `bigserial` | NO | identity | PK |
| `schedule_id` | `integer` | NO | — | Logical reference to `schedules.id` |
| `window_key` | `varchar(80)` | NO | — | `day:YYYY-MM-DD` or `slot:<epoch>` |
| `scheduled_for` | `timestamptz` | NO | — | Due time |
| `start_epoch` | `bigint` | NO | — | Window start |
| `end_epoch` | `bigint` | NO | — | Window end |
| `status` | `varchar(16)` | NO | `'pending'` | `pending`/`dispatched`/`running`/`completed`/`failed`/`canceled` |
| `completion_state` | `varchar(16)` | NO | `'unknown'` | `unknown`/`complete`/`partial` |
| `attempts` | `integer` | NO | `0` | Window attempts |
| `max_attempts` | `integer` | NO | `3` | Retry cap |
| `current_job_id` | `integer` | YES | NULL | Winning/active job |
| `next_attempt_at` | `timestamptz` | YES | NULL | Backoff |
| `last_error` | `text` | YES | NULL | Last failure |
| `config_snapshot` | `json` | YES | NULL | Source/filter/format at window creation; `sa.JSON` |
| `created_at` | `timestamptz` | NO | `now()` | — |
| `updated_at` | `timestamptz` | NO | `now()` | — |

### 5.2 Added columns on `jobs`

| Column | Type | Null | Default | Purpose |
|---|---|---|---|---|
| `schedule_window_id` | `integer` | YES | NULL | Link to `schedule_windows.id` |
| `attempt_no` | `integer` | NO | `1` | Attempt number inside a window |

### 5.3 Constraints and indexes

| Object | Definition | Purpose |
|---|---|---|
| Unique | `uq_schedule_windows_window (schedule_id, window_key)` | One obligation per window |
| Index | `ix_schedule_windows_due (status, scheduled_for)` | Due scan |
| Index | `ix_schedule_windows_schedule (schedule_id, scheduled_for)` | Per-schedule history |

**Jobs indexes are not in `0035`.** `ix_jobs_schedule_window_id`,
`uq_jobs_schedule_attempt`, and `uq_jobs_schedule_active` are deferred to
`0035b`/P7 and are **not part of P1**.

**Foreign keys:** intentionally **none**. Schedule deletion and job history must
not be coupled; cleanup handles rows explicitly.

**CHECK constraints:** none in P1; deferred to `0037`.

### 5.4 Rows in P1

**None are created.** The table is empty and unread.

## 6. Migration 0036 - S3 attempt publication

File: `api/migrations/versions/0036_s3_attempt_publication.py`
Revision: `0036`, down revision `0035`.

### 6.1 Added columns on `jobs`

| Column | Type | Null | Default | Purpose |
|---|---|---|---|---|
| `s3_attempt_token` | `bigint` | NO | `0` | Independent S3 attempt fence |
| `s3_uploading_at` | `timestamptz` | YES | NULL | S3 retry lock timestamp |
| `s3_published_attempt` | `bigint` | YES | NULL | Attempt whose S3 objects are current |
| `s3_manifest_uri` | `text` | YES | NULL | Audit pointer to manifest |

Existing `s3_uri`, `s3_summary_uri`, `s3_counts_uri`, `s3_error`,
`s3_uploaded_at` are unchanged.

### 6.2 Added indexes

**None in `0036`.** `ix_jobs_s3_uploading` is deferred to P8 as a partial
concurrent index:

```sql
CREATE INDEX CONCURRENTLY ix_jobs_s3_uploading
  ON jobs (s3_uploading_at)
  WHERE s3_uploading_at IS NOT NULL;
```

### 6.3 Constraints

**None in P1.** Deferred to `0037`.

## 7. Deferred migration 0037 - constraints (P9)

File (proposed, **not part of P1**):
`api/migrations/versions/0037_status_constraints.py`

| Constraint | Definition | Gate |
|---|---|---|
| `ck_jobs_lease_token_nonnegative` | `lease_token >= 0` | P9 |
| `ck_jobs_s3_attempt_nonnegative` | `s3_attempt_token >= 0` | P9 |
| `ck_jobs_owner_lease_pair` | `owner_id IS NOT NULL OR lease_expires_at IS NULL` | P9 |
| `ck_jobs_published_attempt` | `s3_published_attempt IS NULL OR s3_published_attempt <= s3_attempt_token` | P9 |
| `ck_jobs_status` | six-value status list | P9 after audit |
| `ck_jobs_completion_state` | `unknown`/`complete`/`partial` | P9 after audit |
| `ck_schedule_windows_status` | six-value window status list | P9 after audit |
| `ck_schedule_windows_completion` | `unknown`/`complete`/`partial` | P9 after audit |
| `ck_outbox_status` | `pending`/`published`/`failed` | P9 |
| `ck_outbox_attempts` | `attempts >= 0` | P9 |

No strict `status='running' => owner_id IS NOT NULL` check is proposed until all
writers are on the new version.

## 8. Shared state definitions

These are constants/contracts, not behavior.

### 8.1 Job status (unchanged)

`queued`, `running`, `paused`, `completed`, `failed`, `canceled`.

No seventh status. Derived phases are presentation-only:

`claiming`, `running`, `pausing`, `canceling`, `finalizing`.

### 8.2 Completion state

`unknown`, `complete`, `partial`.

Rules (enforced only from P3):

- `unknown` until a terminal write classifies the result.
- `partial` when any skipped batch/source/BQ drop occurred.
- `complete` only when no gap was recorded.
- `gap_count`/`gap_reason` accompany `partial`.

### 8.3 Lease

- `lease_token` monotonically increases per job on claim/resume/reclaim.
- `owner_id` is diagnostic, not a fence.
- `lease_expires_at` is the authority; worker clocks are not.
- `heartbeat_at` is observability.
- `progress_at` advances only on real progress.

### 8.4 Outbox

- One row per `(job_id, task_name)`.
- `pending` -> `published` or `failed`.
- Publish is at-least-once; execution is gated by the job claim.

### 8.5 Schedule window

- Identity is `(schedule_id, window_key)`.
- `day:YYYY-MM-DD` for calendar schedules.
- `slot:<epoch>` for interval schedules.
- One active job per window.
- Reports select the completed winner, never every terminal job.

### 8.6 Attempt artifacts

- Local path token is the `lease_token`.
- S3 token is `s3_attempt_token`.
- Path shape: `job_<id>.a<token>.<ext>` and
  `job_<id>.a<token>.distinct.sqlite`.
- DB pointers are the publication record.
- P1 adds `store_path` only; it does not switch writers to attempt paths.

### 8.7 Checkpoint identity

- `checkpoint_version` is the protocol version.
- `spec_fingerprint` is the canonical job-spec hash.
- `completed_chunks=0` is **not** resumable.
- Existing `checkpoint` JSON remains the detailed payload.

## 9. File-touch boundary

If P1 is authorized, the allowed changes are:

| File/path | Allowed change |
|---|---|
| `api/migrations/versions/0032_job_ownership_and_completion.py` | New migration |
| `api/migrations/versions/0033_job_artifact_paths.py` | New migration |
| `api/migrations/versions/0034_job_dispatch_outbox.py` | New migration |
| `api/migrations/versions/0035_schedule_windows.py` | New migration |
| `api/migrations/versions/0036_s3_attempt_publication.py` | New migration |
| `api/migrations/versions/0032b_jobs_lease_indexes.py` | New concurrent-index migration |
| `api/migrations/env.py` | `transaction_per_migration=True` only, if approved |
| `api/app/models.py` | Column/table declarations only; no methods/queries |
| `worker/app/db.py` | Core table-mirror column declarations only; no queries |
| `api/app/job_state.py`, `worker/app/job_state.py` | Constants/contract only; no behavior |
| `p1/` (test-only) | Migration/compatibility tests |
| `docs/` | P1 record |

`0035b` (schedule jobs indexes) and `0036b` (S3 index) are **not part of P1**.
They are future P7/P8 revisions and must not be created in the P1 change.

Not allowed in P1:

- `api/app/routers/*`
- `api/app/schemas.py` (no response field changes in P1)
- `worker/app/runner.py`, `tasks.py`, `scheduler.py`, `s3.py`, `rollup.py`,
  `last9/*` (and any other worker module that executes tasks)
- `web/*`
- `docker-compose*.yml`, Dockerfiles, deployment manifests
- `api/requirements*`, `worker/requirements*`
- Celery/Redis/S3 configuration
- Any feature flag or environment default
- Any query that reads a P1 column

## 10. Compatibility with existing API and worker versions

| Concern | Result |
|---|---|
| `ADD COLUMN` on a populated table | Postgres 11+ stores a constant default in the catalog; no rewrite |
| Old ORM inserts | Omit new columns; DB defaults apply |
| Old ORM selects | Select explicit known columns; new columns are invisible |
| Old worker reads | Unchanged columns only; behavior identical |
| Old API responses | No schema change; new fields not serialized |
| New columns with NOT NULL | All have defaults; no backfill needed |
| Unique indexes over new columns | All existing rows have NULL `schedule_window_id`; no conflict |
| Outbox/schedule tables | Empty and unread; no runtime effect |
| Alembic autogenerate drift | Models must declare new columns in P1 to match migrations |
| SQLite tests | New tables/columns are portable; partial unique indexes are supported by recent SQLite |
| Mixed-version deployment | Old and new versions can run concurrently because no behavior reads the new state |

### 10.1 Index creation on a large `jobs` table

The final P1 strategy is:

1. `transaction_per_migration=True` is enabled before P1.
2. `0032` runs as a short transactional column revision.
3. `0032b` creates the approved indexes with `CREATE INDEX CONCURRENTLY` inside
   `autocommit_block`.

The old alternatives (external index step or non-concurrent maintenance-window
indexes) are fallbacks only if the Alembic version/driver is revalidated. Do not
run `CREATE INDEX CONCURRENTLY` inside an ordinary transaction. Do not create the
deferred indexes in P1.

## 11. Migration procedure (when authorized)

The authoritative operator sequence is
[`RELEASE_1_P1_FINAL_OPERATOR_RUNBOOK.md`](./RELEASE_1_P1_FINAL_OPERATOR_RUNBOOK.md).

1. Confirm `transaction_per_migration=True` is present in the deployed code.
2. Take a verified production backup and complete the restore rehearsal.
3. Apply one revision at a time:
   `0032`, `0032b`, `0033`, `0034`, `0035`, `0036`.
4. Verify `alembic current`, schema objects, index validity, API/worker health
   after each revision.
5. Do **not** use `alembic upgrade head` in the P1 window.
6. Do **not** create or run `0035b` or `0036b`.
7. Do **not** enable any P2 behavior in the same deployment.
8. On failure, stop and follow the runbook recovery path; do not skip to the
   next revision.

## 12. Rollback

### 12.1 P1-only rollback (safe)

Downgrade in reverse order:
`0036 -> 0035 -> 0034 -> 0033 -> 0032b -> 0032`.
The `0032b` downgrade drops the concurrent indexes; the column revisions then
drop their columns/tables. This is safe **only while**:

- no writer reads the new columns;
- no outbox rows exist;
- no schedule windows exist;
- no S3 attempt token was incremented;
- no P2 behavior is active.

### 12.2 Rollback after P2+ has started

P1 rollback is **not** standalone. It requires:

1. disable re-dispatch/outbox/claim enforcement;
2. drain workers;
3. export or intentionally discard outbox/window state;
4. roll back P2 code first;
5. then run the P1 downgrade.

Dropping `schedule_windows` or `job_dispatch_outbox` after they contain live
state loses recovery/obligation history and must be treated as data loss.

### 12.3 Backup and retention

- Keep a pre-migration snapshot until P2 is accepted.
- Record row counts for `jobs`, `schedules`, and new tables before/after.
- Rehearse rollback on a copy, not production.

## 13. P1 acceptance tests

These are tests for the migration, not behavior:

| ID | Test | Pass condition |
|---|---|---|
| P1-T01 | Apply `0032`, `0032b`, `0033`, `0034`, `0035`, `0036` individually on a populated Postgres 16 copy | Each revision succeeds; `alembic current=0036`; no data change |
| P1-T02 | Column/default inspection | Types/defaults match this document |
| P1-T03 | `jobs` row count and checksum unchanged | Identical excluding new columns |
| P1-T04 | Old API read smoke | Responses unchanged |
| P1-T05 | Old worker task smoke | Task behavior unchanged |
| P1-T06 | New tables empty | 0 rows in outbox/windows |
| P1-T07 | Schedule-window unique behavior | Duplicate `(schedule_id, window_key)` rejected; jobs rows unaffected |
| P1-T08 | Downgrade reverse order `0036 -> 0035 -> 0034 -> 0033 -> 0032b -> 0032` | Success; added objects removed |
| P1-T09 | Re-upgrade | Success |
| P1-T10 | Lock/duration measurement | Recorded and within approved window |
| P1-T11 | SQLite unit suite | Passes with model declarations |
| P1-T12 | No feature flag/config diff | Confirmed |
| P1-T13 | TPM transaction boundaries | `0032`, `0033`, `0034`, `0035`, `0036` commit independently; `0032b` autocommit works |
| P1-T14 | Deferred indexes absent | No `ix_jobs_retry_of`, `ix_jobs_schedule_window_id`, or `ix_jobs_s3_uploading` in P1 |

## 14. P1 exit criteria

P1 is complete only when:

- all six P1 revisions (`0032`, `0032b`, `0033`, `0034`, `0035`, `0036`) apply and downgrade on a production-like Postgres copy;
- no API/worker/frontend behavior changed;
- tests P1-T01..T14 pass;
- the rollback procedure is documented and rehearsed;
- no P2 behavior is enabled;
- the user explicitly authorizes P2.

## 15. Stop condition

This is a proposal. Do not create these migrations or edit models until the user
explicitly authorizes P1.
