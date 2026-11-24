# Release 1 P1 Implementation Specification

Status: **specification only.** P1 is not authorized. No migration, `env.py`,
`deploy.sh`, application source, schema, API, frontend, dependency, deployment,
or production setting was changed.

**Approval status: HOLD — A14-01 not approved.** Approval evidence must record
both paths, commit/version, individual SHA-256 hashes, approver, reviewer, and
date as defined in `RELEASE_1_GATE_A_CANONICAL_REGISTER.md`.

This document is authoritative for P1 schema shape. If another document
disagrees, this specification and
[`RELEASE_1_P1_FINAL_OPERATOR_RUNBOOK.md`](./RELEASE_1_P1_FINAL_OPERATOR_RUNBOOK.md)
win.

## 1. Revision graph

```text
0031
  -> 0032    jobs ownership/completion columns
  -> 0032b   concurrent jobs lease/owner/progress indexes
  -> 0033    jobs artifact/checkpoint columns
  -> 0034    job_dispatch_outbox table + new-table indexes
  -> 0035    schedule_windows table + jobs window columns + new-table indexes
  -> 0036    jobs S3 attempt columns
```

There are **six** P1 revisions. `0035b` and `0036b` are not P1.

| Revision | File (proposed) | Down revision | Transaction |
|---|---|---|---|
| `0032` | `0032_job_ownership_and_completion.py` | `0031` | One transaction |
| `0032b` | `0032b_jobs_lease_indexes.py` | `0032` | `autocommit_block` |
| `0033` | `0033_job_artifact_paths.py` | `0032b` | One transaction |
| `0034` | `0034_job_dispatch_outbox.py` | `0033` | One transaction |
| `0035` | `0035_schedule_windows.py` | `0034` | One transaction |
| `0036` | `0036_s3_attempt_publication.py` | `0035` | One transaction |

## 2. Migration 0032 — job ownership and completion

Add to `jobs`; no indexes.

| Column | Type | Null | Default |
|---|---|---|---|
| `owner_id` | `varchar(128)` | YES | NULL |
| `lease_token` | `bigint` | NO | `0` |
| `lease_expires_at` | `timestamptz` | YES | NULL |
| `heartbeat_at` | `timestamptz` | YES | NULL |
| `progress_at` | `timestamptz` | YES | NULL |
| `pause_requested_at` | `timestamptz` | YES | NULL |
| `cancel_requested_at` | `timestamptz` | YES | NULL |
| `completion_state` | `varchar(16)` | NO | `'unknown'` |
| `gap_count` | `integer` | NO | `0` |
| `gap_reason` | `text` | YES | NULL |
| `retry_of` | `integer` | YES | NULL |

Rules:

- `completion_state` values: `unknown`, `complete`, `partial`.
- No CHECK constraints in P1; `0037` (P9) owns them.
- No backfill; existing rows receive column defaults.
- No indexes. Do not add `ix_jobs_retry_of` here.
- `retry_of` is in `0032`, not `0033`.

## 3. Migration 0032b — concurrent jobs indexes

Create with `CREATE INDEX CONCURRENTLY` inside `autocommit_block`, one index per
block, after `transaction_per_migration=True` is active.

| Index | Definition |
|---|---|
| `ix_jobs_lease` | `(status, lease_expires_at) WHERE lease_expires_at IS NOT NULL` |
| `ix_jobs_owner` | `(owner_id) WHERE owner_id IS NOT NULL` |
| `ix_jobs_progress` | `(status, progress_at) WHERE progress_at IS NOT NULL` |

Rules:

- Validate `pg_index.indisvalid=true` after each build.
- On failure, `DROP INDEX CONCURRENTLY` the invalid index and retry.
- `ix_jobs_retry_of` is **not** created in P1. Future P2/P9 partial index:
  `(retry_of) WHERE retry_of IS NOT NULL`.
- These are indexes, not named constraints.

## 4. Migration 0033 — artifact and checkpoint pointers

Add to `jobs`; no indexes.

| Column | Type | Null | Default |
|---|---|---|---|
| `store_path` | `text` | YES | NULL |
| `spec_fingerprint` | `varchar(64)` | YES | NULL |
| `checkpoint_version` | `integer` | NO | `1` |

Rules:

- Existing pointers `output_file_path`, `summary_file_path`,
  `counts_file_path`, `unmatched_file_path` are unchanged.
- `completed_chunks=0` is not resumable; the D3 contract applies.
- `retry_of` is not part of this revision.

## 5. Migration 0034 — dispatch outbox

Create `job_dispatch_outbox`; no rows inserted.

| Column | Type | Null | Default |
|---|---|---|---|
| `id` | `bigserial` | NO | identity |
| `job_id` | `integer` | NO | — |
| `task_name` | `varchar(80)` | NO | `'logvault.run_job'` |
| `payload` | `json` (`sa.JSON`) | NO | `'{}'` |
| `status` | `varchar(16)` | NO | `'pending'` |
| `attempts` | `integer` | NO | `0` |
| `next_attempt_at` | `timestamptz` | NO | `now()` |
| `locked_by` | `varchar(128)` | YES | NULL |
| `locked_until` | `timestamptz` | YES | NULL |
| `last_error` | `text` | YES | NULL |
| `created_at` | `timestamptz` | NO | `now()` |
| `published_at` | `timestamptz` | YES | NULL |

Indexes/constraints:

| Object | Definition |
|---|---|
| Unique | `(job_id, task_name)` |
| Index | `ix_job_dispatch_due (status, next_attempt_at)` |
| Index | `ix_job_dispatch_locked (locked_until) WHERE locked_until IS NOT NULL` |

Rules:

- No foreign key; job deletion must not be coupled.
- No CHECK constraints in P1; `0037` (P9) owns them.
- Use `sa.JSON` for SQLite/Postgres portability; do not silently switch to a
  Postgres-only JSONB model without a dialect plan.
- No dispatcher, no outbox rows, no publish behavior in P1.

## 6. Migration 0035 — schedule windows

Create `schedule_windows`; no rows inserted. Add two `jobs` columns.

| Column | Type | Null | Default |
|---|---|---|---|
| `id` | `bigserial` | NO | identity |
| `schedule_id` | `integer` | NO | — |
| `window_key` | `varchar(80)` | NO | — |
| `scheduled_for` | `timestamptz` | NO | — |
| `start_epoch` | `bigint` | NO | — |
| `end_epoch` | `bigint` | NO | — |
| `status` | `varchar(16)` | NO | `'pending'` |
| `completion_state` | `varchar(16)` | NO | `'unknown'` |
| `attempts` | `integer` | NO | `0` |
| `max_attempts` | `integer` | NO | `3` |
| `current_job_id` | `integer` | YES | NULL |
| `next_attempt_at` | `timestamptz` | YES | NULL |
| `last_error` | `text` | YES | NULL |
| `config_snapshot` | `json` (`sa.JSON`) | YES | NULL |
| `created_at` | `timestamptz` | NO | `now()` |
| `updated_at` | `timestamptz` | NO | `now()` |

On `jobs`:

| Column | Type | Null | Default |
|---|---|---|---|
| `schedule_window_id` | `integer` | YES | NULL |
| `attempt_no` | `integer` | NO | `1` |

New-table indexes/constraints:

| Object | Definition |
|---|---|
| Unique | `uq_schedule_windows_window (schedule_id, window_key)` |
| Index | `ix_schedule_windows_due (status, scheduled_for)` |
| Index | `ix_schedule_windows_schedule (schedule_id, scheduled_for)` |

Rules:

- `window_key` is `day:YYYY-MM-DD` for calendar, `slot:<epoch>` for interval.
- No foreign key to `schedules`.
- No CHECK constraints in P1.
- **No jobs indexes in `0035`.** `ix_jobs_schedule_window_id`,
  `uq_jobs_schedule_attempt`, and `uq_jobs_schedule_active` are deferred to
  `0035b`/P7.
- No scheduler, no scan, no window creation, no job creation in P1.

## 7. Migration 0036 — S3 attempt columns

Add to `jobs`; no index.

| Column | Type | Null | Default |
|---|---|---|---|
| `s3_attempt_token` | `bigint` | NO | `0` |
| `s3_uploading_at` | `timestamptz` | YES | NULL |
| `s3_published_attempt` | `bigint` | YES | NULL |
| `s3_manifest_uri` | `text` | YES | NULL |

Rules:

- `ix_jobs_s3_uploading` is **not** created in P1. Future P8 partial index:
  `(s3_uploading_at) WHERE s3_uploading_at IS NOT NULL`.
- No S3 upload, token increment, pointer publication, or cleanup in P1.
- No CHECK constraints in P1; `0037` (P9) owns `s3_published_attempt <=
  s3_attempt_token`.

## 8. Deferred objects

| Object | Phase | Condition |
|---|---|---|
| `0035b` schedule jobs indexes | P7 | Scheduler writes windows; concurrent/unique indexes |
| `0036b` S3 index | P8 | S3 retry path exists |
| `ix_jobs_retry_of` | P2/P9 | Retry lineage query exists; partial concurrent |
| `ix_jobs_schedule_window_id` | P7 | Window/job lookup exists; partial concurrent |
| `ix_jobs_s3_uploading` | P8 | Stale S3 scan exists; partial concurrent |
| `0037` CHECK constraints | P9 | Audit clean; all writers on new version |

## 9. Transaction and ordering requirements

1. `transaction_per_migration=True` must be active before P1.
2. Apply `0032` in its own transaction; commit before `0032b`.
3. `0032b` uses `autocommit_block` and runs outside a transaction.
4. Apply `0033`, `0034`, `0035`, `0036` one at a time.
5. Never run `alembic upgrade head` in the P1 window.
6. Never place `CREATE INDEX CONCURRENTLY` in an ordinary transaction.
7. Never let an autocommit block run before TPM is enabled; without TPM it
   commits preceding revisions.

## 10. Failure and retry behavior

| Failure | Behavior | Recovery |
|---|---|---|
| Transactional revision fails | Rollback; version stays previous | Fix; retry revision |
| Concurrent index fails | Invalid index may remain; version stays previous | Drop invalid; retry `0032b` |
| Process killed during index | Invalid index may remain | Inspect/drop; retry |
| Lock timeout | Current revision aborts | Find blocker; reschedule |
| Statement timeout | Current revision aborts | Measure; adjust; retry |
| Version/object mismatch | Inconsistent state | Audit; do not stamp blindly |
| App deploy fails after migration | Old app remains compatible | Fix deployment; no schema rollback |

## 11. Compatibility requirements

- API `JobOut` and all response schemas unchanged.
- No router reads new columns/tables.
- Worker tasks and Core mirror read only known columns.
- Scheduler/beat does not read `schedule_windows` or new columns.
- Reports/rollup/cleanup/S3 do not read new state.
- New tables remain empty.
- No feature flags, dependencies, or deployment settings change.
- Old API/worker must pass smoke tests against the migrated copy.
- If P1 includes model declarations, both API and worker mirrors must match and
  remain inert; no runtime branch.

## 12. P1/P2 boundary

P1 owns:

- additive columns/tables/indexes;
- inert model/mirror declarations;
- migration tests and compatibility evidence.

P2 owns:

- claim/fencing;
- heartbeat/progress renewal;
- stale-worker rejection;
- cancel/pause request semantics;
- lease-expiry reconciler;
- any read of the new state.

## 13. Unresolved questions

These are not schema inventions; they require explicit closure:

1. **Signed D11 record.** The final recommendation is full ledger; confirm
   `0035` inclusion and `0036.down_revision="0035"`.
2. **Exact filenames.** `0032b_jobs_lease_indexes.py` is proposed; confirm before
   creation.
3. **Model declarations in P1.** Recommended inert declarations in
   `api/app/models.py` and `worker/app/db.py`; confirm whether P1 includes them
   or defers to P2.
4. **`ix_jobs_owner` retention.** Included in the approved three-index set;
   confirm it is not considered speculative.
5. **Partial predicates.** The lease/progress/owner predicates are specified;
   confirm they match the P2 query shapes.
6. **JSON type.** `sa.JSON` is specified for portability; confirm no
   Postgres-only JSONB requirement.
7. **Named constraints.** P1 uses indexes, not named constraints; confirm that
   is acceptable for the schedule uniqueness contract.
8. **`0035b`/`0036b` ownership.** They are deferred; confirm P7/P8 owners and
   that they are not created in P1.

## 14. Stop condition

This is a specification. Do not create migrations or modify code. P1 remains
unauthorized.
