# Implicit State Machines: Validated Inventory

Audit date: 2026-11-14
Scope: `api/`, `worker/`, `web/`
Change type: documentation only. No application code, schema, migration, or
runtime configuration was modified.

This document is the validated inventory. The architecture derived from it lives
in the companion documents:

- [`JOB_LIFECYCLE.md`](./JOB_LIFECYCLE.md) - canonical lifecycle and the
  separation of execution, completeness, and artifact delivery.
- [`STATE_TRANSITIONS.md`](./STATE_TRANSITIONS.md) - central transition rules,
  guards, and the Python/TypeScript contract.
- [`STATE_DEPENDENCIES.md`](./STATE_DEPENDENCIES.md) - parent/child machines,
  shared fields, triggers, cycles, and blast radius.
- [`STATE_MACHINE_RISKS.md`](./STATE_MACHINE_RISKS.md) - risk register with
  severity, probability, business impact, and evidence.
- [`STATE_MACHINE_ROADMAP.md`](./STATE_MACHINE_ROADMAP.md) - phased
  implementation plan, migrations, compatibility, rollback, and tests.

## Legend

| Tag | Meaning |
|---|---|
| **[V]** | Verified in source at the cited location on the audit date. |
| **[R]** | Architectural recommendation. Not current behavior. |
| **[A]** | Assumption or estimate that needs runtime confirmation. Probability and impact ratings are estimates. |
| **[L]** | Latent or defensive behavior: present in code but not shown to be reachable through a normal user path. |

Line numbers are from the audit date and will drift. Function and route names
are the stable references.

## 0. Executive summary

The original audit identified **34** machines: 22 server/domain and 12 client.
Validation confirmed all 34 and added **6** implicit machines that the original
inventory had folded into other rows or missed entirely:

1. **Create -> dispatch handoff** (`commit` then publish to the broker).
2. **Celery delivery / acknowledgement / redelivery**.
3. **Rollup execution subtype** (a job that bypasses the normal claim path).
4. **Schedule window idempotency** (check-then-insert with no unique key).
5. **S3 upload attempt ownership** (retry has no lock or pending state).
6. **Preview -> full promotion / clone fidelity** (a new job is built in the
   browser, not promoted on the server).

The count is therefore **40** machines: the original **22 server/domain** and
**12 client-only**, plus **6 added**. Of the added machines, 35 (create ->
dispatch) and 36 (Celery delivery) are cross-boundary, 37-39 (rollup subtype,
schedule window idempotency, S3 attempt ownership) are server/worker subtypes,
and 40 (preview promotion) starts in the client and ends in the job lifecycle.
The classification is less important than the dependency map; several machines
are two views of the same row.

The central finding is unchanged and now better evidenced:

> There is no single source of truth for job state. The vocabulary is repeated
> in at least 14 places, the worker can write terminal states unconditionally,
> and three different layers derive "success" from a terminal string that
> cannot express incompleteness.

## 1. Method

Every machine was checked against:

- the route or task that owns the transition;
- the SQL/ORM predicate that guards it;
- the column(s) that persist it;
- the consumer that derives another state from it;
- the failure path (exception, process death, broker redelivery, Redis loss);
- the existing test that covers it, if any.

A behavior is tagged **[V]** only when the code path is present. A race is
tagged **[V]** when the unsafe write is unconditional or the guard is absent;
whether the race is observed in production is **[A]**.

The audit did **not** run the application, replay production data, or inspect a
live Postgres/Celery/Redis deployment. Claims about concurrency therefore
describe code structure, not measured incident rates.

## 2. Machine index

| # | Machine | Kind | Persisted state | Canonical owner |
|---|---|---|---|---|
| 1 | Job lifecycle | server | `jobs.status` + timestamps | jobs router, runner |
| 2 | Worker claim / lease | server | `jobs.status`, `job_events.ts` | `worker/app/db.py` |
| 3 | Checkpoint / resume | server | `jobs.checkpoint`, offsets, chunks | runner, `last9/extract.py` |
| 4 | Completion coverage / gaps | server | `error_message`, checkpoint, counters | runner |
| 5 | Stale-job reaper | server | `jobs.status`, `job_events.ts` | scheduler |
| 6 | S3 delivery | server | `s3_*` columns | runner, jobs router, tasks |
| 7 | Schedule run obligation | server | `schedules.enabled`, `last_run_at` | scheduler, schedules router |
| 8 | Job ownership / kind tags | server | `created_by`, `rollup_of`, `is_preview`, `group_id` | creators |
| 9 | Group status / retry lineage | server | `extraction_groups.parent_group_id` | groups router |
| 10 | Report day / alert | server | derived from jobs + schedules | reports router |
| 11 | Comparison run | server | `comparison_runs.status` | comparisons router |
| 12 | Last9 token lifecycle | server | credential token columns | token manager, OAuth |
| 13 | Login throttle | server | Redis key | auth router |
| 14 | OAuth handshake | server | signed state + cookie | auth router |
| 15 | Health breach / recovery | server | Redis latches | health monitor |
| 16 | Notification delivery | server | none (in-memory retry) | notifications |
| 17 | Worker capacity | server | env + live pool | admin, tasks client |
| 18 | Retention / artifact expiry | server | artifact paths | scheduler |
| 19 | Index cache | server | Redis key (15 min) | indexes router |
| 20 | Beat / readiness | server | Redis beat key | scheduler, health router |
| 21 | Auth session | server/client | `lv_token` (24 h JWT) | api client |
| 22 | Parse mode | server/client | aggregation booleans | job create, aggregator |
| 23 | New-extraction wizard | client | React state | `jobs/new` |
| 24 | Save-as-search conflict | client | React + mutation state | `jobs/new` |
| 25 | Auto-detect panel | client | React + mutation state | `auto-detect-panel` |
| 26 | Jobs list filters / selection | client | URL + React | `jobs/page` |
| 27 | Job live feed | client | React + `EventSource` | `jobs/[id]` |
| 28 | Job actions / confirmations | client | mutation + confirm state | `jobs/[id]` |
| 29 | Templates batch / editor | client | React | `templates/page` |
| 30 | Schedule forms | client | React | `schedules/page` |
| 31 | Groups create / detail | client | React + derived group status | `groups/*` |
| 32 | Reports view | client | URL + React | `reports/page` |
| 33 | Command palette | client | React | `command-palette` |
| 34 | Login form | client | React | `login/page` |
| 35 | Create -> dispatch handoff | cross-boundary | `jobs.status` + broker | jobs/groups routers |
| 36 | Celery delivery / ack / redelivery | cross-boundary | broker + `redelivered` | Celery config, tasks |
| 37 | Rollup execution subtype | server | `jobs.rollup_of` + status | `worker/app/rollup.py` |
| 38 | Schedule window idempotency | server | `jobs(created_by, start_epoch)` | scheduler |
| 39 | S3 upload attempt ownership | server | `s3_*` + no lock | jobs router, tasks |
| 40 | Preview -> full promotion | client/server | none (new job) | `jobs/[id]` |

## 3. Server and domain machines

### 1. Job lifecycle

- **States.** `queued`, `running`, `paused`, `completed`, `failed`, `canceled`
  **[V]** (`api/app/schemas.py:199`, `web/lib/api.ts:217`).
  Derived views: `active` (`queued|running|paused`), `terminal`
  (`completed|failed|canceled`), `downloadable`
  (`completed|failed|canceled|paused`).
- **Valid transitions.**
  - create/import/batch/group/schedule/rollup -> `queued` **[V]**.
  - `queued` -> `running`: conditional claim **[V]** (`worker/app/db.py:193-230`).
  - `queued` or `running` -> `paused`: pause route **[V]** (`jobs.py:829-837`).
  - `paused` -> `queued`: resume route, then dispatch **[V]** (`jobs.py:840-849`).
  - any non-terminal -> `canceled`: cancel and bulk cancel **[V]**
    (`jobs.py:852-865`, `926-950`).
  - `running` -> `completed`: runner final write **[V]** (`runner.py:830-895`).
  - `running` -> `failed`: runner exception path **[V]** (`runner.py:703-722`).
  - `running` -> `failed`: reaper **[V]** (`scheduler.py:192-249`).
  - `failed|canceled` -> **new** `queued` job: retry, not an in-place transition
    **[V]** (`jobs.py:953-1003`).
  - `queued` -> `running` -> `completed|failed`: rollup subtype **[V]**
    (`rollup.py:85`, `228-241`).
- **Invalid or missing.**
  - Pause a terminal job -> 409 **[V]**. Resume a non-paused job -> 409 **[V]**.
    Retry a non-terminal job -> 409 **[V]**.
  - No `canceling` / `cancel_requested` state. The API writes `canceled`
    immediately and the worker may still be writing **[V]**.
  - No state for "lease lost" or "fenced". The old worker has no way to know
    that a reclaim happened **[V]**.
  - No distinct `completed_with_gaps`. Incompleteness is `completed` plus
    `error_message` **[V]** (`runner.py:860-872`).
  - No DB check constraint on `jobs.status`; any string can be written **[V]**
    (`models.py:44-97`; migrations 0001-0031 add no check).
- **Triggers.** HTTP create/pause/resume/cancel/retry/bulk-cancel; Celery
  `logvault.run_job`; scheduler scan; reaper; rollup dispatch.
- **DB fields.** `status`, `started_at`, `finished_at`, `error_message`,
  `rows_written`, `total_chunks`, `completed_chunks`, `current_chunk_start`,
  `checkpoint`, artifact paths, `s3_*`, `created_at`, `updated_at`,
  `created_by`, `is_preview`, `rollup_of`, `group_id`.
- **Responsible code.** `api/app/routers/jobs.py`, `api/app/routers/groups.py`,
  `worker/app/runner.py`, `worker/app/db.py`, `worker/app/tasks.py`,
  `worker/app/scheduler.py`, `worker/app/rollup.py`.
- **External dependencies.** Postgres, Celery broker, Last9 API, local
  filesystem, S3, SMTP/Slack (failure alerts).
- **Recovery / retry.** `queued` survives an API restart and still runs when a
  worker picks it up. `running` with no recent event is failed by the reaper.
  `paused` is resumed from the checkpoint on the same row. `failed`/`canceled`
  retry creates a new row and **does not copy the checkpoint** **[V]**
  (`jobs.py:975-996`), so it re-extracts the whole window despite the reaper
  message saying "Retry to resume from the last checkpoint"
  **[V]** (`scheduler.py:211-214`).
- **Validation notes.**
  - **Cancel/complete race [V, structural].** Cancel sets `status="canceled"`
    with an ORM write and no token **[V]** (`jobs.py:858-866`). The runner
    finalizes with an unconditional `status="completed"` **[V]**
    (`runner.py:830-831`). If the final write lands after the cancel, the job
    reappears as completed. The same applies to group cancel
    **[V]** (`groups.py:236-240`).
  - **Pause/resume race [V, structural].** Pause writes `paused`; resume writes
    `queued` and dispatches **[V]** (`jobs.py:834-848`). A worker that has not
    yet observed the pause checks the row, sees `queued`, and keeps writing.
    The new worker claims `queued` and also writes. The conditional claim only
    stops a second claim while the row still says `running`; it does not fence
    the old worker after a resume.
  - **Canceled queued job has no `finished_at` [V].** `cancel_job` never sets
    it (`jobs.py:858-866`), and the reaper only looks at `running`. Retention
    selects `finished_at IS NOT NULL` (`scheduler.py:271-283`), so these rows
    are never cleaned up.
  - `updated_at` is an ORM `onupdate` column, but the worker writes via
    SQLAlchemy Core, so it does not move during a run **[V]**
    (`models.py:93-95`; `scheduler.py:202-204`).
  - `started_at` is overwritten on reclaim **[V]** (`runner.py:229-234`).
  - The status vocabulary is repeated in at least 14 places (section 6).

### 2. Worker claim / lease

- **States.** `queued` (unclaimed), `running` (owned), `running` (quiet and
  reclaimable), `fenced` (recommended, does not exist).
- **Valid transitions.**
  - `queued` -> `running` when the conditional `UPDATE` matches **[V]**
    (`db.py:210-230`).
  - `running` -> `running` when Celery reports redelivery **and** the last
    event is older than `stale_reclaim_minutes` (10 min default) **[V]**
    (`tasks.py:156-174`, `runner.py:225-235`, `db.py:211-222`).
- **Invalid or missing.**
  - Claiming a terminal job is rejected by the `WHERE` predicate **[V]**.
  - Claiming a live `running` job without redelivery is rejected **[V]**.
  - There is no owner id, lease epoch, or fencing token **[V]**. Every write
    after the claim is `WHERE id = :job_id` only.
  - A reclaimed job's old worker can continue writing if it is alive
    **[V, structural]**.
- **Triggers.** Celery task delivery; `current_task.request.redelivered`;
  `claim_job`.
- **DB fields.** `status`, `started_at`, `error_message` (cleared on claim),
  `job_events.ts` (liveness), `checkpoint` (resume).
- **Responsible code.** `worker/app/db.py:193-230`,
  `worker/app/runner.py:201-244`, `worker/app/tasks.py:139-177`.
- **External dependencies.** Celery `task_acks_late=True`,
  `task_reject_on_worker_lost=True`, `worker_prefetch_multiplier=1`
  **[V]** (`worker/app/celery_app.py:20-31`).
- **Recovery / retry.** Redelivery reclaims a quiet row; the reaper fails it
  after 60 quiet minutes; a manual retry creates a new row. There is no
  automatic retry from the reaper.
- **Validation notes.** The reclaim cutoff (10 min) is deliberately above the
  5-minute heartbeat (`config.py:56-60`). The heartbeat is emitted only from
  the row loop (`runner.py:653-664`); a long blocking HTTP retry or a large
  aggregation flush can exceed 10 minutes without an event, which is the
  window in which a redelivered task could reclaim a live worker **[A]**.

### 3. Checkpoint / resume

- **States.** no checkpoint; mid-range; end-of-range; resumed.
- **Valid transitions.**
  - chunk complete -> checkpoint advanced with `completed_chunks`,
    `next_chunk_start`, `file_offset`, `unmatched_offset`, `chunk_hours`
    **[V]** (`runner.py:571-627`, `last9/checkpoint.py:45-58`).
  - pause/cancel -> loop raises `_Stopped`; state is persisted at the last
    chunk boundary **[V]** (`runner.py:631-633`, `667-702`).
  - resume -> seek to `next_chunk_start`, truncate the CSV to `file_offset`,
    replay the partial chunk **[V]** (`runner.py:403-410`, `extract.py:93-100`).
- **Invalid or missing.**
  - Resume is only available on the same job row (pause/resume or reclaim).
    A retry creates a new row without `checkpoint`, so it starts over **[V]**.
  - The checkpoint records no attempt id, so it cannot tell which worker wrote
    it. With no fencing, a late write from an old worker can move the
    checkpoint backwards **[A]**.
- **Triggers.** `on_chunk_complete`; pause/cancel status poll every 10 s;
  reclaim.
- **DB fields.** `checkpoint` JSON (`completed_chunks`, `rows_written`,
  `current_chunk_start`, `next_chunk_start`, `skipped_batches`), `file_offset`,
  `unmatched_offset`, `chunk_hours`, plus mirrored `completed_chunks`,
  `total_chunks`, `rows_written`, `current_chunk_start`.
- **Responsible code.** `worker/app/runner.py`,
  `worker/app/last9/extract.py`, `worker/app/last9/checkpoint.py`.
- **External dependencies.** Local filesystem (CSV/JSONL and distinct store),
  Last9 API.
- **Recovery / retry.** Chunk-granular and idempotent for the CSV because the
  window is non-overlapping. Aggregation occurrence counts use the chunk index
  as an idempotency key **[V]** (`runner.py:614-623`). The distinct store is
  reset only when not resuming **[V]** (`runner.py:286-292`).
- **Validation notes.** Adaptive sizing is 0.25 h to 4 h **[V]**
  (`runner.py:568-589`). `total_chunks` is re-estimated at each boundary
  **[V]** (`runner.py:591-600`). The checkpoint is written in the same
  transaction as the job counters and the chunk event **[V]**
  (`runner.py:626-630`).

### 4. Completion coverage / gaps

- **States.** fully covered; completed with skipped ID batches; preview
  (intentionally capped); rollup with skipped source runs.
- **Valid transitions.**
  - normal full run -> `completed`, `total_chunks = completed_chunks`
    **[V]** (`runner.py:856-858`).
  - skipped ID batches -> `completed` + `error_message` describing the gap
    **[V]** (`runner.py:860-872`).
  - rollup with unusable sources -> `completed` + warn event; no
    `error_message` **[V]** (`rollup.py:212-241`).
  - BigQuery rows that match no pattern -> `completed` + message only
    **[V]** (`runner.py:873-874`).
- **Invalid or missing.**
  - No persisted completeness flag. Consumers must parse `error_message` or
    inspect the checkpoint, and neither is part of `JobOut` in a structured
    form **[V]**.
  - The code computes `covered` but only uses it to pin the progress
    denominator; it does not mark an uncovered run as partial **[V]**
    (`runner.py:856-858`). No normal non-preview exit path was found that
    reaches `completed` without coverage, so "uncovered but completed" is
    **[L]**, not a confirmed defect.
  - Rollup skipped sources are not reflected in `error_message`, group status,
    or report day status **[V]**.
- **Triggers.** End of extraction loop; `skipped_batches`; rollup source scan;
  BigQuery loader result.
- **DB fields.** `status`, `error_message`, `checkpoint.skipped_batches`,
  `total_chunks`, `completed_chunks`, `rows_written`,
  `aggregation_result.rows_unmatched`, `rollup_of`.
- **Responsible code.** `worker/app/runner.py`, `worker/app/rollup.py`,
  `worker/app/last9/extract.py`.
- **External dependencies.** Last9 HTTP 400 behavior; retention (source stores
  may be gone); BigQuery.
- **Recovery / retry.** A retry re-extracts the whole window and does not
  preserve `skipped_batches`. There is no "retry gaps only" path.
- **Validation notes.** `completed` is overloaded: clean, skipped batches,
  rollup with missing sources, preview, and unmatched rows all share it. This
  is the highest-impact semantic gap in the model.

### 5. Stale-job reaper

- **States.** `running` (live), `running` (stale), `failed`.
- **Valid transitions.** `running` -> `failed` when the newest `job_events.ts`
  (fallback `started_at`) is older than `stale_job_minutes` (60) **[V]**
  (`scheduler.py:216-248`).
- **Invalid or missing.**
  - A `running` job with no timestamps at all is left alone **[V]**
    (`scheduler.py:233-237`).
  - The reaper has no lease token. It can fail a job that is alive but silent
    during a long blocking call **[A]**.
  - It does not mark the job for automatic retry; it only fails it.
- **Triggers.** Celery beat every 300 s **[V]** (`celery_app.py:33-37`).
- **DB fields.** `status`, `started_at`, `job_events.ts`, `error_message`,
  `finished_at`.
- **Responsible code.** `worker/app/scheduler.py:192-249`.
- **External dependencies.** Postgres; notification channels.
- **Recovery / retry.** Manual retry only. The message tells the operator to
  retry, but retry starts over (see machine 1).
- **Validation notes.** The heartbeat (300 s) is below the reaper threshold
  (3600 s) by design. The reaper uses events, not `updated_at`, because Core
  writes bypass the ORM `onupdate` **[V]**.

### 6. S3 delivery

- **States.** not configured; pending; uploaded (any artifacts); partially
  uploaded; failed.
- **Valid transitions.**
  - job completes with `s3_profile_id` -> upload before the row is marked
    completed **[V]** (`runner.py:795-839`).
  - success -> `s3_uri` / `s3_summary_uri` / `s3_counts_uri`,
    `s3_uploaded_at`, `s3_error=None` **[V]**.
  - per-artifact failure -> `s3_error` joined from the failing artifacts; the
    job still completes **[V]** (`runner.py:813-839`, `s3.py:127-179`).
  - retry endpoint -> `dispatch_s3_upload` for a completed, non-preview job
    **[V]** (`jobs.py:488-507`).
- **Invalid or missing.**
  - No explicit `s3_state` and no upload lock. Multiple retries can run
    concurrently **[V, structural]**.
  - A later retry overwrites `s3_error` and `s3_uploaded_at` for the whole job,
    even though artifacts upload independently **[V]** (`tasks.py:214-223`).
  - A partial upload (raw succeeds, summary fails) is represented as
    `s3_error` plus a raw URI; the UI badge says "upload failed" if any error
    is present, hiding the successful artifact **[V]**
    (`jobs/[id]/page.tsx:552-554`).
- **Triggers.** End of run; `POST /jobs/{id}/s3-upload`; Celery
  `logvault.upload_job_s3`.
- **DB fields.** `s3_profile_id`, `s3_destination`, `s3_uri`,
  `s3_summary_uri`, `s3_counts_uri`, `s3_error`, `s3_uploaded_at`.
- **Responsible code.** `worker/app/runner.py`, `worker/app/s3.py`,
  `worker/app/tasks.py`, `api/app/routers/jobs.py`.
- **External dependencies.** S3/S3-compatible endpoint, boto3 credential chain,
  encrypted profile keys.
- **Recovery / retry.** Retry re-uploads from local files. If retention or
  manual deletion removed them, the retry fails with "file disappeared before
  upload" **[V]** (`s3.py:154-156`).
- **Validation notes.** The S3 copy is additive; local files remain. The job
  is `completed` regardless of S3 outcome, which is intentional but means
  "completed" does not imply delivered.

### 7. Schedule run obligation / backfill

- **States.** disabled; enabled and up to date; enabled with owed windows;
  backfilling; dispatched-but-not-run.
- **Valid transitions.**
  - disabled <-> enabled: toggle **[V]** (`schedules.py:287-293`).
  - owed window -> insert `queued` job(s), then update `last_run_at=now`
    **[V]** (`scheduler.py:140-177`).
  - calendar-day schedule -> one window per completed UTC day since
    `last_run_at`, capped at 14 **[V]** (`scheduler.py:61-91`).
  - interval schedule -> at most one rolling window **[V]**.
- **Invalid or missing.**
  - `last_run_at` is advanced before dispatch and regardless of whether the
    jobs run **[V]** (`scheduler.py:175-188`).
  - `_already_extracted` does not filter on status. A failed or canceled job
    for that window permanently blocks an automatic re-run **[V]**
    (`scheduler.py:94-108`, `141-142`).
  - No `last_success_at`, `last_dispatch_at`, or per-window run row.
  - No unique constraint on `(created_by, start_epoch)` **[V]**
    (`models.py:44-97`; migrations 0001-0031).
  - A dispatch failure leaves the job `queued` and records no event
    **[V]** (`scheduler.py:178-187`).
- **Triggers.** Celery beat every 60 s; schedule create/update/toggle/delete.
- **DB fields.** `schedules.enabled`, `last_run_at`, `calendar_day`,
  `interval_seconds`, `lookback_seconds`, `filter_spec`, `credential_id`,
  `index_target_id`, `s3_profile_id`; `jobs.created_by="schedule:<id>"`,
  `jobs.start_epoch`, `jobs.status`.
- **Responsible code.** `worker/app/scheduler.py`,
  `api/app/routers/schedules.py`.
- **External dependencies.** Postgres, Celery broker, Last9.
- **Recovery / retry.** Backfill up to 14 days; missed days are inserted as
  jobs with a warn event. A failed day is not retried automatically.
- **Validation notes.** The model comment says the calendar day is IST
  **[V]** (`models.py:133-135`), but the scheduler explicitly uses UTC
  **[V]** (`scheduler.py:81-87`). That is documentation drift, not a runtime
  bug in the current code. `last_run_at` is a dispatch cursor, not a success
  signal.

### 8. Job ownership / kind tags

- **States.** manual; `schedule:<id>`; `rollup:<id>`; preview; full; plain;
  rollup; grouped; ungrouped.
- **Valid transitions.** Set at creation; copied by retry; read by reports,
  alerts, rollup, and the group detail.
- **Invalid or missing.**
  - Single-job retry copies `created_by` and `rollup_of` but **not**
    `group_id` **[V]** (`jobs.py:975-996`). The retried job leaves its group.
  - Group retry sets `created_by=user.email` and drops `rollup_of`
    **[V]** (`groups.py:308-325`). A retried scheduled/rollup clone loses its
    schedule/rollup lineage.
  - Preview -> full creates a new job without `group_id` or `s3_profile_id`
    **[V]** (`jobs/[id]/page.tsx:93-113`).
- **Triggers.** Create, batch, group, schedule scan, retry, rollup, preview
  promotion.
- **DB fields.** `created_by`, `rollup_of`, `is_preview`, `group_id`.
- **Responsible code.** `jobs.py`, `groups.py`, `scheduler.py`, `rollup.py`,
  `jobs/[id]/page.tsx`.
- **External dependencies.** None beyond Postgres.
- **Recovery / retry.** Ownership tags are copied on retry except for the gaps
  above.
- **Validation notes.** `created_by` is a free string with prefixes, not a FK
  or enum. Parsing is duplicated in reports, alerts, and BigQuery loading.

### 9. Group status / retry lineage

- **States.** `queued`, `running`, `completed`, `partial`, `failed`,
  `canceled`; parent/child group lineage.
- **Valid transitions (derived, not persisted).**
  - any child `running|paused` -> group `running` **[V]** (`groups.py:38-50`).
  - else any child `queued` -> `queued`.
  - else all children `failed` -> `failed`.
  - else all children `canceled` -> `canceled`.
  - else any `failed|canceled` -> `partial`.
  - else -> `completed`.
- **Invalid or missing.**
  - Empty group -> `completed` **[V, L]** (`groups.py:44-50`). Group creation
    requires at least one item and creates jobs in the same transaction, so
    this is latent unless rows are manipulated.
  - A group with 9 failed and 1 completed is `partial`, while a report day
    with any failed job is `failed` **[V]**. The precedence differs.
  - `paused` is counted as `running` **[V]** (`groups.py:40`, `68`).
  - Cancel writes `canceled` but does not set `finished_at` and does not wait
    for the worker **[V]** (`groups.py:236-240`).
  - Retry clones only failed/canceled children into a new group with
    `parent_group_id` **[V]** (`groups.py:255-357`).
- **Triggers.** Group create, cancel, retry; any child status change.
- **DB fields.** `extraction_groups.*`, `jobs.group_id`,
  `extraction_groups.parent_group_id`.
- **Responsible code.** `api/app/routers/groups.py`.
- **External dependencies.** Postgres.
- **Recovery / retry.** Retry creates a child group; the original stays
  intact. There is no "retry in place".
- **Validation notes.** Group status is derived on every read; no column can
  drift. The drift is in the derivation rule, not the storage.

### 10. Report day / alert

- **States.** `ok`, `failed`, `running`, `canceled`, `partial`, `missed`,
  `pending`, `off`, `none` **[V]** (`schemas.py:870-872`).
- **Valid transitions (derived per schedule/day).**
  - no jobs + no schedule -> `none`; disabled -> `off`; enabled daily and past
    day -> `missed`; enabled daily and today -> `pending` **[V]**
    (`reports.py:100-125`).
  - any failed -> `failed`; else any active -> `running`; else canceled +
    completed -> `partial`; else only canceled -> `canceled`; else `ok`
    **[V]**.
- **Invalid or missing.**
  - Day is keyed by `created_at`, while a calendar-day schedule's window is the
    previous UTC day. A backfilled yesterday run is reported under today
    **[V]** (`reports.py:161-165`, `scheduler.py:83-90`).
  - Row counts include only `completed` rows **[V]** (`reports.py:90-91`).
  - A day with one failed and many completed is `failed`, but counts still
    show only the completed rows **[V]**.
  - `missed` uses a 36-hour heuristic and `created_at`, not the schedule's
    cadence or `last_success_at` **[V]** (`reports.py:54-55`, `423-452`).
  - `last_run_at` in the report prefers the latest job's `created_at` over
    `schedule.last_run_at` **[V]** (`reports.py:205`).
- **Triggers.** `GET /reports`; `GET /reports/settings`; schedule removal.
- **DB fields.** `jobs.created_by`, `created_at`, `status`, `rows_written`,
  `error_message`, `filter_spec.customer`, `filter_spec.label`;
  `schedules.*`; `app_settings["reports"]`.
- **Responsible code.** `api/app/routers/reports.py`.
- **External dependencies.** Postgres.
- **Recovery / retry.** The report is read-only; retry is a scheduler/manual
  job action.
- **Validation notes.** The report is the layer where derived statuses diverge
  most from the job list. It is defensible for an operator view, but it must be
  documented and ideally shared with groups.

### 11. Comparison run

- **States.** `ok`, `partial`, `failed` **[V]** (`comparisons.py:756-762`).
- **Valid transitions.** One synchronous request computes both sides, then
  inserts a single `ComparisonRun` row **[V]** (`comparisons.py:505-812`).
  Both sides ok -> `ok`; one -> `partial`; neither -> `failed`.
- **Invalid or missing.**
  - No persisted `running`. A crash mid-request leaves no row **[V]**.
  - No retry state or attempt count.
  - The refresh lock is a `threading.Lock` local to one request
    **[V]** (`comparisons.py:581-598`); it does not coordinate across API
    processes.
- **Triggers.** `POST /comparisons/{id}/run`.
- **DB fields.** `comparison_runs.status`, `last9_ok`, `newrelic_ok`,
  `*_error`, `*_total`, `*_series`, `*_raw`, `*_elapsed_ms`, `created_at`.
- **Responsible code.** `api/app/routers/comparisons.py`.
- **External dependencies.** Last9 API, New Relic NerdGraph, token refresh.
- **Recovery / retry.** Re-submit the request. There is no stored attempt to
  resume.
- **Validation notes.** Synchronous execution is a deliberate product choice;
  the missing `running` row is a crash-observability gap, not a correctness
  bug for successful requests.

### 12. Last9 token lifecycle

- **States.** `unknown`, `valid`, `expiring`, `expired` for display
  **[V]** (`last9_oauth.py:44-52`); worker-internal: fresh, within 5 min of
  expiry, refreshing, refresh-failed.
- **Valid transitions.**
  - missing or within 300 s of expiry -> refresh **[V]**
    (`last9/tokens.py:21-22`, `66-71`).
  - 401 or expired-body -> force refresh, up to 2 attempts in the client
    **[V]** (client retry logic).
  - refresh success -> persist access token, expiry, and rotated refresh token
    via `on_rotate` **[V]** (`runner.py:369-380`).
  - refresh 5xx/429 -> exponential backoff, up to 5 attempts; other 4xx ->
    `AuthExpiredError` **[V]** (`tokens.py:73-118`).
- **Invalid or missing.**
  - No cross-worker lock around refresh + persist **[V]**. Two jobs using one
    credential can rotate the refresh token concurrently; the last writer
    wins, and the other job's rotated token is lost.
  - The API display uses a 1-hour "expiring" window
    **[V]** (`last9_oauth.py:20`), while the worker refreshes at 5 minutes
    **[V]** (`tokens.py:21-22`). These are different thresholds for different
    purposes, but the names invite confusion.
- **Triggers.** `get_access_token`; HTTP 401; credential test-connection.
- **DB fields.** `last9_credentials.encrypted_access_token`,
  `access_token_expires_at`, `encrypted_refresh_token`,
  `refresh_token_last4`.
- **Responsible code.** `worker/app/last9/tokens.py`,
  `worker/app/last9/client.py`, `api/app/last9_oauth.py`,
  `api/app/routers/credentials.py`.
- **External dependencies.** Last9 OAuth endpoint, encryption key.
- **Recovery / retry.** Transient refresh failures retry; a hard 4xx fails the
  job. A rotated token loss requires re-authorization.
- **Validation notes.** The comparison endpoint serializes refresh within one
  request with a thread lock; worker jobs do not share it **[V]**.

### 13. Login throttle

- **States.** under limit; locked.
- **Valid transitions.** 401 -> `INCR` key; first failure sets a fixed TTL;
  success -> `DEL`; `>= max_attempts` -> 429 **[V]**
  (`auth.py:72-137`).
- **Invalid or missing.**
  - Fail-open when Redis is unreachable **[V]** (`auth.py:72-82`).
  - Keyed by email only, no IP dimension **[V]** (`auth.py:68-69`, `118-120`).
  - Fixed window from first failure; later attempts do not extend it
    **[V]** (`auth.py:85-93`).
- **Triggers.** `POST /auth/login`.
- **DB fields.** Redis `login:fail:<email>`; users table for verification.
- **Responsible code.** `api/app/routers/auth.py`.
- **External dependencies.** Redis, password hash.
- **Recovery / retry.** Lock expires after 15 minutes by default
  (`login_lockout_seconds=900`).
- **Validation notes.** Fail-open is documented as deliberate for an internal
  tool **[V]**. Treat as an accepted trade-off unless the threat model changes.

### 14. OAuth handshake

- **States.** initiated; callback; success; failed (`disabled`, `denied`,
  `domain`, `invalid_state`, `oauth_failed`) **[V]**
  (`auth.py:191-194`, `365-378`).
- **Valid transitions.**
  - `/google/login` mints a signed JWT state with a 600 s TTL and sets an
    HttpOnly cookie **[V]** (`auth.py:161-162`, `198-212`).
  - callback verifies the state and cookie, exchanges the code, validates the
    ID token, checks the domain, provisions the user, deletes the cookie
    **[V]** (`auth.py:365-386`).
- **Invalid or missing.**
  - State is a signed JWT plus cookie, not a server-side one-time nonce store.
    A replay within 600 s with the same cookie is possible in principle
    **[V, A]**.
  - Failure redirects carry a code, not a persisted attempt row.
- **Triggers.** `/auth/google/login`, `/auth/google/callback`.
- **DB fields.** `users.email`, `oauth_subject`, `auth_provider`, `role`.
- **Responsible code.** `api/app/routers/auth.py`.
- **External dependencies.** Google OAuth, tokeninfo endpoint, `JWT_SECRET`.
- **Recovery / retry.** Re-initiate the flow. The 600 s state TTL bounds the
  window.
- **Validation notes.** The callback verifies `aud`, `iss`, `email_verified`,
  `exp`, and the optional hosted domain **[V]** (`auth.py:299-321`).

### 15. Health breach / recovery

- **States.** below threshold; breached; cooldown-suppressed; recovered.
- **Valid transitions.** metric >= threshold -> set breach latch and cooldown
  key; first only -> alert; metric < threshold -> `getdel` breach latch and
  send recovery **[V]** (`health_monitor.py:159-217`).
- **Invalid or missing.**
  - If Redis is down, `r=None` and alerts are sent every tick
    **[V]** (`health_monitor.py:150-175`).
  - Latches are Redis-only; a flush loses breach state **[V]**.
- **Triggers.** Celery beat, `health_check_interval_seconds` (60 s).
- **DB fields.** `app_settings["health_alerts"]`; Redis
  `logvault:health:breach:*`, `logvault:health:alerted:*`,
  `logvault:health:sample`.
- **Responsible code.** `worker/app/health_monitor.py`.
- **External dependencies.** psutil, Redis, Slack, SMTP.
- **Recovery / retry.** Cooldown suppresses repeat alerts; recovery notice is
  best-effort.
- **Validation notes.** Each metric has its own latch. `getdel` makes recovery
  one-shot **[V]**.

### 16. Notification delivery

- **States.** not attempted; retrying; sent; failed (per channel).
- **Valid transitions.** `_retry` loops up to `notification_max_retries` (3)
  with linear delay; success stops; final failure is logged **[V]**
  (`notifications.py:76-99`, `101-150`).
- **Invalid or missing.**
  - No persisted delivery state or idempotency key. A retry after a partial
    send can duplicate the alert **[A]**.
  - API and worker have separate implementations with different backoff
    comments and logging **[V]** (`api/.../notifications.py` vs
    `worker/.../notifications.py`).
- **Triggers.** Job failure, S3 failure, health alert, recovery.
- **DB fields.** `app_settings["notifications"]`; none for delivery.
- **Responsible code.** `api/app/notifications.py`,
  `worker/app/notifications.py`.
- **External dependencies.** SMTP, Slack webhook.
- **Recovery / retry.** In-memory retry only; a process crash loses the
  attempt.
- **Validation notes.** Alert failure is suppressed so it cannot change the job
  outcome **[V]**.

### 17. Worker capacity

- **States.** configured N; live pool M; active jobs A.
- **Valid transitions.** `pool_grow`/`pool_shrink` by delta, then poll until
  the live size matches **[V]** (`tasks_client.py:78-140`).
- **Invalid or missing.**
  - `WORKER_CONCURRENCY` only applies on restart; the live resize is ephemeral
    **[V]**.
  - No persisted desired capacity or reconciliation loop.
- **Triggers.** Admin capacity card; worker restart.
- **DB fields.** None; env and Celery control.
- **Responsible code.** `api/app/tasks_client.py`,
  `api/app/routers/admin.py`.
- **External dependencies.** Celery control channel.
- **Recovery / retry.** Retry the resize; a restart returns to env value.
- **Validation notes.** `worker_capacity` reads live pool processes rather
  than `max-concurrency` **[V]** (`tasks_client.py:51-76`).

### 18. Retention / artifact expiry / download links

- **States.** file present; file expired/deleted; signed link valid/expired.
- **Valid transitions.**
  - `finished_at < now - export_retention_days` -> delete files, null paths,
    add warn event **[V]** (`scheduler.py:288-320`).
  - distinct store kept an extra 31 days **[V]** (`scheduler.py:258-262`).
  - low disk -> purge oldest 20 completed outputs **[V]**
    (`scheduler.py:329-369`).
  - signed link expires at `download_url_ttl_seconds` (7 days) **[V]**
    (`signing.py:24-30`).
- **Invalid or missing.**
  - The job remains `completed` after files are gone; `has_output` is derived
    from path + existence **[V]** (`jobs.py:76-84`).
  - Low-disk purge nulls output/summary/counts but not
    `unmatched_file_path` **[V]** (`scheduler.py:352-367`).
  - Queued-canceled jobs have `finished_at=NULL` and are never selected
    **[V]** (`scheduler.py:271-283`).
- **Triggers.** Celery beat hourly; download request; manual delete-files.
- **DB fields.** artifact paths, `finished_at`, `status`; URL `exp/sig`.
- **Responsible code.** `worker/app/scheduler.py`, `api/app/signing.py`,
  `api/app/routers/jobs.py`.
- **External dependencies.** Local filesystem, S3 (copy remains).
- **Recovery / retry.** Files are not recoverable after deletion; S3 may retain
  a copy. There is no "re-materialize" path.
- **Validation notes.** Retention is a file lifecycle, not a job lifecycle.
  Treating it as a job status is the modeling mistake.

### 19. Index cache

- **States.** miss; hit; invalidated.
- **Valid transitions.** GET miss -> DB -> `SETEX` 900 s; write -> delete all
  and region key **[V]** (`indexes.py:26-40`, `114-146`).
- **Invalid or missing.**
  - Invalidation failure is suppressed; a stale cache can survive 15 min
    **[V]** (`indexes.py:33-40`).
- **Triggers.** `GET /indexes`; create/update/delete index.
- **DB fields.** Redis `logvault:indexes:<region|all>`; `index_targets`.
- **Responsible code.** `api/app/routers/indexes.py`.
- **External dependencies.** Redis.
- **Recovery / retry.** TTL bounds staleness.
- **Validation notes.** This is a cache, not a workflow. Included because the
  original audit counted it.

### 20. Beat / readiness

- **States.** beat fresh; beat stale; ready ok/degraded; ops ok/degraded.
- **Valid transitions.** beat writes `logvault:beat` with 600 s TTL at the end
  of a successful scan **[V]** (`scheduler.py:41-52`). `/ready` checks Postgres
  and Redis **[V]** (`health.py:35-57`). `/health/ops` checks beat and backups
  **[V]** (`health.py:60-101`).
- **Invalid or missing.**
  - `/ready` does not include the worker; a dead worker leaves the API ready
    **[V]** (by design, documented).
  - Beat write failure is suppressed; schedules can run while the heartbeat is
    missing, or vice versa **[V]**.
- **Triggers.** Beat tick; UI poll every 15 s.
- **DB fields.** Redis beat key; backup filesystem.
- **Responsible code.** `worker/app/scheduler.py`,
  `api/app/routers/health.py`, `web/components/api-status.tsx`.
- **External dependencies.** Redis, Postgres, backup volume.
- **Recovery / retry.** TTL expiry is the signal.
- **Validation notes.** `/health/ops` exists because readiness should not pull
  a healthy API out of rotation for a dead worker.

### 21. Auth session

- **States.** authenticated; expired; cleared.
- **Valid transitions.** login -> 24 h JWT stored in localStorage and a
  SameSite cookie **[V]** (`auth.py:31-48`, `web/lib/api.ts:20-39`).
  Any 401 -> clear token/cookie and redirect to `/login` **[V]**
  (`api.ts:58-72`).
- **Invalid or missing.**
  - No refresh token or silent renewal; the user is logged out at 24 h
    **[V]**.
  - The token is readable by JavaScript (localStorage), so XSS is a full
    account compromise **[A]**.
- **Triggers.** Login, any API 401, logout.
- **DB fields.** None; JWT claims.
- **Responsible code.** `api/app/routers/auth.py`, `api/app/deps.py`,
  `web/lib/api.ts`.
- **External dependencies.** `JWT_SECRET`.
- **Recovery / retry.** Re-login.
- **Validation notes.** There is no server-side session revocation list.

### 22. Parse mode

- **States.** raw (off); parse-only (`enabled && !aggregate`); parse+aggregate
  (`enabled && aggregate`); library (`use_library`).
- **Valid transitions.** Set at job/schedule creation from the aggregation
  booleans; immutable for the job.
- **Invalid or missing.**
  - There is no explicit `parse_mode` enum. Every consumer re-derives it from
    `enabled`, `aggregate`, and `use_library`.
  - `use_library` requires at least one enabled log format or the job fails
    with an aggregation config error **[V]** (`runner.py:312-334`).
- **Triggers.** Job create; schedule create/update; template load; auto-detect
  apply.
- **DB fields.** `jobs.filter_spec.aggregation.*`;
  `schedules.filter_spec.aggregation.*`;
  `filter_templates.aggregation`.
- **Responsible code.** `api/app/schemas.py`, `worker/app/last9/aggregate.py`,
  `worker/app/runner.py`, `web/app/jobs/new/page.tsx`.
- **External dependencies.** Log format library.
- **Recovery / retry.** A bad parse config fails the job before extraction
  **[V]** (`runner.py:335-347`).
- **Validation notes.** The four modes produce different columns and counts;
  they are not cosmetic.

## 4. Client-only machines

### 23. New-extraction wizard

- **States.** steps 1-5; current step; visited steps; per-step done/blocked;
  ready to run **[V]** (`jobs/new/page.tsx:257-262`, `987-1036`).
- **Valid transitions.** Continue only when the current step is done; the rail
  can jump to any step; `goToStep` marks visited **[V]** (`1038-1044`).
- **Invalid or missing.**
  - Step 4 is always "done" **[V]** (`1014`), so it is informational.
  - State resets on reload; the wizard is not deep-linkable **[V]**.
  - `stepBlocker` text is the only explanation for a blocked step
    **[V]** (`1017-1036`).
- **Triggers.** User navigation; field changes; template load; auto-detect
  apply.
- **DB fields.** None until create.
- **Responsible code.** `web/app/jobs/new/page.tsx`.
- **External dependencies.** Credentials, indexes, templates, format library.
- **Recovery / retry.** None; the draft is lost on reload.
- **Validation notes.** The run button is gated by `canRun`, not by step
  completion, so a user can run from the review step while an earlier step is
  invalid if the shared fields still satisfy `canRun` **[V]** (`887-891`,
  `1157-1167`).

### 24. Save-as-search conflict

- **States.** idle; naming; saving; conflict(create/update); renaming; saved
  **[V]** (`jobs/new/page.tsx:50-55`, `245-248`).
- **Valid transitions.** Save -> preflight duplicate -> conflict; "Update
  existing" / "Rename" / "Cancel"; a 409 falls back to conflict
  **[V]** (`386-388`, `498-545`).
- **Invalid or missing.**
  - No optimistic concurrency; "Update existing" overwrites the current row
    **[V, A]**.
  - Conflict state is local; a second tab's change is not detected.
- **Triggers.** Save template; duplicate name; server 409.
- **DB fields.** `filter_templates.name` (unique), `filter_templates.*`.
- **Responsible code.** `web/app/jobs/new/page.tsx`.
- **External dependencies.** Templates API.
- **Recovery / retry.** Rename or update; no merge.
- **Validation notes.** The unique constraint on `name` is the only guard
  **[V]** (`models.py:248`).

### 25. Auto-detect panel

- **States.** closed; open-empty; detecting; result; applied; saved; error
  **[V]** (`auto-detect-panel.tsx:124-129`).
- **Valid transitions.** Detect -> result; Use this -> apply; Save -> create
  log format; Detect resets result/applied/saved **[V]**
  (`174-183`, `197-199`).
- **Invalid or missing.**
  - Result is not persisted; closing/reloading loses it.
  - "Use once" applies an inferred regex without saving it; the wizard owns the
    value afterwards.
- **Triggers.** Detect, apply, save.
- **DB fields.** `log_formats` on save; none otherwise.
- **Responsible code.** `web/components/auto-detect-panel.tsx`.
- **External dependencies.** Detect API, log formats API.
- **Recovery / retry.** Re-detect.
- **Validation notes.** Detection is deterministic against saved patterns; no
  external model is called **[V]**.

### 26. Jobs list filters / selection

- **States.** tab (`all|previews|status`); search; selection; bulk-confirm;
  bulk-result **[V]** (`jobs/page.tsx:46-60`, `82-117`, `161-190`).
- **Valid transitions.** tab/search -> URL; select active -> bulk cancel ->
  canceled/skipped; selection pruned when a job leaves active
  **[V]** (`168-174`).
- **Invalid or missing.**
  - Selection is not persisted across reload.
  - "Select all" only touches `isActive` rows in the current view
    **[V]** (`257-269`).
- **Triggers.** Tab click, search input, row checkbox, bulk cancel.
- **DB fields.** None; URL `tab`, `q`.
- **Responsible code.** `web/app/jobs/page.tsx`.
- **External dependencies.** Jobs list, stats, bulk cancel.
- **Recovery / retry.** Refresh; the server reports skipped IDs.
- **Validation notes.** Counts come from the server aggregate, not the loaded
  page **[V]** (`248-255`).

### 27. Job live feed

- **States.** `connecting`; `live`; `reconnecting`; `closed`
  **[V]** (`jobs/[id]/page.tsx:137-142`, `185-223`).
- **Valid transitions.** `onopen` -> live; event -> live; terminal type ->
  closed; error -> reconnecting or closed; `error` message -> closed
  **[V]**.
- **Invalid or missing.**
  - On reconnect the server restarts `last_event_id=0`
    **[V]** (`jobs.py:1167`), and the client prepends every event again with
    no dedupe **[V]** (`jobs/[id]/page.tsx:198-199`). The feed duplicates
    lines after a drop.
  - There is no `paused` terminal event; the stream stays open and polls every
    3 s **[V]** (`jobs.py:1187-1188`).
- **Triggers.** Page load; EventSource open/message/error; terminal status.
- **DB fields.** `jobs.status`, `rows_written`, counters, `job_events`.
- **Responsible code.** `web/app/jobs/[id]/page.tsx`,
  `api/app/routers/jobs.py:1100-1190`.
- **External dependencies.** SSE endpoint, signed progress ticket (12 h TTL).
- **Recovery / retry.** EventSource reconnects automatically; a 30 s job query
  is the fallback **[V]** (`jobs/[id]/page.tsx:127-133`).
- **Validation notes.** The 12 h ticket outlives a normal job but not an
  arbitrarily long one.

### 28. Job actions / confirmations

- **States.** idle; pending; applied; error; confirm cancel; confirm delete
  files **[V]** (`jobs/[id]/page.tsx:137`, `264-315`).
- **Valid transitions.** Pause/resume/cancel/retry/delete-files/S3-retry;
  409/error shown; confirm strips **[V]**.
- **Invalid or missing.**
  - Buttons are gated by status, not by a server-computed capability. A stale
    row can show an action that the server rejects.
  - Retry navigates to the new job; the old job remains.
- **Triggers.** Button clicks; confirm.
- **DB fields.** Job status and artifact paths.
- **Responsible code.** `web/app/jobs/[id]/page.tsx`.
- **External dependencies.** Job action endpoints.
- **Recovery / retry.** Refresh; error text is shown.
- **Validation notes.** `actionError` surfaces the first failed mutation
  **[V]** (`311-315`).

### 29. Templates batch / editor

- **States.** viewing; selecting; batch-open; created; row editing;
  confirm-delete **[V]** (`templates/page.tsx`).
- **Valid transitions.** Select -> batch -> created jobs; edit -> save/cancel;
  delete confirm.
- **Invalid or missing.** Selection is local; batch result is not persisted.
- **Triggers.** Checkbox, batch action, edit, delete.
- **DB fields.** `filter_templates.*`, `jobs.group_id`.
- **Responsible code.** `web/app/templates/page.tsx`.
- **External dependencies.** Templates and batch APIs.
- **Recovery / retry.** Refresh; partial batch failures are surfaced by the
  API as a whole-request error (see machine 35).
- **Validation notes.** One-search batches stay plain jobs; multi-search
  batches create a group **[V]** (`jobs.py:417-434`).

### 30. Schedule forms

- **States.** list; adding; row editing; rolling up; confirm delete
  **[V]** (`schedules/page.tsx:126-128`).
- **Valid transitions.** Add -> save/cancel; edit -> save/cancel; rollup ->
  job; delete -> confirm.
- **Invalid or missing.** Row forms are independent; a save in one row does
  not close another. `last_run_at` is displayed as "last run" even though it
  is a dispatch cursor **[V]** (`schedules/page.tsx:160`).
- **Triggers.** Buttons; form submit.
- **DB fields.** `schedules.*`; `jobs.rollup_of`.
- **Responsible code.** `web/app/schedules/page.tsx`.
- **External dependencies.** Schedules and rollup APIs.
- **Recovery / retry.** Error text per form; no draft persistence.
- **Validation notes.** Rollup uses the schedule's aggregation config; a
  schedule without it cannot roll up **[V]** (`jobs.py:608-613`).

### 31. Groups create / detail

- **States.** create: selection, custom window, test/run pending, error;
  detail: active/done, cancel-confirm, retry **[V]**
  (`groups/new/page.tsx`, `groups/[id]/page.tsx:111-135`).
- **Valid transitions.** Select -> test/run -> detail; cancel -> confirm;
  retry -> child group.
- **Invalid or missing.**
  - Detail derives status from the server; the client has its own
    `GROUP_STATUS` map and `active()` predicate **[V]**
    (`groups/[id]/page.tsx:24-49`).
  - A stale group can show "Cancel group" after it finished.
- **Triggers.** Selection, run, cancel, retry.
- **DB fields.** `extraction_groups.*`, `jobs.group_id`.
- **Responsible code.** `web/app/groups/new/page.tsx`,
  `web/app/groups/[id]/page.tsx`.
- **External dependencies.** Groups API.
- **Recovery / retry.** Refresh; retry creates a child group.
- **Validation notes.** The client's `active()` treats only `queued|running`
  as active, while the server counts `paused` as running
  **[V]** (`groups.py:40`; `groups/[id]/page.tsx:49`). A paused child can make
  the group `running` while the UI hides the cancel button.

### 32. Reports view

- **States.** window days; retention edit/save; remove-confirm; alert list
  **[V]** (`reports/page.tsx:398-471`).
- **Valid transitions.** Window -> URL; retention -> save -> refetch; remove
  schedule -> confirm.
- **Invalid or missing.**
  - Window is clamped by retention; changing retention can clamp the window
    **[V]** (`reports/page.tsx:436-437`).
  - Alert list has no acknowledgement state.
- **Triggers.** Select, save, remove.
- **DB fields.** `app_settings["reports"]`; schedules/jobs for the report.
- **Responsible code.** `web/app/reports/page.tsx`.
- **External dependencies.** Reports and settings APIs.
- **Recovery / retry.** Refetch; save error inline.
- **Validation notes.** The view is URL-backed (`?days=`), unlike most other
  workflow state **[V]**.

### 33. Command palette

- **States.** closed; open-empty; querying; results; active item
  **[V]** (`command-palette.tsx`).
- **Valid transitions.** Cmd/Ctrl-K or pill -> open; type -> filter; arrows ->
  active; Enter -> navigate; Esc/backdrop -> close.
- **Invalid or missing.** No server state; results can be stale if data
  changes.
- **Triggers.** Keyboard, click.
- **DB fields.** None.
- **Responsible code.** `web/components/command-palette.tsx`.
- **External dependencies.** Cached client data.
- **Recovery / retry.** Reopen.
- **Validation notes.** Pure UI; included for completeness.

### 34. Login form

- **States.** idle; submitting; error; redirect **[V]**
  (`web/app/login/page.tsx`).
- **Valid transitions.** Submit -> loading -> token/redirect or error; Google
  enabled/disabled.
- **Invalid or missing.** No client-side lockout countdown; the server 429 is
  shown as an error.
- **Triggers.** Submit; provider availability.
- **DB fields.** None.
- **Responsible code.** `web/app/login/page.tsx`.
- **External dependencies.** Auth API, Google flow.
- **Recovery / retry.** Re-submit; 429 clears after the server window.
- **Validation notes.** The `from` query parameter controls the post-login
  redirect; it is sanitized server-side for OAuth.

## 5. Added machines

### 35. Create -> dispatch handoff

- **States.** validated; committed (`queued`); published; publish-failed;
  duplicate-on-retry.
- **Valid transitions.**
  - validate -> insert -> `db.commit()` -> `dispatch_job()` -> response
    **[V]** (`jobs.py:313-327`).
  - batch/group: commit all -> refresh -> dispatch each in a loop
    **[V]** (`jobs.py:474-478`, `groups.py:216-225`).
- **Invalid or missing.**
  - `dispatch_job` is outside the transaction and has no outbox, retry, or
    error handling in the create routes **[V]** (`tasks_client.py:17-22`).
  - If the broker is unreachable, the row is already committed, the API
    returns 500, and the client has no id to reconcile. A user retry creates a
    second job **[V, structural]**.
  - In a batch/group, one publish failure aborts the remaining loop; earlier
    jobs are published, later ones stay `queued` **[V]**.
  - The scheduler does handle publish failure by continuing
    **[V]** (`scheduler.py:178-187`), but it records no event.
- **Triggers.** Any create route.
- **DB fields.** `jobs.status="queued"`, `created_at`.
- **Responsible code.** `api/app/routers/jobs.py`,
  `api/app/routers/groups.py`, `api/app/tasks_client.py`.
- **External dependencies.** Celery broker.
- **Recovery / retry.** A queued row can be picked up only if something
  re-dispatches it. There is no sweeper for `queued` jobs; the reaper only
  handles `running`. A broker outage therefore leaves orphaned `queued` rows
  until a human retries.
- **Validation notes.** This is a missing state machine, not just an error
  path: there is no `publish_pending` / `published` distinction.

### 36. Celery delivery / acknowledgement / redelivery

- **States.** published; delivered; executing; acknowledged; redelivered;
  rejected/requeued.
- **Valid transitions.**
  - publish -> deliver -> execute; `acks_late` means ack after completion
    **[V]** (`celery_app.py:20-21`).
  - worker lost -> broker redelivers; `redelivered=True` -> reclaim allowed
    **[V]** (`tasks.py:156-174`).
  - prefetch 1 prevents one worker hoarding jobs **[V]**.
- **Invalid or missing.**
  - The application has no visibility into a message that is published but
    never delivered. The job stays `queued` with no event **[V]**.
  - There is no dead-letter queue or delivery-attempt counter.
  - A task can be redelivered while the old worker is still alive in edge
    cases (broker visibility timeout, long GC pause); the claim guard relies on
    the event age, not a lease **[A]**.
- **Triggers.** Broker, worker lifecycle.
- **DB fields.** `jobs.status`, `job_events`.
- **Responsible code.** `worker/app/celery_app.py`, `worker/app/tasks.py`.
- **External dependencies.** Celery broker/result backend.
- **Recovery / retry.** Redelivery; reaper; manual retry.
- **Validation notes.** `task_reject_on_worker_lost=True` makes redelivery the
  normal crash path **[V]**.

### 37. Rollup execution subtype

- **States.** `queued`; `running`; `completed`; `failed`; canceled (not
  honored).
- **Valid transitions.**
  - create rollup -> `queued` **[V]** (`jobs.py:628-655`).
  - `run_rollup` -> unconditional `running` **[V]** (`rollup.py:80-86`).
  - merge sources -> `completed` with `completed_chunks=total_chunks=usable`
    **[V]** (`rollup.py:228-241`).
  - exception -> `failed` **[V]** (`rollup.py:181-210`).
- **Invalid or missing.**
  - No `claim_job` and no ownership check **[V]** (`rollup.py:85`).
  - No pause/cancel polling; a cancel request is ignored and the rollup can
    finish `completed` **[V]**.
  - Two dispatches can run the same rollup concurrently and write the same
    distinct store and output files **[V, structural]**.
  - `find_source_jobs` selects all statuses and filters in Python; skipped
    sources are warned but the rollup still `completed` **[V]**
    (`rollup.py:53-73`, `128-137`, `212-241`).
- **Triggers.** `POST /jobs/rollup`; Celery `run_job` with `rollup_of` set.
- **DB fields.** `rollup_of` JSON (`schedule_id`, `label`, `source_job_ids`),
  status, counters, artifact paths, `aggregation_result`.
- **Responsible code.** `worker/app/rollup.py`, `worker/app/tasks.py:161-174`.
- **External dependencies.** Source distinct stores, local filesystem.
- **Recovery / retry.** Retry creates a new rollup with a fresh source list.
- **Validation notes.** This is a distinct execution machine hiding inside the
  job lifecycle. It is the clearest example of why "one status column" is not
  enough: the same statuses have different guards and different failure modes.

### 38. Schedule window idempotency

- **States.** window owed; window checked; inserted; already-covered.
- **Valid transitions.**
  - for each owed window: `_already_extracted` -> skip or insert
    **[V]** (`scheduler.py:140-142`).
  - `last_run_at=now` after the loop **[V]**.
- **Invalid or missing.**
  - Check-then-insert is not atomic; no unique index
    **[V]** (`scheduler.py:94-108`; `models.py:44-97`).
  - `_already_extracted` ignores status, so a failed/canceled window is
    treated as covered **[V]**.
  - Two beat processes (a documented deployment risk; the module says "run one
    dedicated beat") can both insert the same window **[V, A]**.
- **Triggers.** Beat scan every 60 s.
- **DB fields.** `jobs.created_by`, `jobs.start_epoch`, `schedules.last_run_at`.
- **Responsible code.** `worker/app/scheduler.py`.
- **External dependencies.** Postgres transaction isolation.
- **Recovery / retry.** Manual retry of the duplicate job; no automatic
  dedupe.
- **Validation notes.** The docstring claims idempotency for crash recovery
  **[V]** (`scheduler.py:94-100`), but the implementation is not idempotent
  under concurrency. This is a verified gap between comment and code.

### 39. S3 upload attempt ownership

- **States.** no attempt; uploading; uploaded; partial; failed; retrying.
- **Valid transitions.** dispatch -> load job/profile -> upload artifacts ->
  write `s3_*` **[V]** (`tasks.py:180-228`).
- **Invalid or missing.**
  - No attempt token, timestamp, or lock. Concurrent retries can both upload
    and both write the row **[V]**.
  - `s3_uploaded_at` is set if any URI exists; a later failure can set
    `s3_error` without clearing the timestamp, producing a row that is both
    "uploaded" and "failed" **[V]**.
  - The endpoint does not clear `s3_error` before dispatch, so the UI shows the
    old failure until the task finishes **[V]**.
- **Triggers.** `POST /jobs/{id}/s3-upload`.
- **DB fields.** `s3_uri*`, `s3_error`, `s3_uploaded_at`.
- **Responsible code.** `api/app/routers/jobs.py:488-507`,
  `worker/app/tasks.py:180-228`, `worker/app/s3.py`.
- **External dependencies.** S3.
- **Recovery / retry.** Re-dispatch; no backoff.
- **Validation notes.** Uploads are idempotent at the object-key level
  (overwrite), but the row update is last-writer-wins.

### 40. Preview -> full promotion

- **States.** preview completed; promoted (new full job); canceled.
- **Valid transitions.** The job detail page builds a `createJob` request from
  the preview's fields and navigates to the new job **[V]**
  (`jobs/[id]/page.tsx:93-113`).
- **Invalid or missing.**
  - No server-side promotion endpoint, so there is no idempotency key and no
    link from the preview to the full job.
  - The clone omits `group_id`, `s3_profile_id`, `exclude_phrases`, and
    `exclude_exact_phrases` **[V]**.
  - The clone keeps `start_epoch` / `end_epoch` from the preview, which are
    the original selected window, not the sampled slice; that is correct, but
    it is implicit.
- **Triggers.** "Run full extraction" / "Run again".
- **DB fields.** New `jobs` row; `is_preview=false`.
- **Responsible code.** `web/app/jobs/[id]/page.tsx`,
  `api/app/routers/jobs.py:create_job`.
- **External dependencies.** Create job API.
- **Recovery / retry.** Re-click; a duplicate full job is possible.
- **Validation notes.** This is a client-side copy machine with no persisted
  lineage (`preview_of` / `promoted_to`).

## 6. Cross-machine findings

### 6.1 Status vocabulary duplication

The job status vocabulary is redefined in at least 14 places:

| Location | Set / purpose |
|---|---|
| `api/app/schemas.py:199` | `JobStatus` Literal |
| `api/app/routers/jobs.py:60-63` | `_TERMINAL`, `_DOWNLOADABLE` |
| `api/app/routers/customers.py:31` | `_ACTIVE` |
| `api/app/routers/groups.py:35` | `ACTIVE_STATUSES` |
| `api/app/routers/groups.py:38-50` | group derivation |
| `api/app/routers/reports.py:53` | `ACTIVE_STATUSES` |
| `api/app/routers/reports.py:100-125` | day derivation |
| `worker/app/runner.py:49-57` | `_Stopped`, status poll |
| `worker/app/db.py:193-230` | claim predicate |
| `worker/app/scheduler.py:192-249` | reaper predicate |
| `web/lib/api.ts:217` | `JobStatus` union |
| `web/lib/api.ts` | `JOB_TONE` map |
| `web/lib/use-jobs.ts:6-10` | `ACTIVE_STATUSES`, `isActive` |
| `web/app/jobs/page.tsx:46-60` | `STATUS_TABS` |
| `web/app/jobs/[id]/page.tsx:58` | `TERMINAL` |
| `web/app/page.tsx` | `STATUS_COLOR` |
| `web/app/groups/[id]/page.tsx:24-49` | `GROUP_STATUS`, `JOB_STATUS` |

Adding a state is a multi-file change with no cross-language compiler check.

### 6.2 Derived status precedence differs

| Source | Precedence | Effect |
|---|---|---|
| Group (`groups.py:38-50`) | running/paused > queued > all failed > all canceled > any failed/canceled -> partial > completed | 9 failed + 1 completed -> `partial` |
| Report day (`reports.py:100-125`) | failed > running > canceled+completed -> partial > canceled > ok | any failed -> `failed` |
| Comparison | both ok > one ok -> partial > none -> failed | independent |
| S3 badge | error > uri > pending | partial upload shows failed |

These are all defensible individually, but they are not one model.

### 6.3 "Completed" overload

`completed` currently covers:

- clean full extraction;
- extraction with skipped ID batches (`error_message` set);
- rollup with skipped source runs (warn event only);
- preview sample (capped rows);
- BigQuery run with unmatched rows;
- a job whose local files were later deleted by retention;
- a job whose S3 upload failed or partially succeeded.

No consumer can distinguish these without parsing free text or inspecting
unstructured JSON.

### 6.4 Request state vs acknowledged state

Pause, cancel, resume, retry, S3 retry, and group cancel are all *requests*
written directly to the row. There is no acknowledgement state, so the API's
response means "the row was updated", not "the worker complied". This is the
root of the cancel/complete and pause/resume races.

## 7. State-like but not state machines

These were checked and deliberately excluded from the 40:

- Log-format `enabled` and `priority`: policy flags, idempotent registration.
- Index cache TTL: cache lifecycle, no workflow semantics.
- Theme and timezone preferences: client preference.
- Table sort/filter controls: view state only.
- Notification SMTP/Slack configuration: settings, not transition.
- CRUD edit forms without multi-step transitions.
- Backup freshness (`/health/ops`): a health signal, not an application state.
- Comparison history retention: a cleanup policy.
- `jobs.updated_at`: an ORM audit column that the worker does not maintain;
  it is not a lifecycle signal.

## 8. Validation limits

- No production traces, Postgres isolation-level tests, or Celery broker
  inspection were performed.
- Race probabilities are estimates. The code structure is cited; incident
  frequency is not measured.
- The audit did not verify deployment topology (single vs multiple beat
  processes, number of API replicas). Several concurrency findings become more
  likely with more than one process.
- `docs/STATE_MACHINE_RISKS.md` separates verified behavior from estimated
  probability and states where runtime confirmation is required.
