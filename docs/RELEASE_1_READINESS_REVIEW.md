# Release 1 Readiness Review

Status: **read-only architecture and engineering review**. Nothing has been
implemented. No application source, schema, migration, API, dependency, or
deployment file was changed.

Review date: 2026-11-14
Scope: `api/`, `worker/`, `web/`, migrations, tests, compose/systemd, and the
seven Release 1 design documents.

## 0. Verdict

**Overall verdict: NOT READY for full Release 1 implementation approval.**

> **Post-closure update:** the six blocker areas have since been specified in
> [`RELEASE_1_BLOCKER_CLOSURE_REVIEW.md`](./RELEASE_1_BLOCKER_CLOSURE_REVIEW.md).
> Current readiness is **0 READY, 11 READY WITH CONDITIONS, 1 NOT READY,
> 2 BUSINESS DECISION REQUIRED** for readiness areas. The final decision
> register uses decision-level counts (0/7/1/2 plus P0 informational), so the
> totals are not directly comparable. P0 validation is the next authorized step,
> not implementation. The matrix in section 9 is the pre-closure snapshot; the
> blocker review and final decision register are authoritative.
>
> **P0 executed:** 19 tests, 18 passed, 1 failed (visibility recovery). P0
> requires D9 to add DB lease-expiry re-dispatch; P1 is not authorized. See
> [`RELEASE_1_P0_EXECUTION_REPORT.md`](./RELEASE_1_P0_EXECUTION_REPORT.md).

The **ownership/fencing core** is close to implementable, but the full release
as scoped has concrete design and verification gaps:

- D3 checkpoint/retry lacks a complete identity and validity contract.
- Attempt-scoped artifacts still collide with canonical-path assumptions in
  `customers.py`, `rollup._concat_raw`, and cleanup.
- D11 schedule recovery lacks interval-window identity, schedule-change
  snapshots, deletion policy, and partial-window semantics in the implementation
  plan.
- D9 requires a business decision on task runtime limits and isolated
  Celery/Redis integration tests.
- Completion data is specified, but the job list/detail UI does not yet render a
  partial badge; group/report derivation is not yet wired to it.
- There is no Postgres/Redis concurrency test suite; current tests are
  SQLite-only.

The minimum safe subset (lease/fencing + checkpoint validation + attempt paths)
is **READY WITH CONDITIONS**. It should not be expanded to the full release
until the blockers below are closed.

### Readiness counts (pre-closure snapshot)

The current post-closure counts are 0 READY, 11 READY WITH CONDITIONS, 1 NOT
READY, 2 BUSINESS DECISION REQUIRED. This table records the original readiness
review.

| Classification | Count |
|---|---|
| READY | 0 |
| READY WITH CONDITIONS | 9 |
| NOT READY | 6 |
| BUSINESS DECISION REQUIRED | 1 |

The areas are enumerated in section 9.

## Legend

| Tag | Meaning |
|---|---|
| **[S]** | Verified from source code. |
| **[C]** | Verified from configuration/deployment files. |
| **[T]** | Verified from existing tests. |
| **[A]** | Assumption requiring verification. |
| **[P]** | Requires production/runtime evidence. |
| **[R]** | Proposed Release 1 behavior. |

## 1. Source-level verification

The following findings were re-checked against the repository, not taken from
the design documents.

| # | Finding | File / function / location | Current behavior [S/C/T] | Proposed Release 1 behavior [R] | Compatibility concern | Revision needed? |
|---|---|---|---|---|---|---|
| 1 | Commit then publish | `api/app/routers/jobs.py:324-327`; `api/app/tasks_client.py:17-22` | Job commits `queued`; `send_task` runs after commit, outside the transaction. Broker failure leaves a committed job and a 500. | Insert `job_dispatch_outbox` in the same transaction; publish via dispatcher/inline fast path. | Create returns 201 even if publish fails; old clients see a queued job. | **Yes** (outbox; already planned) |
| 2 | Conditional claim, no fence | `worker/app/db.py:193-230` | Claim is conditional; later writes are by `job_id` only. | Add owner, token, lease expiry, progress; guard every write. | Old workers ignore tokens; deployment sequencing required. | **Yes** |
| 3 | `started_at` overwritten on reclaim | `worker/app/runner.py:229-234` | Reclaim writes `started_at=now()`. | `COALESCE(started_at, now())`; token distinguishes attempts. | ETA/audit behavior changes. | **Yes** |
| 4 | Unconditional terminal writes | `worker/app/runner.py:830-895`; `worker/app/rollup.py:85`, `228-241` | Completion/failure/cancel writes have no source-status/token predicate. | Guarded terminal finalize; cancel dominance. | Cancel can no longer be overwritten; rollup can no longer complete after cancel. | **Yes** |
| 5 | Immediate pause/cancel via ORM | `api/app/routers/jobs.py:829-865`; `groups.py:236-240` | Status is written directly; no request timestamps; bulk/group cancel uses an ORM status assignment. | Conditional updates; request timestamps; owner remains for running; derived `phase`/`is_finalizing`. | Same status codes; additive phase fields; download gating. | **Yes** |
| 6 | Reaper uses event age | `worker/app/scheduler.py:192-249` | `running` + no event for `stale_job_minutes` -> `failed`. | Lease expiry + progress timeout + reaper grace; event fallback only during mixed versions. | A live worker with no event can be failed; tests and monitoring required. | **Yes** |
| 7 | Retry does not resume | `api/app/routers/jobs.py:975-996`; `scheduler.py:211-214` | New job copies window/settings but not checkpoint; reaper message says "resume." | Resume only with validated checkpoint/artifact/store; otherwise restart with a reason. | Behavior change; `RETRY_MODE`; message/UI must match. | **Yes** |
| 8 | Retry drops group/lineage | `jobs.py:975-996`; `groups.py:308-325` | Single retry drops `group_id`; group retry sets `created_by=user.email` and drops `rollup_of`. | Copy `group_id` or explicit group retry; preserve lineage. | Group counts/report ownership improve. | **Yes** |
| 9 | Rollup bypasses claim | `worker/app/rollup.py:80-86` | Writes `running` unconditionally; no pause/cancel poll; duplicate dispatch can overlap. | Claim/lease/guarded writes/cancel poll; source winner per window. | Canceled rollup now stops; partial sources marked. | **Yes** |
| 10 | S3 keys shared / no lock | `worker/app/s3.py:97-179`; `worker/app/tasks.py:180-228`; `jobs.py:488-507` | Object key is job/label/timeframe; concurrent retries write the same key; no pending lock. | Unique attempt prefix + `s3_attempt_token` + `s3_uploading_at` + DB pointer/manifest. | New object layout; old `s3_uri` remains readable. | **Yes** |
| 11 | Canonical local paths | `worker/app/runner.py:151-180`; `rollup.py:285`; `scheduler.py:322`; `customers.py:73-86` | Code assumes `job_<id>.csv`, `.summary.csv`, `.distinct.sqlite`, etc. | Attempt-scoped paths; `store_path`; update cleanup/rollup/customers. | External path consumers break; download names unchanged. | **Yes** |
| 12 | Customer delete hardcodes names | `api/app/routers/customers.py:73-86` | Deletes conventional names plus recorded paths. | Also scan/record attempt paths; update schedule-window/deletion policy. | Preview/attempt orphans otherwise leak; ledger references can dangle. | **Yes** |
| 13 | Rollup concat hardcodes path | `worker/app/rollup.py:285` | `_concat_raw` writes `job_<id>.csv`. | Use the rollup attempt path and publish under lease. | Two attempts could share a file. | **Yes** |
| 14 | Cleanup hardcodes store | `worker/app/scheduler.py:322`; `rollup.py:130` | Reads canonical `job_<id>.distinct.sqlite`. | Use `jobs.store_path` with legacy fallback; scan unreferenced attempts. | Old rollup/cleanup miss attempt stores. | **Yes** |
| 15 | Report derives from `created_at` | `api/app/routers/reports.py:161-165`, `100-125` | Day keyed by creation time; only completed rows count; failed dominates. | Ledger/window start; `partial` propagation; successful attempt per window. | Historical report values change; flag/announce. | **Yes** |
| 16 | Group derivation lacks partial child | `api/app/routers/groups.py:38-50` | `partial` comes only from failed/canceled children. | Any child `completion_state=partial` -> group `partial`. | Group status changes for partial children. | **Yes** |
| 17 | Web has no completion/phase fields | `web/lib/api.ts:265-335`, `364-371`; `jobs/page.tsx:681`; `jobs/[id]/page.tsx:373` | `Job` type has status/S3 but no `completion_state`/`phase`; status badge is the only signal. | Add fields; show a partial badge; consume phase/finalizing. | Old clients ignore; new UI must not treat partial as clean. | **Yes** |
| 18 | Celery config has no visibility/time limit | `worker/app/celery_app.py:20-37` | `acks_late`, reject-on-lost, prefetch 1; no visibility timeout; no time limits; `result_expires=3600`. | Explicit visibility 3600; time-limit decision; ignore result or longer expiry. | Long tasks redeliver hourly; hung task can hold a slot. | **Yes** (D9 decision) |
| 19 | Worker topology | `docker-compose.yml:61-86`; `docker-compose.prod.yml:18-23`; `install-prod.sh:337,363` | One worker service with `-B`, concurrency 4; API 4 uvicorn workers. | Dedicated single beat; workers without `-B`; scan lock. | Scaling worker=N creates N beats. | **Yes** (deployment) |
| 20 | SQLite-only tests | `api/tests/conftest.py:33-56`; `worker/tests/conftest.py:27-39` | API in-memory SQLite; worker SQLite file. | Real Postgres/Redis concurrency/lifecycle suite. | SQLite cannot prove row-lock/fencing races. | **Yes** (test infra) |
| 21 | Alembic transaction | `api/migrations/env.py` | All migrations in one transaction; no `CREATE INDEX CONCURRENTLY`. | Audit/backfill; separate concurrent index step or maintenance window. | `CONCURRENTLY` fails inside the transaction. | **Yes** (migration plan) |
| 22 | Worker DB pool default | `worker/app/db.py:176-178` | Default SQLAlchemy pool (5+10). | Size to concurrency + heartbeat/progress margin. | Live resize can starve ownership writes. | Condition |
| 23 | `delete_job_files` vs S3 retry | `jobs.py:868-910`; `tasks.py:180-228` | Can delete local files while an S3 retry is uploading; retry then fails. | Gate delete on `s3_uploading_at`/terminal age or coordinate. | User-visible 409/404; no data corruption. | Condition |
| 24 | Schedule UTC vs model comment | `worker/app/scheduler.py:81-87`; `api/app/models.py:133-135` | Runtime uses UTC; model comment says IST. | Document UTC; no DST; ledger `window_key`. | Report expectations. | **Yes** (docs/schema) |
| 25 | `scan_schedules` status-blind | `worker/app/scheduler.py:94-108`, `140-177` | Any job for a window blocks re-extraction; `last_run_at` advances before dispatch. | Ledger owns obligation; failed/missing retry; successful attempt winner. | Reports/scheduler truth changes. | **Yes** |
| 26 | `_mark_failed` bypasses ownership | `worker/app/tasks.py:112-136` | Can fail a `queued` or `running` job without a lease/token. | Queued conditional fail; running only with lease; `LeaseLost` no write. | Old workers ignore. | **Yes** |
| 27 | S3 retry no attempt | `jobs.py:488-507`; `tasks.py:180-228` | Repeated retries upload same keys. | Attempt token/lock/manifest/unique prefix. | New layout; old URIs remain. | **Yes** |
| 28 | `customers` deletes jobs with ledger | `customers.py:146-163` | Deletes jobs/events; no ledger handling. | Cancel/retain ledger; update `current_job_id`; prevent dangling references. | Deletion semantics. | **Yes** |
| 29 | Low-disk purge leaves unmatched path | `scheduler.py:352-367` | Nulls output/summary/counts, not unmatched. | Null all four paths; use helper. | Broken links. | Condition |
| 30 | No status CHECK | `api/app/models.py:44-97`; migrations | No DB CHECK on status/completion. | Audit then add CHECKs. | Legacy invalid values fail migration. | Condition |

## 2. D3 - Checkpoint and retry recovery

### 2.1 Verified mechanics

- `Checkpoint` is a JSON blob in `jobs.checkpoint` with
  `completed_chunks`, `rows_written`, `current_chunk_start`,
  `next_chunk_start`, `skipped_batches` **[S]**
  (`worker/app/last9/checkpoint.py:15-58`).
- `on_chunk` flushes/fsyncs the CSV and unmatched file, flushes the aggregator
  store, then updates the job counters/checkpoint and inserts a chunk event in
  one DB transaction **[S]** (`runner.py:571-630`).
- `DistinctStore` is a SQLite file with a `last_chunk_committed` marker; a
  replayed chunk drops duplicate occurrence counts **[S]**
  (`last9/distinct_store.py:150-179`).
- Resume currently uses `next_chunk_start` and truncates the CSV to
  `file_offset` **[S]** (`runner.py:403-410`; `extract.py:93-100`).
- Retry currently creates a new row without copying the checkpoint
  **[S]** (`jobs.py:975-996`).
- No checkpoint contains a job id, attempt id, config fingerprint, or artifact
  path; it relies on the job row and `output_file_path` **[S]**.

### 2.2 Recovery validation contract

A checkpoint is **resumable** only when all conditions hold:

1. `checkpoint_version` is supported.
2. The checkpoint belongs to the same job, or the current job's `retry_of`
   points to the checkpoint's `source_job_id`. A copied checkpoint must update
   `source_job_id` to the new job and retain `lineage_root_id`.
3. The `spec_fingerprint` matches the current job's immutable extraction
   inputs: region, index target, start/end, filter spec, chunk/batch settings,
   output format, and aggregation config. Credential changes for the same index
   are allowed; changing the index/window/filter/format requires restart.
4. `completed_chunks >= 0`; `next_chunk_start` is between `start_epoch` and
   `end_epoch`; `current_chunk_start < next_chunk_start`.
5. `file_offset >= 0`, the artifact exists (unless `skip_raw_output`), is not a
   zip, and `file_offset <= file_size`.
6. The artifact path is inside the configured storage root and belongs to this
   job/lineage; no path traversal or cross-job path.
7. The DB checkpoint was committed after the file was flushed/fsynced.
8. For aggregation, `store_path` exists and the store's
   `last_chunk_committed >= completed_chunks - 1`. A store behind the
   checkpoint is invalid; a store one chunk ahead is allowed (replay drops
   counts).
9. If `rows_unmatched > 0` or `unmatched_offset > 0`, the unmatched artifact
   exists; otherwise resume would publish an incomplete unmatched artifact.
10. `skipped_batches == 0` and `completion_state != partial`. A partial job
    should restart to retry gaps, not resume with the gaps frozen.
11. The job is not a preview being promoted to a full run.
12. The source data is assumed append-only/immutable for the historical window.
    If it is mutable, resume produces a mixed snapshot; restart is required.

### 2.3 Crash cases

| Crash point | Checkpoint | Artifact | Store | Result |
|---|---|---|---|---|
| Before fsync | old | partial suffix | old | Resume old prefix; replay chunk. |
| After fsync before DB commit | old | full chunk suffix | possibly new | Resume old prefix; replay; store marker drops duplicate counts. |
| During DB commit | atomic old/new | full | committed | Old -> replay; new -> next. |
| After DB commit | new | full | committed | Resume next; no replay. |
| Store committed, DB not | old | full | ahead | Merge store + preserve marker; replay rows; no double count. |
| DB committed, store behind | new | full | behind | Invalid for aggregation; restart. |
| Artifact newer than checkpoint | old | extra suffix | any | Copy only old offset; replay; safe. |
| Checkpoint newer than artifact | new | shorter | any | Invalid; restart/fail. |
| Artifact missing | any | missing | any | Restart from zero. |
| Artifact corrupt/zip | any | corrupt | any | Restart; no tail-only file. |

### 2.4 Decision matrix

| Condition | Resume | Restart | Fail manual | Reason |
|---|---|---|---|---|
| No checkpoint, no artifact | - | Yes | - | Nothing to resume. |
| Valid checkpoint + valid artifact + valid store + fingerprint + lineage + no gaps | **Yes** | - | - | All invariants hold. |
| Checkpoint valid, artifact missing | - | Yes | - | Committed prefix unavailable. |
| Checkpoint valid, artifact shorter than offset/corrupt/zip | - | Yes | - | Cannot trust the prefix. |
| Artifact exists, checkpoint missing | - | Yes | - | Cannot know committed boundary. |
| Checkpoint newer than artifact | - | Yes | - | Missing committed bytes. |
| Artifact newer than checkpoint | **Yes** | - | - | Copy committed prefix; replay suffix. |
| Store missing/behind for aggregation | - | Yes | - | Counts would be incomplete. |
| Store one chunk ahead | **Yes** | - | - | Marker makes replay idempotent. |
| Fingerprint mismatch | - | Yes | - | Different source/window/config. |
| Lineage mismatch / no retry link | - | Yes | - | Checkpoint belongs to another job. |
| `skipped_batches > 0` / partial | - | Yes | - | Resume would freeze gaps. |
| Unmatched artifact expected but missing | - | Yes | - | Incomplete unmatched artifact. |
| Preview -> full | - | Yes | - | Preview is intentionally capped. |
| Unknown checkpoint version | - | - | **Yes** | Do not guess a schema. |
| Artifact path outside storage root | - | - | **Yes** | Security/integrity; do not touch. |
| Storage permission/IO error | - | - | **Yes** | Do not silently re-extract over a broken volume. |

**Safest Release 1 recommendation:** **restart by default**. Resume only for a
same-lineage, same-fingerprint, clean (no gaps), non-preview checkpoint with a
valid artifact/store. Partial/unknown/mismatched -> restart; unknown schema,
path escape, or filesystem/IO failure -> manual intervention.

**Data-integrity caveat:** resume is chunk-consistent, not a point-in-time
snapshot across attempts. If source data can change in the completed prefix,
resume cannot correct it. This is an assumption **[A]/business decision**.

## 3. D8 - Lease, heartbeat and progress timing

### 3.1 Verified timing facts

- Status poll: 10 s **[S]** (`runner.py:57`).
- Current heartbeat event: 300 s **[S]** (`runner.py:503`).
- Reclaim: 10 min; stale job: 60 min **[C]** (`worker/app/config.py:56-60`).
- Last9 HTTP timeout: 60 s; 10 attempts; backoff cap 300 s; a single chain can
  take roughly 18 minutes **[S]** (`client.py:58-72`, `197-198`;
  `runner.py:367`).
- S3: connect 10 s, read 120 s, 5 retries **[S]** (`s3.py:57-59`).
- Worker/API clocks are not synchronized by the app; use DB time **[S/A]**.
- No current progress instrumentation; current liveness is `job_events` **[S]**.

### 3.2 What counts as progress

A `ProgressClock` per attempt, updated by:

| Component | Event | Persisted? |
|---|---|---|
| Runner row loop | each row written | In-memory mark; `progress_at` on heartbeat if changed |
| Runner chunk | after fsync + DB checkpoint commit | In-memory + `progress_at` through heartbeat |
| Last9 client | before/after each HTTP attempt and backoff | In-memory; optional callback |
| Artifact writer | before/after fsync, zip, summary, counts | In-memory |
| Finalizer | start/end of terminal transaction | In-memory + heartbeat |
| S3 post-completion | not under job lease | No |

A heartbeat that finds `progress_changed=true` sets `progress_at=now()`;
otherwise it only renews `heartbeat_at`/`lease_expires_at`. A hung main loop
therefore stops renewing at the progress timeout.

### 3.3 Timing model

```
heartbeat interval (60s) < lease_ttl (600s) / 3
reclaim_grace (60s) << lease_ttl
progress_timeout (3600s) >> max legitimate silent stage
reaper_grace (60s) << progress_timeout
```

| Failure | Recovery bound |
|---|---|
| Dead process | lease 10 min + reaper grace 1 min ~ 11 min |
| Hung main loop, heartbeat alive | progress 60 min + lease 10 min + reaper 1 min ~ 71 min |
| DB outage | stop at TTL safety margin; recover when DB returns |
| Redis outage | task continues; no redelivery/beat; recover when Redis returns |
| S3 slow (post-completion) | no job lease; retry/cleanup path |
| Long Last9 retry chain | progress callback per attempt; silence <= request timeout/backoff |

### 3.4 Can a healthy worker be fenced?

Yes, if a legitimate silent stage exceeds `progress_timeout`. Mitigations:

- Instrument Last9 attempt/backoff, chunk/fsync, zip/finalization.
- Set DB `statement_timeout`/`lock_timeout` below the progress timeout.
- Measure p99 silent-stage duration; do not keep 1800 without evidence.
- Use 3600 as the conservative Release 1 default until measured.

### 3.5 Can a hung worker retain ownership?

Only if both the main loop and the progress tracker/heartbeat logic are broken.
The progress-aware heartbeat plus `progress_at` reaper branch are intended to
prevent it. Add a test that a heartbeat thread cannot renew without progress.

### 3.6 Configuration strategy

Keep 600/60/60/3600/60 as **initial conservative defaults**, not final truths.
Measure:

- p99 chunk duration and max silent interval between progress marks;
- p99 Last9 request/retry chain;
- p99 zip/summary/finalization duration;
- p99 DB query/lock wait;
- worker/DB network latency.

Tune progress to 2-3× the measured max silent stage, never below it. Alert at
80% of the timeout.

## 4. D9 - Celery and Redis delivery semantics

### 4.1 Four different events

1. **Celery ack:** the broker removes/acknowledges the message; it may happen
   after the task returns, after `self.retry`, or not at all on worker loss.
2. **Celery task completion:** the task function returned or raised; the result
   backend may record success/failure and expire after `result_expires`.
3. **Database job completion:** `jobs.status` is terminal; this is the product
   truth.
4. **Lease release:** `owner_id=NULL`, `lease_expires_at=NULL`; can happen
   before or after ack, and a duplicate task can be acked without touching the
   job.

They are not the same event. The DB claim/lease is the execution authority; the
Celery result is diagnostic.

### 4.2 Configuration decision table

| Setting | Current | Recommended | Reason | Risk if wrong | Verification |
|---|---|---|---|---|---|
| `task_acks_late` | True | **True** | Ack after execution; redelivery on crash. | Early ack loses work on worker death. | Integration kill test. |
| `task_reject_on_worker_lost` | True | **True** | Immediate redelivery on worker loss. | Lost job waits for reaper. | SIGKILL test. |
| `task_acks_on_failure_or_timeout` | default True | **True (explicit)** | Failed task is recorded on job; requeue loops are worse. | Requeue storm. | Failure test. |
| `worker_prefetch_multiplier` | 1 | **1** | Fair queueing. | Hoarding/ starvation. | Queue test. |
| `visibility_timeout` | unset (default 3600) | **3600 explicit** | Long tasks redeliver hourly; claim makes safe. | Silent behavior change on upgrade. | Long-task redelivery test. |
| `result_backend visibility_timeout` | unset | **3600 explicit** | Consistent ETA/retry behavior. | Retry loops/misbehavior. | Retry ETA test. |
| `result_expires` | 3600 | **ignore_result for `run_job` or > max job** | Result state expires before long jobs. | Support confusion; Redis churn. | Long-task result inspection. |
| `task_time_limit` | unset | **business decision** | Hung task holds a slot; hard kill resumes from checkpoint. | Slot exhaustion vs. killing healthy long tasks. | Kill/resume test. |
| `task_soft_time_limit` | unset | **business decision** | Controlled stop/checkpoint before hard kill. | Unhandled soft exception. | Soft-limit test. |
| Redis `maxmemory-policy` | not set in compose | **noeviction / enough memory** | Avoid broker key eviction. | Lost tasks/queue corruption. | Redis memory test. |
| AOF | on | **on** | Broker/result persistence across restart. | Lost unacked messages. | Redis restart test. |
| `stop_grace_period` (Docker) | default ~10 s | **60-120 s** | Give worker warm shutdown a chance. | SIGKILL mid-chunk (recoverable but noisy). | Docker stop test. |

### 4.3 Retry / ETA

- `self.retry` countdown must be shorter than the visibility timeout; use
  `<=300 s`, max 3.
- On redelivered + live lease: bounded retry, do not steal.
- On redelivered + expired lease: claim.
- On terminal: exit.
- On duplicate non-redelivered + running: exit/ack; the original owns.
- If max retries exhausted: ack and rely on reaper/manual retry.

### 4.4 Required integration tests

- Celery Redis redelivery after kill -9.
- Redelivery while original alive (long task).
- `self.retry` ETA under Redis visibility.
- Redis restart with AOF; unacked message behavior.
- Worker warm shutdown vs SIGKILL.
- Hard/soft time-limit behavior, if approved.

## 5. D10 - Completion integrity

### 5.1 Three dimensions

- **Execution status:** `queued/running/paused/completed/failed/canceled`.
- **Completion state:** `unknown/complete/partial`.
- **Artifact publication:** local pointer and S3 attempt/pointer (derived).

`completed` + `completion_state=partial` is valid: execution finished, data is
incomplete. It must not be displayed as a clean success.

### 5.2 Minimal contract

| Case | `status` | `completion_state` | `gap_count/reason` | Group/report |
|---|---|---|---|---|
| Clean full run | completed | complete | 0 / none | completed/ok |
| Skipped ID batches | completed | partial | batches / `skipped_batches:N` | partial |
| Rollup skipped source | completed | partial | sources / `rollup_skipped:N` | partial |
| BQ rows dropped | completed | partial | rows / `bq_unmatched:N` | partial |
| Canceled | canceled | partial | 0 / canceled | canceled/partial |
| Failed before coverage | failed | unknown | 0 / error | failed |
| Reaped/unknown | failed | unknown | 0 / reaped | failed |
| Preview | completed | partial | 0 / preview | excluded by ownership |
| Legacy | any | unknown | 0 / none | do not claim complete |

### 5.3 Derivation inventory

- `api/app/routers/groups.py:_group_status` -> must include
  `completion_state=partial`.
- `api/app/routers/reports.py:_day_status` -> must include partial and use the
  ledger/successful attempt.
- `reports.py:_rows` -> currently sums completed only; decide whether partial
  rows are shown with a marker or excluded from "rows". Recommend show rows but
  status partial, and label them.
- `api/app/routers/jobs.py:JobStats` -> add partial counts if the dashboard
  should show them.
- `web/lib/api.ts:Job` -> add fields; `JOB_TONE` remains status-only.
- `web/app/jobs/page.tsx:681`, `jobs/[id]/page.tsx:373` -> add a partial badge.
- `web/app/groups/[id]/page.tsx` -> already has `partial` group status; ensure
  child partial is mapped.
- `web/app/reports/page.tsx` -> `partial` day status already typed; verify copy.

A shared Python helper and a generated/asserted TypeScript contract are needed
to prevent the same divergence the audit found.

## 6. D11 - Schedule ledger and recovery

### 6.1 Verified schedule facts

- `Schedule` has `interval_seconds`, `lookback_seconds`, `calendar_day`,
  `last_run_at`; no timezone field **[S]** (`api/app/models.py:125-151`).
- Runtime calendar boundary is UTC **[S]** (`scheduler.py:81-87`); the model
  comment says IST **[S]** (`models.py:133-135`) — documentation drift.
- Interval schedules are rolling `[now-lookback, now]`; `start_epoch` changes
  every tick ** [S]** (`scheduler.py:76-79`).
- `_already_extracted` checks `(created_by,start_epoch)` and ignores status
  **[S]** (`scheduler.py:94-108`).
- `last_run_at` advances before dispatch **[S]** (`scheduler.py:175-188`).
- Schedule update mutates interval/calendar_day/lookback in place
  **[S]** (`api/app/routers/schedules.py:236-284`).
- Schedule delete removes the schedule; jobs remain **[S]**
  (`schedules.py:296-304`).

### 6.2 Window lifecycle

```
due -> pending -> dispatched -> running -> completed(complete|partial)
                                  |          |
                                  |          +-> partial: manual retry only
                                  +-> failed -> retry (attempts < max) -> pending
                                  +-> canceled (delete/manual)
```

- **Due:** `scan_schedules` computes owed slots; upserts ledger rows.
- **Pending:** no active job; eligible at `next_attempt_at`.
- **Dispatched:** job + outbox committed; job is queued.
- **Running:** worker claim; window status can be set by terminal write or
  derived from job. Recommend worker terminal write updates it in the same
  transaction.
- **Completed:** job terminal `completed`; copy `completion_state`.
- **Failed:** job terminal `failed` or dispatch failure after attempts; retry
  with backoff.
- **Canceled:** schedule deleted/user cancel; keep history.
- **Partial:** completed + completion_state partial; no auto-retry by default.
- **Missed:** derived from pending/expected cadence; not a persisted status.

### 6.3 Window identity and changes

- `window_key`: `day:YYYY-MM-DD` for calendar-day schedules;
  `slot:<epoch>` for interval schedules. `start_epoch` alone is not stable for
  rolling lookback.
- `scheduled_for` for display/backoff.
- `config_snapshot` at creation: source, credential/index, filter, format,
  chunk/batch, S3, aggregation. A retry uses the snapshot; schedule edits apply
  to future windows.
- Calendar-day schedules are UTC; no DST. Interval schedules use UTC slots.
- Schedule delete: mark pending/dispatched windows canceled; keep terminal
  rows; do not delete job history. A running window may finish; its terminal
  update keeps audit.
- Duplicate prevention: unique `(schedule_id, window_key)` + one active job per
  window; scan lock for new beat instances; stop old `-B` beat before enabling.
- Winner selection: `current_job_id`/successful attempt; reports/rollups must
  not include every terminal retry.

### 6.4 Crash matrix

| Crash stage | State | Recovery |
|---|---|---|
| After ledger insert, before job | pending | Dispatcher creates job. |
| After job insert, before outbox | transaction rollback | Ledger pending; retry. |
| After outbox commit, before publish | pending outbox | Dispatcher publishes. |
| After publish, before claim | queued | Worker/outbox reconciliation. |
| After claim, before progress | running | Lease/reaper; window running. |
| During extraction | running | Lease/reaper; retry. |
| After job terminal, before window update | must be same transaction | Impossible; enforce. |
| After window completed, before report read | completed | Report reads ledger. |
| Beat crash | no scan | Orchestrator restart; owed windows. |
| Two beats | lock/unique | One window; loser skips. |

### 6.5 Schedule model authority

- `Schedule` remains authoritative for **configuration and cadence**.
- `schedule_windows` owns **per-window obligation/execution state**.
- `jobs` owns **execution/artifact truth** for an attempt.
- `last_run_at` remains a **scan/dispatch cursor**, not success.
- Report/rollup success comes from the ledger's completed winner + the job's
  completion state.

### 6.6 Release scope

Minimum safe Release 1: ledger for both calendar-day and interval schedules,
window key, one active job, retries/backfill, winner selection, scan lock.

If schedule work must be split: Release 1 can ship **ledger + calendar-day +
beat singleton**, while interval schedules remain legacy; but then interval
duplicate/retry risk remains and must be explicitly accepted. Do not mix a
ledger for new scans with old `-B` inserts.

## 7. Remaining architecture risks

### A. Fencing and worker ownership

- All worker writes listed in `WORKER_OWNERSHIP` section 11 need `update_owned`
  and rowcount checks.
- `_mark_failed` (`tasks.py:112-136`) is a concrete bypass; make it conditional.
- `upload_job_s3` is not a job-lease write after completion; use S3 attempt
  fencing.
- `cleanup_exports`/`delete_job_files` are system/user writes; do not require
  job lease but must not race with an active S3 upload or a live attempt.
- A zero-row update must raise `LeaseLost`; the runner must close files and not
  publish. Background heartbeat must set `lease_lost`; the main loop must check
  it every row.
- No worker write should bypass the guard; the blueprint must include a static
  review/grep check.

### B. Cancellation and pause/resume

- Immediate status + derived phase + request timestamps + owner/token is
  **implementable**, but the API/UI/report must use `is_finalizing`/phase.
- Cancel dominance is enforced by the terminal SQL/token; tests both orderings.
- Pause/resume race is closed by resume clearing owner/bumping token.
- Download URLs should be withheld while `is_finalizing`.
- Reporting systems must not count a canceling row as a completed run; they
  already see status canceled.

### C. Attempt-scoped artifacts

- Canonical-path assumptions are concrete blockers: `customers.py`,
  `rollup._concat_raw`, `scheduler.cleanup_exports`, `rollup.find_source_jobs`.
- `runner.output_path/summary_path/...` must accept an attempt token.
- Published pointer is `output_file_path`/`summary...`/`store_path`.
- S3 pointer is `s3_published_attempt`/URIs/manifest.
- External consumers of `job_<id>.csv` break; document/migrate.

### D. Transactional outbox

- Outbox row + job row in one transaction; inline fast path after commit;
  dispatcher with `SKIP LOCKED`/lock columns; retry/backoff; reconciliation.
- Duplicate publish is safe via claim; duplicate **job creation** after a lost
  HTTP response is not solved (Release 2 idempotency key).
- Batch/group all-or-nothing includes outbox rows.
- Cancel before dispatch: queued canceled job remains; dispatcher publishes; the
  worker claim sees canceled and exits. Add test.
- Job deletion: no delete endpoint for jobs; customer delete must clean outbox
  rows/windows.

### E. S3 publication

- Unique attempt prefix; DB pointer is the publication commit; manifest audit.
- Multipart cleanup requires a lifecycle rule or explicit abort task; not
  proven for all S3-compatible stores.
- Stable external key is not provided in Release 1; document.
- If DB publish fails, objects are orphaned; cleanup by attempt prefix; never
  delete the published attempt.
- If a prior published attempt exists and a retry fails, keep the pointer and
  show the retry error separately.

### F. Beat singleton

- Dedicated `celery beat`, one replica; workers without `-B`.
- Scan lock `SET NX EX 90` with owner token, or Postgres advisory lock.
- Lock expiration: unique ledger/outbox is the correctness backstop.
- Crash: orchestrator restart; owed windows/backfill.
- Overlap: stop old `-B` before enabling ledger; new beat instances coordinate
  via lock.
- Two instances starting simultaneously: lock NX; one wins; loser skips.
- Network partition: lock may expire; ledger prevents duplicate jobs; old beat
  must not run.

## 8. Migration and test evidence

- Postgres 16 in compose; SQLite in tests **[C/T]**.
- Alembic runs in one transaction **[C]**; `CREATE INDEX CONCURRENTLY` needs a
  separate step.
- No migration test against Postgres is present **[T]**.
- API/worker tests use SQLite **[T]**; no Redis integration tests **[T]**.
- Real Postgres/Redis tests are mandatory for claim/fencing/outbox/schedule.
- The detailed field/table review is in
  [`RELEASE_1_MIGRATION_PLAN.md`](./RELEASE_1_MIGRATION_PLAN.md).

## 9. Readiness matrix

| Area | Classification | Why |
|---|---|---|
| Job creation/outbox | READY WITH CONDITIONS | Design sound; create idempotency residual; reconciliation tests. |
| Lease/fencing | READY WITH CONDITIONS | Core specified; needs `progress_at`, instrumentation, Postgres tests. |
| Cancellation/pause | READY WITH CONDITIONS | Phase/finalizing design; API/UI/tests pending. |
| D3 checkpoint/retry | **NOT READY** | Identity/validation contract was incomplete; matrix now defined but needs implementation. |
| Attempt artifacts/stores | **NOT READY** | Canonical assumptions in customers/rollup/cleanup. |
| S3 publication | READY WITH CONDITIONS | Model sound; multipart/listing/conditional behavior unverified. |
| D10 completion | READY WITH CONDITIONS | Fields defined; group/report/job UI wiring pending. |
| D11 schedule ledger | **NOT READY** | Interval identity, config snapshot, deletion, partial, winner selection need implementation. |
| D9 Celery/Redis | **BUSINESS DECISION REQUIRED** | Time-limit policy and Redis integration tests unresolved. |
| Beat singleton | READY WITH CONDITIONS | Dedicated beat + lock; deployment/test pending. |
| Migrations | READY WITH CONDITIONS | Additive plan; Postgres audits/concurrent index/tests pending. |
| Frontend | READY WITH CONDITIONS | Partial/phase fields/badge pending. |
| Rollup | **NOT READY** | Canonical concat/store/source-winner changes. |
| Tests/observability | **NOT READY** | No Postgres/Redis suite, no baselines. |
| Cleanup/retention | **NOT READY** | Canonical paths and S3/delete races. |
| API compatibility | READY WITH CONDITIONS | Additive fields; status vocabulary unchanged. |

## 10. Blocking findings

1. **D3 is not implementable as written** without checkpoint identity,
   fingerprint, lineage, store-marker, missing-artifact, and partial-gap
   rules. The matrix in section 2 is the proposed contract.
2. **Attempt paths are incomplete** until `customers.py`, `rollup._concat_raw`,
   `rollup.find_source_jobs`, `scheduler.cleanup_exports`, and `runner` path
   builders are updated.
3. **D11 is incomplete** for interval schedules, schedule edits, deletion, and
   partial windows. `window_key`, `scheduled_for`, `config_snapshot`, and
   `completion_state` are now proposed; they need implementation.
4. **D9 needs a business decision** on soft/hard task limits; without it a hung
   process can hold a worker slot forever.
5. **Completion is not user-visible** until the web `Job` type, list/detail
   badges, group derivation, and report derivation are updated.
6. **No real Postgres/Redis concurrency suite exists**; SQLite tests cannot
   prove fencing, outbox, or schedule correctness.
7. **Canonical-path cleanup can leak or mis-delete** after attempt-scoped
   artifacts; this is a data-loss/storage risk, not cosmetic.

## 11. Assumptions and production evidence

- Production Postgres isolation/read behavior.
- Redis `visibility_timeout` actual behavior and unacked-message/AOF recovery.
- S3-compatible multipart/listing/conditional-write behavior.
- Exports volume filesystem semantics.
- Max legitimate silent stage and max job runtime.
- External consumers of canonical local/S3 paths.
- Real p99 chunk/finalization/DB timings.
- Whether source data in a completed prefix can change.

## 12. Conclusion

Release 1 is **not ready for full implementation approval**. The ownership core
is close, but the release cannot claim state integrity while D3, artifact
cleanup, D11, D10 UI/derivation, and the Postgres/Redis test evidence remain
open.

The implementation blueprint and phase gates are in
[`RELEASE_1_IMPLEMENTATION_BLUEPRINT.md`](./RELEASE_1_IMPLEMENTATION_BLUEPRINT.md).
The final classification and approval questions are in
[`RELEASE_1_FINAL_DECISION_REGISTER.md`](./RELEASE_1_FINAL_DECISION_REGISTER.md).
