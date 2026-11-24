# State Machine Risks

Status: risk register derived from the validated audit. This is analysis, not a
list of proven production incidents. Every finding states whether the behavior
is verified in code or only a structural possibility.

Legend:

- **Verified behavior [V]** - the code does what the row says.
- **Verified race [V-R]** - the unsafe write/absent guard is present; whether it
  occurs is not measured.
- **Assumption [A]** - depends on deployment topology, timing, or data.
- **Recommendation [R]** - proposed mitigation.

Severity, probability, and business impact are estimates. Probability is
relative to the current deployment assumptions (see section 1).

## 1. Rating method

### Severity

| Level | Meaning |
|---|---|
| Critical | Silent wrong data, uncontrolled execution, or credential loss across customers. |
| High | Wrong status/report, duplicated work, or a control action that does not hold. |
| Medium | Local inconsistency, operational confusion, or recoverable data loss. |
| Low | Cosmetic, single-user, or easily reversed. |

### Probability

| Level | Meaning |
|---|---|
| High | Likely in normal use (multiple times per month). |
| Medium | Possible in normal use (a few times per year). |
| Low | Requires a race, an outage, or a rare deployment. |
| Unknown | No runtime evidence; depends on topology. |

### Business impact

- **Data integrity** - the artifact or count is wrong or incomplete.
- **Reporting** - dashboards, reports, or alerts misstate reality.
- **Cost** - duplicate Last9 queries, compute, or storage.
- **Control** - an operator cannot stop/retry/pause reliably.
- **Security** - authentication or credential exposure.
- **Operations** - on-call burden, silent failure, cleanup failure.

### Deployment assumptions

- One API process is not guaranteed; the code supports multiple.
- The scheduler docstring recommends one dedicated beat process, but nothing
  enforces it **[V]** (`scheduler.py:1-6`).
- Redis and Postgres are single logical instances in the current compose-style
  deployment; this is an assumption **[A]**.
- The worker has `worker_concurrency=4` by default and `acks_late=True`
  **[V]** (`celery_app.py:20-31`).

## 2. Risk register

| ID | Risk | Evidence | Status | Severity | Probability | Impact |
|---|---|---|---|---|---|---|
| R-01 | Cancel is overwritten by a late completion write | `jobs.py:858-866`; `runner.py:830-831` | V-R | **Critical** | Low-Medium | Control, data integrity, audit |
| R-02 | Pause then quick resume creates two writers | `jobs.py:834-848`; `runner.py:647-652`; `db.py:210-230` | V-R | **Critical** | Medium | Data integrity, cost |
| R-03 | Reclaim has no fencing token; old worker can keep writing | `db.py:185-186`, `210-230`; `runner.py:626-630` | V-R | **Critical** | Low-Medium | Data integrity, wrong counts |
| R-04 | Rollup bypasses claim and ignores cancel/pause | `rollup.py:80-86`, `228-241` | V | **High** | Medium | Control, duplicate work |
| R-05 | Retry restarts instead of resuming, despite the reaper message | `jobs.py:975-996`; `scheduler.py:211-214` | V | **High** | High | Cost, time, duplicate data |
| R-06 | Commit succeeds but publish fails; job is orphaned `queued` | `jobs.py:324-327`; `tasks_client.py:17-22` | V-R | **High** | Medium | Cost, control, UX |
| R-07 | Schedule window insert is check-then-insert; no unique key | `scheduler.py:94-108`, `140-142`; `models.py:44-97` | V-R | **Critical** | Low | Duplicate extraction, cost, report noise |
| R-08 | A failed/canceled scheduled window is treated as covered forever | `scheduler.py:94-108` | V | **High** | Medium | Silent data gap |
| R-09 | `completed` hides skipped ID batches | `runner.py:860-872` | V | **High** | Medium | Data integrity, reporting |
| R-10 | Rollup `completed` hides skipped source runs | `rollup.py:212-241` | V | **High** | Medium | Under-reported uniques |
| R-11 | Job status vocabulary duplicated 14+ times | See `STATE_MACHINES.md` 6.1 | V | **High** | High over time | Drift, multi-file bugs |
| R-12 | Group and report day disagree on precedence | `groups.py:38-50`; `reports.py:100-125` | V | **Medium** | High | Reporting inconsistency |
| R-13 | Report day keyed by `created_at`, schedule by window | `reports.py:161-165`; `scheduler.py:83-90` | V | **Medium** | Medium | Backfill misattribution |
| R-14 | `last_run_at` advances before dispatch; not a success signal | `scheduler.py:175-188` | V | **High** | Medium | Silent missed run |
| R-15 | Queued-canceled jobs have no `finished_at`, so retention never cleans | `jobs.py:858-866`; `scheduler.py:271-283` | V | **Medium** | High | Storage, dangling rows |
| R-16 | Concurrent token refresh can lose a rotated refresh token | `runner.py:369-380`; `tokens.py:110-118` | V-R | **High** | Low-Medium | Credential loss, all jobs fail |
| R-17 | Single-job retry drops `group_id` | `jobs.py:975-996` | V | **Medium** | High | Group counts/status wrong |
| R-18 | Preview promotion drops `group_id`, `s3_profile_id`, exclusions | `jobs/[id]/page.tsx:93-113` | V | **Medium** | Medium | Wrong delivery/filter behavior |
| R-19 | S3 retry has no lock; partial success is ambiguous | `jobs.py:488-507`; `tasks.py:180-228`; `runner.py:813-839` | V-R | **Medium** | Low-Medium | Delivery evidence |
| R-20 | Reaper can fail a live job during a long silent call | `scheduler.py:216-248`; `runner.py:653-664` | V-R | **High** | Low | Lost work, false alert |
| R-21 | SSE reconnect replays all events; UI duplicates the feed | `jobs.py:1167`; `jobs/[id]/page.tsx:198-199` | V | **Low** | Medium | UX confusion |
| R-22 | No DB check constraint on `jobs.status` | `models.py:44-97`; migrations 0001-0031 | V | **Medium** | Low | Invalid state possible |
| R-23 | Login throttle fails open and is per-email only | `auth.py:72-82`, `118-120` | V | **Low-Medium** | Low | Security |
| R-24 | OAuth state has a 600 s replay window, no one-time store | `auth.py:161-212`, `365-386` | V, A | **Low** | Low | Security |
| R-25 | Health latches are Redis-only; Redis loss repeats alerts | `health_monitor.py:159-217` | V | **Low** | Low | Alert noise |
| R-26 | Comparison runs have no persisted `running` | `comparisons.py:505-812` | V | **Low-Medium** | Low | Crash observability |
| R-27 | Notifications have no persisted delivery state | `notifications.py:76-99` | V | **Low** | Medium | Duplicate/missed alerts |
| R-28 | Low-disk purge leaves `unmatched_file_path` dangling | `scheduler.py:352-367` | V | **Low** | Medium | Broken download link |
| R-29 | `updated_at` is not maintained by Core writes | `models.py:93-95`; `scheduler.py:202-204` | V | **Low** | High | External monitoring wrong |
| R-30 | Empty group derives `completed` | `groups.py:44-50` | V, L | **Low** | Low | Incorrect badge if data manipulated |

## 3. Detailed analysis

### R-01 Cancel/complete race

**Verified behavior.** `POST /jobs/{id}/cancel` reads the row, checks
`status not in _TERMINAL`, writes `status="canceled"`, commits
**[V]** (`jobs.py:852-866`). The runner's final write sets
`status="completed"` with no `WHERE status=...` guard **[V]**
(`runner.py:830-831`, `894`).

**Race.** The cancel lands after the runner's last status poll but before the
final write. The row ends `completed`. The partial artifact may be complete or
not; the operator believes the job was stopped.

**Why it matters.** Cancel is the emergency control for an expensive or
incorrect extraction. A control that silently loses is a critical trust issue,
even if the data happens to be correct.

**Mitigation.** Either:

- set `cancel_requested_at` and let the worker finalize with a guarded write;
- or keep the immediate `canceled` write and make the worker finalizer write
  `canceled` when `cancel_requested_at` is set, guarded by
  `status IN ('running','canceled')`.

Add a property test: once `cancel_requested_at` is set, the final status is
never `completed`.

### R-02 Pause/resume double writer

**Verified behavior.** Pause writes `paused` immediately
**[V]** (`jobs.py:834-837`). Resume writes `queued` and dispatches
**[V]** (`jobs.py:845-848`). The runner checks the row every 10 s and stops
only on `paused` or `canceled` **[V]** (`runner.py:647-652`).

**Race.** Pause and resume happen within one status-check interval. The old
worker checks after resume, sees `queued` (not `paused`), and continues. The
new worker claims `queued` and writes. `claim_job` only prevents a second claim
while the row is still `running` **[V]** (`db.py:210-230`).

**Why it matters.** Two workers append to the same CSV and the same distinct
store. Depending on timing, the output can be duplicated, truncated, or
interleaved. The row can still finish `completed`.

**Mitigation.** A lease token plus a post-check ownership read. Resume must
increment the token; the old worker must abort when its token is stale. Do not
rely on `paused` being observed.

### R-03 Reclaim without fencing

**Verified behavior.** `claim_job` can take over a `running` row when
`redelivered=True` and the last event is older than `stale_reclaim_minutes`
**[V]** (`db.py:211-222`, `runner.py:225-235`). After the claim, every write is
unconditional by id **[V]** (`db.py:185-186`).

**Assumption.** A live-but-silent worker (long HTTP retry, GC pause, paused
process resumed) can coexist with the new owner. The heartbeat makes this
unlikely; it does not make it impossible.

**Why it matters.** Reclaim is the recovery path for a dead worker. If it can
produce two writers, the recovery path itself corrupts data.

**Mitigation.** Owner id + monotonic lease token + guarded writes. The old
worker's write returns 0 rows and aborts.

### R-04 Rollup ignores the lifecycle

**Verified behavior.** `run_rollup` sets `status="running"` unconditionally
**[V]** (`rollup.py:85`), never calls `claim_job`, and never polls for
`paused`/`canceled` **[V]**. The final write sets `completed`
unconditionally **[V]** (`rollup.py:228-241`).

**Consequences.**

- Two dispatches run concurrently and write the same output/store.
- Cancel sets `canceled`, but the rollup can finish `completed`.
- Pause is ignored.
- The reaper can fail a running rollup, but the rollup can still write
  `completed` afterward.

**Why it matters.** Rollups are month-end, expensive, and feed customer
numbers. They are exactly the job you must be able to stop and must not run
twice.

**Mitigation.** Use the same claim/lease and status poll as `run_extraction`.
Add a test that cancels a rollup and asserts the final status.

### R-05 Retry does not resume

**Verified behavior.** The reaper message says "Retry to resume from the last
checkpoint" **[V]** (`scheduler.py:211-214`). `retry_job` creates a new row and
copies window/settings but not `checkpoint`, `file_offset`, or chunk counters
**[V]** (`jobs.py:975-996`).

**Consequences.** A multi-hour job that failed at 90% re-extracts from zero.
The old partial artifact remains, so storage and confusion double. The
operator was told it would resume.

**Mitigation.** Choose one semantic and make the message/UI match. If resume is
desired, copy the checkpoint and verify the artifact still matches the offset;
otherwise change the message and add a clear "starts over" warning.

### R-06 Create/publish gap

**Verified behavior.** `create_job` commits, refreshes, then calls
`dispatch_job` outside the transaction **[V]** (`jobs.py:324-327`).
`dispatch_job` calls `send_task` with no retry/outbox **[V]**
(`tasks_client.py:17-22`). The same pattern exists in batch and group creation
**[V]** (`jobs.py:474-478`, `groups.py:216-225`).

**Consequences.**

- Broker down: row is `queued`, API returns 500, client has no id. A retry
  creates a duplicate.
- Batch/group: a mid-loop failure aborts later dispatches; earlier jobs run,
  later jobs stay `queued`.
- No sweeper retries `queued` rows.

**Mitigation.** Outbox or a `dispatch_pending` sweeper. Return the created row
even when publish fails, with a clear retry path.

### R-07 Schedule duplicate window

**Verified behavior.** `_already_extracted` selects by owner + `start_epoch`
**[V]** (`scheduler.py:94-108`). Insert happens later in the same transaction
**[V]** (`scheduler.py:143-165`). There is no unique index on
`(created_by, start_epoch)` in models or migrations 0001-0031 **[V]**.

**Assumption.** Two beat processes, or a crashed beat retried while the first
transaction is still in flight, can both pass the check and insert. The module
docstring recommends one dedicated beat, but nothing enforces it
**[V]** (`scheduler.py:1-6`).

**Consequences.** The same day is extracted twice, billed twice, and appears
twice in reports. The duplicate jobs are independent; canceling one does not
cancel the other.

**Mitigation.** Partial unique index + `ON CONFLICT DO NOTHING`, or an advisory
lock per schedule. Add a concurrent-scan test with two sessions.

### R-08 Failed window is never retried

**Verified behavior.** `_already_extracted` does not filter on status
**[V]** (`scheduler.py:101-108`). A failed or canceled job for a window makes
the scheduler skip that window on every later scan. `last_run_at` has already
advanced past it **[V]** (`scheduler.py:175-177`).

**Consequences.** A daily schedule that fails one day stays missing that day.
The report shows a failed day (so it is visible), but no automatic retry
occurs. Operators must manually retry the job. If the failure happened before
the job row was created (dispatch failure), the report may show `missed` or
nothing.

**Mitigation.** Define covered as `completed` only for retry purposes, or add a
per-window run record with status and attempt count. Keep an explicit
"do not retry" policy if that is the product intent, but document it.

### R-09 Completed with hidden gaps

**Verified behavior.** `skipped_batches > 0` writes `completed` plus an
`error_message` **[V]** (`runner.py:860-872`). The comment explicitly declines
a new status because it would touch schema/API/UI **[V]**.

**Consequences.** Reports count the run as successful. Group status says
`completed`. The UI may show the error text, but no aggregate or filter can
find "partial" jobs reliably. A customer reconciliation based on this output
is short by up to `skipped_batches * id_batch_size` IDs.

**Mitigation.** `completion_state` + `gap_count` + `gap_reason`; propagate to
group/report derivation. Do not add a seventh terminal status.

### R-10 Rollup skips are quiet

**Verified behavior.** Non-completed or missing-store sources are collected in
`skipped` **[V]** (`rollup.py:128-137`). The final message includes
"counts are incomplete" and is logged at `warn` if any skipped
**[V]** (`rollup.py:212-241`). The status is `completed`; `error_message` is
not set.

**Consequences.** A month-end unique count can under-report while looking
clean. This is the worst kind of reporting failure: a plausible number with no
visible caveat except a log line.

**Mitigation.** Set `completion_state=partial` and `gap_count` for rollups;
surface it in the schedule/report row. Consider blocking a rollup if a source
store is missing, or requiring an explicit override.

### R-11 Vocabulary drift

**Verified behavior.** The sets are duplicated in at least 14 places
(see `STATE_MACHINES.md` 6.1). There is no generated contract.

**Consequences.** A new state is added to the API and forgotten in the worker
claim predicate, the UI tab list, or the reaper. The result is a job that can
be created but not claimed, or a status that renders with no label.

**Mitigation.** Shared Python module + generated TypeScript + contract test.
This is the highest-leverage structural fix and has no schema impact.

### R-12 Group vs report precedence

**Verified behavior.**

- Group: any running/paused -> running; queued -> queued; all failed ->
  failed; all canceled -> canceled; any failed/canceled -> partial; else
  completed **[V]** (`groups.py:38-50`).
- Report: any failed -> failed; any active -> running; canceled+completed ->
  partial; else ok **[V]** (`reports.py:100-125`).

**Consequence.** A group with 9 failed and 1 completed is `partial`; the same
day in the report is `failed`. Both are "correct" under their own rules.

**Mitigation.** One derivation helper with documented precedence. If the
product wants "failed dominates", apply it everywhere; if "partial" is more
useful for a batch, document the difference and make the UI explain it.

### R-13 Report day attribution

**Verified behavior.** Jobs are bucketed by `created_at` UTC
**[V]** (`reports.py:161-165`). A calendar-day schedule's window is the
previous UTC day **[V]** (`scheduler.py:83-90`). A backfill run created today
for yesterday's window appears under today.

**Consequence.** A weekend backfill shows as a spike on Monday; "yesterday" and
"same weekday last week" comparisons are wrong for backfilled days.

**Mitigation.** For calendar-day schedules, bucket by
`datetime.fromtimestamp(start_epoch, UTC).date()`. Keep `created_at` for
interval schedules, or add a `window_day` column if the query cost matters.

### R-14 `last_run_at` is not success

**Verified behavior.** The beat updates `last_run_at=now` inside the scan
transaction, before dispatch **[V]** (`scheduler.py:175-188`). Reports prefer
the latest job's `created_at` over `schedule.last_run_at` **[V]**
(`reports.py:205`). The schedules page labels `last_run_at` as "last run"
**[V]** (`schedules/page.tsx:160`).

**Consequence.** A dispatch failure leaves a recent `last_run_at` with no
running job. The schedule looks current; the report may show `pending` or
`missed` depending on job rows. Two sources of truth.

**Mitigation.** Treat `last_run_at` as `last_dispatch_at` in the UI and docs;
derive `last_success_at` from completed jobs, or add it if a query needs it.
Do not use the cursor as a success signal.

### R-15 Queued cancel is never cleaned

**Verified behavior.** API cancel does not set `finished_at`
**[V]** (`jobs.py:858-866`). Cleanup selects `finished_at IS NOT NULL`
**[V]** (`scheduler.py:271-283`).

**Consequence.** Canceled queued jobs stay forever, with paths null and no
cleanup event. They accumulate in the list and the database.

**Mitigation.** Set `finished_at` on every terminal transition, or change
cleanup to select terminal status and use `COALESCE(finished_at, created_at)`.

### R-16 Token rotation race

**Verified behavior.** Each runner builds its own `TokenManager`
**[V]** (`runner.py:382-395`). On rotation it writes the encrypted access and
refresh tokens **[V]** (`runner.py:369-380`). There is no cross-process lock.
The comparison endpoint has a per-request `threading.Lock`
**[V]** (`comparisons.py:581-598`).

**Assumption.** Two jobs using the same credential refresh within the same
window; the slower writer persists an older refresh token. The other rotation
is lost.

**Consequence.** The credential can become invalid; every job using it fails
until an operator re-authorizes. This is a cross-customer outage if the
credential is shared.

**Mitigation.** Per-credential Redis/DB lock around refresh + persist, plus a
compare-and-swap on the token value. Retry the refresh once if the CAS fails.

### R-17 Retry leaves the group

**Verified behavior.** `retry_job` copies `created_by` and `rollup_of` but not
`group_id` **[V]** (`jobs.py:975-996`).

**Consequence.** Retrying a failed member of a group creates an ungrouped job.
The group still reports the old failure; the retry is invisible to the group.
The group retry endpoint does the right thing (new child group), but the job
page's Retry does not.

**Mitigation.** Copy `group_id` when the original is grouped, or make the job
page offer "retry in group" explicitly. Add a test for both paths.

### R-18 Preview promotion loses settings

**Verified behavior.** The client builds a new job with credential, index,
window, chunk size, phrases, IDs, exact phrases, message types, format, label,
customer, aggregation **[V]** (`jobs/[id]/page.tsx:93-113`). It omits
`group_id`, `s3_profile_id`, `exclude_phrases`, and
`exclude_exact_phrases` **[V]**.

**Consequence.** A preview created from a saved search with exclusions or S3
delivery promotes to a full job with different semantics. The operator sees a
different row count and no S3 upload.

**Mitigation.** Add a server-side promotion endpoint that clones the full
filter spec and ownership tags, with an idempotency key.

### R-19 S3 retry ambiguity

**Verified behavior.** The retry endpoint checks completed/non-preview/profile
and dispatches **[V]** (`jobs.py:488-507`). The task loads the job, uploads,
and writes the row **[V]** (`tasks.py:180-228`). There is no lock or attempt
state. A partial upload is `s3_error` + some URIs **[V]**
(`s3.py:127-179`).

**Consequence.** Two retries can run; the row's final `s3_error` and
`s3_uploaded_at` depend on the last writer. The UI badge says "failed" even
when the raw file uploaded.

**Mitigation.** Derive `s3_partial` explicitly; add an attempt marker or
advisory lock; clear the error when an attempt starts.

### R-20 Reaper false positive

**Verified behavior.** The reaper uses the newest `job_events.ts`, fallback
`started_at` **[V]** (`scheduler.py:216-248`). The heartbeat is every 300 s
inside the row loop **[V]** (`runner.py:653-664`). A single Last9 request can
retry for ~14 minutes without an event (`config.py:52-56`).

**Assumption.** A request retry chain longer than 60 minutes, or a blocked
write, can exceed the 60-minute threshold. The config comment says a request
can retry ~14 minutes, so a single call should not. Multiple sequential
retries or a wedged socket could.

**Consequence.** A live job is failed; the worker later writes `completed`
unconditionally (R-01/R-03), so the row may end in an inconsistent state. The
operator gets a false alert.

**Mitigation.** Heartbeat from a separate thread/timer, or extend the
threshold based on the maximum request chain. Fencing makes the late write
harmless.

### R-21 SSE duplicates

**Verified behavior.** The server initializes `last_event_id=0` per connection
**[V]** (`jobs.py:1167`). The client prepends every `event` message with no
dedupe **[V]** (`jobs/[id]/page.tsx:198-199`).

**Consequence.** A laptop sleep or VPN blip can duplicate the whole feed, up to
the 200-item cap. It looks like the job repeated work.

**Mitigation.** Honor `Last-Event-ID` (send the id in the SSE payload) or dedupe
by event id client-side.

### R-22 No status constraint

**Verified behavior.** `jobs.status` is `String(20)` with no check constraint
**[V]** (`models.py:48`; migrations add none). Any code path can write any
string.

**Consequence.** A typo or a future state becomes a row that no consumer
handles. It will render as an unknown badge and may never be claimed or
cleaned.

**Mitigation.** A `CHECK (status IN (...))` migration after the shared
vocabulary is in place. Add a schema validation test.

### R-23 Login throttle

**Verified behavior.** Redis failure returns 0 attempts, i.e. fail-open
**[V]** (`auth.py:72-82`). The key is per-email, fixed window
**[V]** (`auth.py:85-93`, `118-121`).

**Consequence.** A Redis outage removes brute-force protection. A distributed
attack across emails is not limited by IP.

**Mitigation.** Accept for an internal tool, or add an IP dimension and a
fail-closed mode for admin accounts. Document the trade-off.

### R-24 OAuth state replay

**Verified behavior.** State is a signed JWT with a nonce and 600 s expiry,
plus a cookie **[V]** (`auth.py:198-212`). The callback verifies both but does
not store a one-time nonce **[V]** (`auth.py:365-378`).

**Assumption.** Replay requires the attacker to have the victim's state cookie
and a valid code. The window is short.

**Mitigation.** A Redis one-time nonce (`SET NX EX 600`) if the threat model
requires it. Low priority for an internal tool.

### R-25 Health latches

**Verified behavior.** Breach and cooldown keys are Redis with TTLs
**[V]** (`health_monitor.py:159-175`). If Redis is down, `r=None`, so every
tick sends an alert **[V]**.

**Consequence.** Alert storm during a Redis outage; lost latch after a flush.

**Mitigation.** Accept, or add a process-local fallback latch. Do not make
health depend on the same Redis the product depends on without documenting it.

### R-26 Comparison crash visibility

**Verified behavior.** The run row is inserted after both sides finish
**[V]** (`comparisons.py:764-812`). A crash mid-request leaves no row.

**Consequence.** No record that an attempt happened; the UI cannot show
"running" or "interrupted".

**Mitigation.** Insert a `running` row first, commit, then update. Optional.

### R-27 Notification delivery

**Verified behavior.** Retries are in-memory; final failure is logged
**[V]** (`notifications.py:76-150`). There is no persisted attempt.

**Consequence.** A process crash loses the alert; a retry after a partial send
can duplicate it. The job outcome is unaffected, which is correct.

**Mitigation.** Persist an alert attempt only if delivery guarantees become a
requirement. Otherwise document best-effort.

### R-28 Low-disk unmatched path

**Verified behavior.** The emergency purge nulls output, summary, and counts,
but not `unmatched_file_path` **[V]** (`scheduler.py:352-367`).

**Consequence.** The detail page shows `has_unmatched` based on path existence
(single-job read checks existence, so it may correctly show false), while the
list shows path-presence true. A download link can 404.

**Mitigation.** Null all four paths in every purge path. Use one helper.

### R-29 `updated_at` is misleading

**Verified behavior.** The ORM has `onupdate=func.now()` **[V]**
(`models.py:93-95`). The worker uses Core updates **[V]**
(`db.py:185-186`), so `updated_at` does not move during a run. The scheduler
comment documents this **[V]** (`scheduler.py:202-204`).

**Consequence.** Any external dashboard or future code that uses `updated_at`
as liveness will be wrong.

**Mitigation.** Rename it in docs to "row updated by ORM", or add a trigger.
Use `job_events.ts` / `heartbeat_at` for liveness.

### R-30 Empty group

**Verified behavior.** `_group_status([])` returns `completed`
**[V, L]** (`groups.py:44-50`). Group creation requires at least one item and
creates jobs in the same transaction, so this is latent.

**Consequence.** Only if rows are deleted or a future endpoint creates an empty
group. It would show a completed group with zero jobs.

**Mitigation.** Return `none` or `queued` for an empty group. Low priority.

## 4. What is verified vs. what is not

### Verified in code

- All current transition writes and guards in the routes, runner, reaper,
  scheduler, rollup, groups, reports, token manager, auth, health, retention,
  and client pages cited above.
- The absence of a unique constraint on `(created_by, start_epoch)`.
- The absence of owner/lease/fencing columns.
- The absence of `completion_state` / `gap_*`.
- The vocabulary duplication.
- The retry/clone field omissions.
- The SSE reset to event id 0.

### Structural but not reproduced

- Cancel/complete and pause/resume races (R-01, R-02).
- Reclaim coexistence (R-03).
- Schedule duplicate insert under concurrent beats (R-07).
- Token rotation loss (R-16).
- Reaper false positive on a very long silent call (R-20).

These are tagged V-R and should be reproduced with integration tests before
being described as incidents.

### Assumptions

- Number of API/beat processes.
- Redis/Postgres topology.
- Real-world frequency of broker outages, Redis outages, and long retry
  chains.
- Whether any external consumer depends on `updated_at` or `last_run_at`.

### Explicitly not defects

- A preview being `completed` with capped rows. It is intentional; the
  discriminator is `is_preview`.
- Retention deleting files while the job stays `completed`. It is a file
  lifecycle; the defect would be presenting it as a job failure.
- S3 being additive; a completed job with a failed S3 copy is intentional.
- The 36-hour `missed` heuristic. It is a product choice; the risk is that it
  is the only signal.
- The synchronous comparison. It is a product choice; the missing `running`
  row is an observability gap, not a correctness bug.
- Fail-open login throttling. It is documented as deliberate.

## 5. Top five architectural risks

1. **No fencing on worker ownership** (R-02, R-03, R-04). Cancel, pause/resume,
   reclaim, and rollup can all produce two writers. This is the only class of
   defect that can silently corrupt the artifact and the counts while reporting
   success.
2. **"Completed" cannot express completeness** (R-09, R-10). Skipped ID
   batches and skipped rollup sources are invisible to every aggregate.
3. **Schedule truth is split between a cursor and job rows** (R-07, R-08,
   R-14). A failed or duplicate window is not represented in one place.
4. **Retry semantics contradict the recovery message** (R-05, R-17). A reaped
   job re-extracts from zero and may leave its group.
5. **Status vocabulary and derivation are duplicated** (R-11, R-12). Every
   future state change is a multi-file change with no compiler check, and
   groups/reports already disagree.

## 6. Recommended risk order

| Order | Risk | Why first |
|---|---|---|
| 1 | R-01/R-02/R-03/R-04 fencing and cancel dominance | Prevents silent data corruption; makes every later fix safe. |
| 2 | R-06 create/publish + R-07/R-08 schedule idempotency | Stops orphaned and duplicate work at the source. |
| 3 | R-09/R-10 completeness | Makes partial data visible before reporting changes. |
| 4 | R-05 retry semantics + R-17 group lineage | Aligns recovery behavior with what the UI promises. |
| 5 | R-11/R-12/R-13/R-14 shared derivation | Removes the reporting drift after the data is trustworthy. |
| 6 | R-16 token lock, R-19 S3 lock | Remaining concurrency fixes. |
| 7 | R-15/R-28 retention, R-21 SSE, R-22 constraint | Cleanup and polish. |
| 8 | R-23/R-24/R-25/R-26/R-27 | Security/observability trade-offs; document or defer. |
