# State Machine Implementation Roadmap

Status: proposal. Nothing in this document has been implemented. No schema,
migration, API, worker, or web change was made for this task.

> **Release 1 note:** the implementation-ready Release 1 design is
> [`RELEASE_1_DESIGN.md`](./RELEASE_1_DESIGN.md). Its migration numbers and
> milestone order supersede the illustrative numbers in this broader roadmap.
> This document remains the long-range view; the Release 1 documents are the
> executable specification.

Inputs:

- [`STATE_MACHINES.md`](./STATE_MACHINES.md) - 40 validated machines.
- [`JOB_LIFECYCLE.md`](./JOB_LIFECYCLE.md) - canonical lifecycle.
- [`STATE_TRANSITIONS.md`](./STATE_TRANSITIONS.md) - transition registry.
- [`STATE_DEPENDENCIES.md`](./STATE_DEPENDENCIES.md) - coupling and cycles.
- [`STATE_MACHINE_RISKS.md`](./STATE_MACHINE_RISKS.md) - risk register.

Legend: **[V]** verified current behavior, **[R]** recommendation, **[A]**
assumption.

## 1. Principles

1. **Do not add a state-machine library.** The domain is small; guarded SQL and
   a shared module are enough.
2. **Keep the public status vocabulary.** Add orthogonal fields instead of a
   seventh terminal status.
3. **Persist only what concurrency requires.** Owner/lease, cancel request,
   completeness, and an S3 attempt marker qualify. Group, report, downloadable,
   and expiry states stay derived.
4. **Migrate additively first, enforce later.** Every schema change must be
   safe for the previous application version.
5. **Worker before API enforcement.** Old workers cannot send a lease token; do
   not reject them before they are upgraded.
6. **Every phase has a rollback that does not require data loss.**
7. **Tests are part of the phase, not a later phase.** A transition change
   without a concurrency test is not done.

## 2. Phase overview

| Phase | Theme | Risk reduced | Schema? | API break? |
|---|---|---|---|---|
| 0 | Baseline and observability | Detection | No | No |
| 1 | Critical data integrity | R-01, R-03, R-04, R-06, R-07, R-08 | Yes (additive + one index) | No |
| 2 | State-model standardization | R-09, R-11, R-22 | Yes (additive) | Additive fields |
| 3 | Concurrency | R-02, R-16, R-19, R-20 | Yes (optional S3 lock) | No |
| 4 | Reporting consistency | R-10, R-12, R-13, R-14 | Optional | Response values change |
| 5 | Frontend consistency | R-17, R-18, R-21, R-27 (UI) | No | Additive |
| 6 | Testing and regression protection | All | No | No |

## 3. Phase 0 - baseline and observability

### 0.1 Record the current transition matrix

- **Files:** `docs/STATE_TRANSITIONS.md`, `api/tests/test_jobs.py`,
  `worker/tests/test_runner.py`, `worker/tests/test_scheduler.py`.
- **DB impact:** none.
- **API impact:** none.
- **Migration:** none.
- **Compatibility risk:** none.
- **Rollback:** documentation revert.
- **Tests:** add characterization tests for the current behavior before
  changing it. Specifically: cancel while running, pause then resume, reclaim,
  rollup cancel, schedule failed-window scan.

### 0.2 Add structured transition logging

- **Files:** `api/app/routers/jobs.py`, `worker/app/runner.py`,
  `worker/app/rollup.py`, `worker/app/scheduler.py`.
- **What:** log `{job_id, from, to, trigger, owner, lease_token}` at INFO on
  every state write. Do not log tokens or payloads.
- **DB:** none.
- **API:** none.
- **Migration:** none.
- **Compatibility:** log volume; sample or aggregate if needed.
- **Rollback:** remove the log lines.
- **Tests:** assert the log record on a transition (caplog).
- **Why:** you cannot measure a race you cannot see. This also gives the
  metrics for phases 1 and 3.

### 0.3 Add metrics

- **Files:** API/worker metrics module (new), `runner.py`, `scheduler.py`.
- **Metrics:** `jobs_transition_total{from,to,trigger}`,
  `jobs_fenced_total`, `jobs_orphaned_queued`, `schedule_windows_duplicate`,
  `rollup_skipped_sources`, `token_refresh_conflict`, `s3_attempt_conflict`.
- **DB/API/migration:** none.
- **Compatibility:** none.
- **Rollback:** disable the exporter.
- **Tests:** metric increment on a simulated transition.

## 4. Phase 1 - critical data integrity

### 1.1 Job lease and fencing

- **Files:** `api/app/models.py`, `worker/app/db.py`,
  `worker/app/runner.py`, `worker/app/rollup.py`,
  `api/app/routers/jobs.py`, `api/app/routers/groups.py`,
  `api/app/schemas.py`, `worker/app/config.py`.
- **DB impact:** add `owner_id` (varchar 128, null), `lease_token` (bigint,
  not null, default 0), `heartbeat_at` (timestamptz, null),
  `cancel_requested_at` (timestamptz, null), `pause_requested_at`
  (timestamptz, null). Add an index on `(status, heartbeat_at)` for the
  reaper/reclaim.
- **API impact:** `JobOut` may expose `lease_token`? No - keep it internal.
  Expose derived `is_stale`/`can_cancel` only if needed. Additive fields are
  safe.
- **Migration:** `0032_job_lease_fencing.py` (additive, nullable/default).
- **Backward-compatibility risk:** old workers do not send a token. Do **not**
  enforce on the first deploy. Add the columns, deploy the new worker that
  acquires and checks, then enable API/DB enforcement.
- **Rollback:** stop enforcing; leave columns. Revert worker code. No data
  loss.
- **Tests:**
  - two claims, one winner;
  - reclaim increments `lease_token`;
  - old token write affects 0 rows;
  - cancel sets `cancel_requested_at`;
  - finalizer cannot write `completed` when cancel is requested;
  - rollup claim and cancel;
  - reaper increments the token.

**Implementation notes:**

- Claim SQL is in `JOB_LIFECYCLE.md` 5.2.
- `worker/app/db.py` currently mirrors the API table; add the columns there
  too.
- The runner must check `rowcount` after every write. A 0-row update means
  "fenced"; close files and return.
- Do not use `job_events.ts` as the lease. Keep it for human-visible liveness.

### 1.2 Cancel dominance

- **Files:** `worker/app/runner.py`, `worker/app/rollup.py`,
  `api/app/routers/jobs.py`, `api/app/routers/groups.py`.
- **DB impact:** none beyond 1.1 (`cancel_requested_at`).
- **API impact:** none; cancel still returns `canceled`.
- **Migration:** none.
- **Compatibility:** a running worker may now keep `canceled` instead of
  overwriting it. That is the intended fix.
- **Rollback:** revert the finalizer guard.
- **Tests:** cancel during the finalization window; assert final `canceled` and
  the partial artifact remains downloadable.

**Implementation notes:**

- API cancel sets `cancel_requested_at` and `status='canceled'` for a queued
  job, or `cancel_requested_at` plus immediate `canceled` for a running job
  (compatibility).
- Worker finalizer:
  `status = 'canceled' if cancel_requested_at else 'completed'`, guarded by
  `status IN ('running','canceled')` and the lease token.
- Rollup must poll the same flag.

### 1.3 Rollup uses the lifecycle

- **Files:** `worker/app/rollup.py`, `worker/app/tasks.py`.
- **DB impact:** none beyond 1.1.
- **API impact:** none.
- **Migration:** none.
- **Compatibility:** a canceled rollup now stops; previously it completed.
  That is the intended fix.
- **Rollback:** revert to the unconditional `running`/`completed` writes.
- **Tests:** duplicate dispatch, cancel, pause, reaper, skipped source.

**Implementation notes:**

- Replace `db.update_job(status="running")` with `claim_job`.
- Check the token on every merge/progress write.
- Poll `status`/`cancel_requested_at` between sources.
- Set `completion_state=partial` when `skipped` is non-empty (phase 2 field;
  until then, set `error_message`).

### 1.4 Schedule window idempotency

- **Files:** `worker/app/scheduler.py`, `api/app/models.py`,
  `api/migrations/versions/0034_schedule_window_unique.py`.
- **DB impact:** partial unique index on
  `jobs (created_by, start_epoch) WHERE created_by LIKE 'schedule:%'`.
- **API impact:** none.
- **Migration:** `0034_schedule_window_unique.py`. Before creating the index,
  run a duplicate audit:
  `SELECT created_by, start_epoch, count(*) ... HAVING count(*) > 1`.
  Resolve duplicates manually or leave the index creation to a maintenance
  window.
- **Backward-compatibility risk:** existing duplicates cause the migration to
  fail. Provide a pre-check and a documented cleanup decision. Use
  `CREATE UNIQUE INDEX CONCURRENTLY` on Postgres.
- **Rollback:** drop the index. The code can keep `ON CONFLICT DO NOTHING`
  only if the index exists; otherwise it is a no-op syntax error on SQLite.
  Use a dialect-aware insert or a transaction + advisory lock for SQLite tests.
- **Tests:** two concurrent scans insert one job; a failed job is not treated
  as covered (policy test); backfill cap.

**Implementation notes:**

- Change `_already_extracted` + insert to one
  `INSERT ... ON CONFLICT (created_by, start_epoch) DO NOTHING RETURNING id`.
- If no id is returned, skip the window.
- Keep the 14-day cap.
- Decide the failed-window policy (R-08) in the same change: covered means
  `completed`, or add a `schedule_runs` row with status. The smallest fix is
  to query `status='completed'` for coverage and let the failed window be
  re-inserted; but that would create a second job for the same window, which
  the unique index blocks. Therefore the policy must be explicit:
  - **Option A (recommended):** a `schedule_windows` table (or `schedule_run`
    row) with `(schedule_id, start_epoch)` and `status`; the unique key is
    there, and a failed row can be retried by updating it.
  - **Option B (smallest):** keep the job as the window record; a failed job
    is not automatically retried. Document it and add a "retry window" manual
    action.

### 1.5 Create -> dispatch handoff

- **Files:** `api/app/routers/jobs.py`, `api/app/routers/groups.py`,
  `api/app/tasks_client.py`, new `api/app/dispatch.py` or
  `api/app/outbox.py`, `worker/app/scheduler.py` (sweeper).
- **DB impact:** Option A: `job_dispatch` outbox table
  (`id, job_id, created_at, published_at, attempts, last_error`). Option B: no
  new table; a `queued` sweeper with an idempotent task.
- **API impact:** create returns the job even if publish fails, with
  `dispatch_pending=true` (additive) or a 202; the current 500-after-commit is
  the bug.
- **Migration:** `0035_dispatch_outbox.py` for Option A; none for Option B.
- **Backward-compatibility risk:** old clients expect 201; keep 201 and add a
  field. Do not change the shape.
- **Rollback:** revert to direct dispatch; the outbox/sweeper can be disabled.
- **Tests:** broker down -> row exists, response is 201 with pending; sweeper
  publishes; duplicate publish is idempotent; batch partial failure does not
  orphan later jobs.

**Implementation notes:**

- Insert the outbox row in the same transaction as the job.
- A beat task every 30-60 s publishes unpublished rows with a bounded retry
  and backoff.
- `dispatch_job` should be idempotent by job id; the worker claim already
  makes a duplicate message harmless once fencing exists.

### 1.6 Retry semantics

- **Files:** `api/app/routers/jobs.py`, `api/app/routers/groups.py`,
  `worker/app/scheduler.py` (message), `web/app/jobs/[id]/page.tsx` (copy).
- **DB impact:** optional `retry_of` (integer, null) on `jobs`; no other
  change. `checkpoint` copy is a data decision, not a schema one.
- **API impact:** additive `retry_of`; response status unchanged.
- **Migration:** `0036_job_retry_lineage.py` if `retry_of` is added.
- **Backward-compatibility risk:** if retry starts resuming, the cost/time
  behavior changes; gate with a setting `RETRY_RESUMES_FROM_CHECKPOINT`
  (default off until tested).
- **Rollback:** flip the setting; keep `retry_of`.
- **Tests:** retry copies checkpoint when the setting is on; falls back to a
  fresh run when the artifact is missing; message matches behavior; group
  retry lineage.

**Implementation notes:**

- If resuming, verify the artifact path and `file_offset` still exist; if not,
  start fresh and record why.
- Copy `group_id` for a single-job retry (R-17).
- Group retry should preserve `created_by`/`rollup_of` lineage when the
  original had it (R-17) or explicitly set the retrying user with a
  `retry_of` link.

### 1.7 Terminal timestamps

- **Files:** `api/app/routers/jobs.py`, `api/app/routers/groups.py`.
- **DB impact:** none.
- **API impact:** canceled rows now have `finished_at`; additive.
- **Migration:** none.
- **Compatibility:** retention starts cleaning old queued-canceled rows; that
  is intended.
- **Rollback:** stop setting it; rows already set keep it.
- **Tests:** cancel queued -> `finished_at` set; cleanup selects it; group
  cancel sets it on every child.

## 5. Phase 2 - state-model standardization

### 2.1 Shared job-state module

- **Files:** new `api/app/job_state.py`, new `worker/app/job_state.py`,
  `api/app/schemas.py`, `api/app/routers/jobs.py`,
  `api/app/routers/customers.py`, `api/app/routers/groups.py`,
  `api/app/routers/reports.py`, `worker/app/db.py`,
  `worker/app/runner.py`, `worker/app/scheduler.py`.
- **DB impact:** none.
- **API impact:** none (same strings).
- **Migration:** none.
- **Compatibility:** pure refactor; behavior must not change.
- **Rollback:** revert imports.
- **Tests:** import the same constants; a contract test asserts API and worker
  sets match.

**Contents:**

```python
JobStatus, ACTIVE, TERMINAL, DOWNLOADABLE, TRANSITIONS, can_transition
```

Do not put FastAPI or SQLAlchemy imports in this module; it must be importable
by both sides and by tests.

### 2.2 Cross-language contract

- **Files:** new `contracts/job-state.json`, new
  `scripts/generate_job_state.py` (or a test), new `web/lib/job-state.ts`,
  `web/lib/api.ts`, `web/lib/use-jobs.ts`, `web/app/jobs/page.tsx`,
  `web/app/jobs/[id]/page.tsx`, `web/app/page.tsx`,
  `web/app/groups/[id]/page.tsx`.
- **DB impact:** none.
- **API impact:** none.
- **Migration:** none.
- **Compatibility:** the generated file must match the current strings exactly.
- **Rollback:** keep the generated file and revert consumers.
- **Tests:** CI regenerates and fails on diff; a test asserts the TypeScript
  union and Python Literal contain the same values.

### 2.3 Completeness fields

- **Files:** `api/app/models.py`, `worker/app/db.py`,
  `worker/app/runner.py`, `worker/app/rollup.py`, `api/app/schemas.py`,
  `api/app/routers/jobs.py`.
- **DB impact:** add `completion_state` varchar(16) not null default
  `'unknown'`, `gap_count` integer not null default 0, `gap_reason` text null.
- **API impact:** `JobOut` adds the three fields. Old clients ignore them.
- **Migration:** `0033_job_completion_state.py`. Backfill:
  - existing `completed` rows with `error_message` like `%batch(es) skipped%`
    -> `partial` (best-effort, documented);
  - rollups with skipped warn events are not detectable from the job row;
    leave `unknown` and document.
- **Backward-compatibility risk:** backfill can misclassify; default
  `unknown` is honest. Do not fail the migration on unparseable rows.
- **Rollback:** stop reading the fields; leave the columns.
- **Tests:**
  - normal run -> `complete`;
  - skipped batch -> `partial`, `gap_count=1`;
  - rollup missing store -> `partial`, `gap_count=N`;
  - preview -> `is_preview` and `completion_state` unchanged/`unknown`;
  - legacy row -> `unknown`.

### 2.4 Status check constraint

- **Files:** `api/app/models.py`, migration.
- **DB impact:** `CHECK (status IN ('queued','running','paused','completed','failed','canceled'))`.
- **API impact:** none.
- **Migration:** `0037_job_status_check.py`, after a distinct-value audit:
  `SELECT DISTINCT status FROM jobs`.
- **Backward-compatibility risk:** any legacy value fails the constraint. Run
  the audit first; map or fail explicitly.
- **Rollback:** drop the constraint.
- **Tests:** inserting an invalid status raises; a valid transition still
  commits.

### 2.5 Capability object (optional, recommended)

- **Files:** `api/app/schemas.py`, `api/app/routers/jobs.py`,
  `web/app/jobs/[id]/page.tsx`, `web/app/jobs/page.tsx`.
- **DB impact:** none.
- **API impact:** additive `capabilities: {can_pause, can_resume, can_cancel,
  can_retry, can_delete_files, can_retry_s3}`.
- **Migration:** none.
- **Compatibility:** old clients ignore it.
- **Rollback:** remove the field.
- **Tests:** capabilities match the transition table for every status.

## 6. Phase 3 - concurrency

### 3.1 Per-credential token refresh lock

- **Files:** `worker/app/runner.py`, `worker/app/last9/tokens.py`,
  new `worker/app/locks.py` (or a small helper), `api/app/routers/comparisons.py`.
- **DB impact:** none if Redis is used; optional `token_version` bigint on
  `last9_credentials` for CAS.
- **API impact:** none.
- **Migration:** optional `0038_credential_token_version.py`.
- **Backward-compatibility risk:** a lock outage must not stop refreshes. Fall
  back to the current behavior with a metric.
- **Rollback:** disable the lock via setting.
- **Tests:** two concurrent refreshes -> one rotation, the other reuses the
  token; CAS failure retries; Redis down -> fallback.

**Implementation notes:**

- `SET lock:credential:<id> <owner> NX EX 30`; release only if the value
  matches.
- Hold the lock across refresh + persist, not across the Last9 query.
- Prefer a DB `SELECT ... FOR UPDATE` if Redis is not acceptable; it is slower
  but simpler.

### 3.2 S3 attempt ownership

- **Files:** `worker/app/tasks.py`, `worker/app/runner.py`,
  `api/app/routers/jobs.py`, `api/app/schemas.py`.
- **DB impact:** optional `s3_uploading_at` timestamptz null,
  `s3_attempt_token` bigint default 0.
- **API impact:** additive `s3_state` derived helper (or `s3_state` field).
- **Migration:** `0039_s3_upload_attempt.py` (optional).
- **Backward-compatibility risk:** old retries do not set the marker; the
  endpoint still needs to accept them. Use a nullable marker with a stale
  timeout.
- **Rollback:** stop claiming; the marker is harmless.
- **Tests:** two retries -> one claims; stale marker is reclaimable; partial
  upload derives `s3_partial`; row clears the marker on success/failure.

### 3.3 Heartbeat independent of the row loop

- **Files:** `worker/app/runner.py`.
- **DB impact:** uses `heartbeat_at` from 1.1.
- **API impact:** none.
- **Migration:** none.
- **Compatibility:** none.
- **Rollback:** revert to event heartbeats.
- **Tests:** a simulated long blocking call still heartbeats; the reaper does
  not fail it.

**Implementation notes:** a small daemon thread or a `threading.Timer` that
writes `heartbeat_at` every 60-120 s while the run is active, stopped in a
`finally`. It must use the lease token and stop on a 0-row update.

### 3.4 Pause/resume fence

- **Files:** `api/app/routers/jobs.py`, `worker/app/runner.py`.
- **DB impact:** uses 1.1.
- **API impact:** pause may return `paused` plus a derived `pause_pending`
  flag; additive.
- **Migration:** none.
- **Compatibility:** resume now increments the lease token; an old worker's
  write is fenced. That is the fix.
- **Rollback:** revert resume's token increment.
- **Tests:** pause then immediate resume with a worker that has not observed
  the pause; only one writer survives.

## 7. Phase 4 - reporting consistency

### 4.1 Shared derivation helper

- **Files:** new `api/app/derived_state.py`,
  `api/app/routers/groups.py`, `api/app/routers/reports.py`,
  `api/app/routers/jobs.py`.
- **DB impact:** none.
- **API impact:** group/report values may change for edge cases; document.
- **Migration:** none.
- **Compatibility:** a group with 9 failed + 1 completed may switch from
  `partial` to `failed` (or vice versa) depending on the chosen precedence.
  Announce it.
- **Rollback:** restore the per-router functions.
- **Tests:** golden table for every combination of child statuses; property
  test that group and report agree on "failed dominates" if that is the chosen
  rule.

### 4.2 Report day key

- **Files:** `api/app/routers/reports.py`.
- **DB impact:** none if computed; optional `window_day` date column for
  performance.
- **API impact:** historical days move for backfilled runs.
- **Migration:** `0040_job_window_day.py` only if a column is added.
- **Backward-compatibility risk:** reports change; keep a feature flag
  `REPORT_BY_WINDOW_DAY` for one release.
- **Rollback:** flip the flag.
- **Tests:** a backfill created today for yesterday appears under yesterday;
  interval schedules still use `created_at`.

### 4.3 Partial propagation

- **Files:** `api/app/routers/groups.py`,
  `api/app/routers/reports.py`, `api/app/routers/jobs.py`,
  `web/app/jobs/page.tsx`, `web/app/jobs/[id]/page.tsx`.
- **DB impact:** uses 2.3.
- **API impact:** `GroupSummary` gains `partial` count; `ReportDayOut` gains
  `partial` count; additive.
- **Migration:** none.
- **Compatibility:** a day with a partial run may now show `partial` instead of
  `ok`. That is the intended fix.
- **Rollback:** keep the counts but revert the status precedence.
- **Tests:** skipped-batch job -> group partial -> report partial; rollup skip
  -> partial.

### 4.4 Schedule success signal

- **Files:** `api/app/routers/reports.py`,
  `api/app/routers/schedules.py`, `web/app/schedules/page.tsx`.
- **DB impact:** none if derived; optional `last_success_at` on schedules.
- **API impact:** add `last_success_at` (derived) and `last_dispatch_at`
  (alias of `last_run_at`); keep `last_run_at` for compatibility.
- **Migration:** `0041_schedule_last_success.py` only if persisted.
- **Compatibility:** labels change; values are additive.
- **Rollback:** remove the fields.
- **Tests:** dispatch failure leaves `last_dispatch_at` recent and
  `last_success_at` old; report `missed` uses the success signal.

### 4.5 Alert acknowledgement (optional)

- **Files:** `api/app/routers/reports.py`, `api/app/models.py` or
  `app_settings`, `web/app/reports/page.tsx`.
- **DB impact:** `report_alert_acks` table or a JSON blob.
- **API impact:** add `acknowledged_at/by` to alerts.
- **Migration:** `0042_report_alert_acks.py`.
- **Compatibility:** additive.
- **Rollback:** ignore the table.
- **Tests:** ack hides/marks an alert; a new failure reopens it.

## 8. Phase 5 - frontend consistency

### 5.1 Generated state mirror

Covered by 2.2; list the consumers explicitly:

- `web/lib/api.ts` (`JobStatus`, `JOB_TONE`)
- `web/lib/use-jobs.ts` (`ACTIVE_STATUSES`, `isActive`)
- `web/app/jobs/page.tsx` (`STATUS_TABS`)
- `web/app/jobs/[id]/page.tsx` (`TERMINAL`)
- `web/app/page.tsx` (`STATUS_COLOR`)
- `web/app/groups/[id]/page.tsx` (`GROUP_STATUS`, `JOB_STATUS`, `active`)

### 5.2 Preview promotion endpoint

- **Files:** `api/app/routers/jobs.py`, `api/app/schemas.py`,
  `web/app/jobs/[id]/page.tsx`.
- **DB impact:** optional `promoted_from` (integer, null) or reuse `retry_of`.
- **API impact:** new `POST /jobs/{id}/promote`; keep the client-side path as
  fallback.
- **Migration:** `0043_job_promotion_lineage.py` (optional).
- **Compatibility:** additive; old clients keep using `create_job`.
- **Rollback:** remove the route; the client path still works.
- **Tests:** promotion copies the full filter spec, `group_id`,
  `s3_profile_id`, exclusions; idempotency key prevents duplicates.

### 5.3 SSE event id / dedupe

- **Files:** `api/app/routers/jobs.py`,
  `web/app/jobs/[id]/page.tsx`.
- **DB impact:** none.
- **API impact:** include `id:` in the SSE frame or `event_id` in the JSON;
  honor `Last-Event-ID`.
- **Migration:** none.
- **Compatibility:** old clients ignore the extra field.
- **Rollback:** revert to event id 0; the client dedupe still works if kept.
- **Tests:** reconnect does not duplicate; terminal event closes once.

### 5.4 URL-backed workflow state (optional)

- **Files:** `web/app/jobs/new/page.tsx`,
  `web/app/groups/new/page.tsx`, `web/app/reports/page.tsx`.
- **DB impact:** none.
- **API impact:** none.
- **Migration:** none.
- **Compatibility:** none.
- **Rollback:** revert.
- **Tests:** back/forward restores step/selection; reload keeps the draft.

### 5.5 Capability-driven actions

- **Files:** `web/app/jobs/[id]/page.tsx`, `web/app/jobs/page.tsx`.
- **DB impact:** none.
- **API impact:** consumes 2.5.
- **Migration:** none.
- **Compatibility:** additive.
- **Rollback:** fall back to status checks.
- **Tests:** no action button appears for a terminal status; stale row 409
  shows the error.

## 9. Phase 6 - testing and regression protection

### 6.1 Transition matrix tests

- **Files:** `api/tests/test_job_transitions.py` (new),
  `worker/tests/test_runner_transitions.py` (new).
- **DB/API/migration:** none.
- **Tests:** every row in `STATE_TRANSITIONS.md` section 2 and 3; every
  forbidden transition returns 409 or 0 rows.

### 6.2 Concurrency integration tests

- **Files:** `api/tests/test_job_concurrency.py`,
  `worker/tests/test_claim_concurrency.py`.
- **Setup:** two SQLAlchemy sessions/connections against the test Postgres (or
  SQLite with `check_same_thread=False` for a coarse test). SQLite does not
  reproduce row-level locking faithfully; prefer a Postgres test container for
  the real assertions.
- **Tests:**
  - two claims;
  - reclaim + old write;
  - pause/resume;
  - cancel/complete;
  - reaper + late write;
  - two schedule scans;
  - two rollups;
  - two S3 retries;
  - two token refreshes.

### 6.3 Contract tests

- **Files:** `api/tests/test_state_contract.py`,
  `worker/tests/test_state_contract.py`, `web` script.
- **Tests:** Python/worker/TS vocabularies match; OpenAPI `JobOut` includes the
  new fields; generated file is current.

### 6.4 Property tests

- **Files:** `api/tests/test_job_properties.py` (Hypothesis optional; do not
  add a dependency just for this if a table-driven test is enough).
- **Properties:**
  - terminal is absorbing;
  - cancel dominance;
  - fence;
  - settle-once;
  - window uniqueness;
  - chunk replay idempotency.

### 6.5 Golden derivation tests

- **Files:** `api/tests/test_derived_state.py`.
- **Cases:** all child status combinations for group; all day combinations for
  report; partial/complete/unknown; preview excluded.

### 6.6 Outage/chaos tests

- **Files:** `api/tests/test_dispatch_outage.py`,
  `worker/tests/test_redis_outage.py`.
- **Cases:** broker down on create; Redis down on login throttle; Redis down
  on health; token refresh 503; S3 partial failure; disk full before start.

## 10. Migration inventory

These are proposals. None exist today.

| Migration | Purpose | Additive? | Risk | Rollback |
|---|---|---|---|---|
| `0032_job_lease_fencing.py` | owner, lease, heartbeat, cancel/pause request | Yes | Low; nullable/default | Leave columns |
| `0033_job_completion_state.py` | completeness + gap fields | Yes | Low; backfill best-effort | Leave columns |
| `0034_schedule_window_unique.py` | partial unique index | Index only | Medium; duplicates fail | Drop index |
| `0035_dispatch_outbox.py` | outbox for create->dispatch | Yes | Low | Drop table |
| `0036_job_retry_lineage.py` | `retry_of` | Yes | Low | Leave column |
| `0037_job_status_check.py` | CHECK constraint | Constraint | Medium; legacy values | Drop constraint |
| `0038_credential_token_version.py` | CAS for token rotation | Yes | Low | Leave column |
| `0039_s3_upload_attempt.py` | S3 attempt marker | Yes | Low | Leave column |
| `0040_job_window_day.py` | report day key (optional) | Yes | Low | Leave column |
| `0041_schedule_last_success.py` | success signal (optional) | Yes | Low | Leave column |
| `0042_report_alert_acks.py` | alert acknowledgement (optional) | Yes | Low | Drop table |
| `0043_job_promotion_lineage.py` | preview promotion link (optional) | Yes | Low | Leave column |

### 10.1 Pre-migration audits

```sql
-- duplicate schedule windows
SELECT created_by, start_epoch, count(*)
FROM jobs
WHERE created_by LIKE 'schedule:%'
GROUP BY created_by, start_epoch
HAVING count(*) > 1;

-- unexpected statuses
SELECT status, count(*) FROM jobs GROUP BY status;

-- legacy completion gaps
SELECT count(*) FROM jobs
WHERE status = 'completed' AND error_message LIKE '%batch(es) skipped%';
```

Do not run these in this task; they are for the migration plan.

## 11. Rollout order

### 11.1 Fencing (the most delicate)

1. Deploy migration `0032` (columns only).
2. Deploy the worker that acquires the lease and checks the token, but keep
   enforcement disabled. It writes `owner_id`/`lease_token`; the API ignores
   them.
3. Verify all workers are updated (capacity/admin view or a version metric).
4. Deploy the API that sets `cancel_requested_at` and, optionally, enforces
   token checks on its own writes. The API does not own job execution, so
   enforcement is mostly in the worker.
5. Enable `JOB_FENCING_ENFORCE=true` in the worker. Monitor
   `jobs_fenced_total`; a spike means a bug, not normal behavior.
6. Remove the feature flag after one release.

### 11.2 Completeness

1. Deploy migration `0033` (default `unknown`).
2. Deploy the worker that sets `completion_state` on new terminal writes.
3. Deploy the API/UI that reads it. Legacy rows stay `unknown` and render as
   "not recorded".
4. Backfill only the unambiguous `error_message` cases; leave rollups
   `unknown` unless event-based detection is added.

### 11.3 Schedule uniqueness

1. Run the duplicate audit.
2. Resolve duplicates (cancel/delete the extra job, or keep the oldest and
   document).
3. Create the unique index concurrently.
4. Deploy `ON CONFLICT DO NOTHING` insertion.
5. Add the failed-window policy test.

### 11.4 Vocabulary

1. Land the shared module and contract test with no behavior change.
2. Replace consumers one layer at a time: worker, API, web.
3. Only then add new states/fields.

## 12. Backward compatibility matrix

| Change | Old API | Old worker | Old web | Notes |
|---|---|---|---|---|
| New nullable columns | Fine | Fine (ignores) | Fine | Additive |
| `completion_state` field | Fine | Fine (does not set) | Fine (ignores) | Legacy `unknown` |
| Lease enforcement | Fine | **Breaks** if it cannot send a token | Fine | Worker first |
| Unique schedule index | Fine | Fine (conflict skip) | Fine | Clean duplicates |
| Retry resumes | Fine | Fine | Behavior change | Feature flag |
| Report day key | Fine | Fine | Numbers change | Announce |
| Preview promotion endpoint | Fine | Fine | Old path still works | Additive |
| Status CHECK | Fine | Fine | Fine | Audit first |
| SSE event id | Fine | Fine | Old ignores | Additive |
| Capability object | Fine | Fine | Old ignores | Additive |

## 13. Rollback strategy

| Change | Rollback | Data loss? |
|---|---|---|
| Lease columns | Disable enforcement; revert worker | No |
| Completion fields | Stop reading; leave columns | No |
| Unique index | Drop index; keep code path guarded by dialect | No |
| Outbox | Disable sweeper; direct dispatch | No |
| Retry resume flag | Flip flag to restart | No |
| Report day key | Flip flag | No (historical view changes) |
| Token lock | Disable lock setting | No |
| S3 attempt marker | Stop claiming; leave marker | No |
| Status CHECK | Drop constraint | No |
| Preview endpoint | Remove route; client fallback | No |

## 14. Top five highest-risk problems

1. **No worker fencing** (R-01, R-02, R-03, R-04). Cancel, pause/resume,
   reclaim, and rollup can produce two writers. This is the only class that can
   silently corrupt the artifact and still report success.
2. **`completed` cannot express completeness** (R-09, R-10). Skipped ID batches
   and skipped rollup sources are invisible to reports and groups.
3. **Schedule truth is split** (R-07, R-08, R-14). The cursor says "ran", the
   job row may say "failed", and a failed window is never retried.
4. **Retry contradicts recovery** (R-05, R-17). A reaped job re-extracts from
   zero and may leave its group, despite a message promising resume.
5. **Vocabulary and derivation are duplicated** (R-11, R-12). Every future
   state change is a multi-file change, and groups/reports already disagree.

## 15. Recommended implementation order

| Step | Work | Why |
|---|---|---|
| 1 | Phase 0 baseline + transition logging | Make the races observable before changing them. |
| 2 | 1.1 lease/fencing + 1.2 cancel dominance + 1.3 rollup | Closes the data-corruption class. |
| 3 | 1.4 schedule idempotency + 1.5 dispatch handoff | Stops duplicate/orphaned work at the source. |
| 4 | 1.6 retry semantics + 1.7 terminal timestamps | Aligns recovery behavior and cleanup. |
| 5 | 2.1 shared module + 2.2 contract + 2.3 completeness | Removes drift and makes partial data visible. |
| 6 | 3.1 token lock + 3.2 S3 attempt + 3.3 heartbeat | Remaining concurrency fixes. |
| 7 | 4.1-4.4 shared derivation + day key + partial + success signal | Reporting consistency. |
| 8 | 5.1-5.5 frontend mirror, promotion, SSE, URL state | UI consistency after the server is trustworthy. |
| 9 | 6.1-6.6 tests and chaos | Lock the behavior in. |
| 10 | 2.4 status CHECK, 4.5 alert acks, optional items | Hardening and polish. |

The order is deliberately **data integrity before reporting, reporting before
UI**. Changing a dashboard to show `partial` before the worker records it
would only move the inconsistency.

## 16. Deferred / not recommended now

| Item | Why defer |
|---|---|
| A state-machine library (XState, transitions, python-statemachine) | The transition table is small; a library adds a dependency and a second source of truth. |
| Persisting group/report status | They are derived by design; a column would create a new drift source. |
| A seventh `completed_with_gaps` status | Breaks the vocabulary; `completion_state` is orthogonal and additive. |
| Making comparisons asynchronous | Product change, not required for correctness. |
| A full event-sourcing rewrite | The current row + events model is sufficient; add fencing and completeness. |
| Rewriting the scheduler as cron | The owed-window logic works; the missing piece is idempotency. |
| Persisting notification delivery | Only if delivery guarantees become a requirement. |
| Server-side one-time OAuth nonce | Low risk for an internal tool; add if the threat model changes. |

## 17. Definition of done

A phase is done when:

- the transition table in `STATE_TRANSITIONS.md` is updated;
- the shared module/contract is updated;
- the migration is additive and reversible;
- the concurrency test exists and fails on the old code;
- the rollback is documented and exercised in staging;
- the API compatibility matrix is updated;
- the risk register status is updated (verified fix or accepted risk).

The most important acceptance criterion is not "the tests pass". It is:

> No worker write can change a row it no longer owns, and no `completed` row
> can hide a known gap.
