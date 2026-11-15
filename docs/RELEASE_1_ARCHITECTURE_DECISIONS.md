# Release 1 Architecture Decisions: Independent Challenge Review

Status: design review only. Nothing has been implemented. No source code,
schema, migration, API, dependency, or deployment configuration was changed.

This document challenges the original Release 1 design. It is the authoritative
record of what changed and why. The seven Release 1 documents have been revised
to match the decisions here.

Legend:

| Tag | Meaning |
|---|---|
| **[V]** | Verified in the repository or official documentation. |
| **[P]** | Proposed architecture, not implemented. |
| **[A]** | Assumption requiring verification. |
| **[D]** | Decision requiring approval. |

## 0. What changed after the challenge

The original design was directionally correct but too optimistic in five
places:

1. **Heartbeat liveness was treated as job liveness.** A hung process with a
   live heartbeat thread would renew its lease forever. The revised design adds
   a **progress-aware heartbeat**: renewal stops when the main execution loop
   has made no progress for `JOB_PROGRESS_TIMEOUT_SECONDS`.
2. **Completeness was deferred.** That would let Release 1 still report skipped
   ID batches and incomplete rollups as clean successful jobs. The revised
   design includes the minimum `completion_state`/`gap_count`/`gap_reason`
   fields and propagation to group/report status.
3. **Schedule recovery was deferred.** The unique index alone prevents
   duplicates but does not retry failed windows or track missing ones. The
   revised design adds a `schedule_windows` ledger.
4. **Cancellation/pause statuses were ambiguous.** Immediate `paused`/`canceled`
   while an owner still exists is compatible but ambiguous to consumers. The
   revised design keeps the immediate status for compatibility and adds a
   derived `phase`/`is_finalizing` API field; internal truth is the request
   timestamp plus owner.
5. **Celery timing was underspecified.** Celery 5.4/Redis defaults to a
   3600-second visibility timeout, and no task time limits are set. The revised
   design makes the visibility timeout explicit and requires a high hard/soft
   runtime limit or an accepted watchdog risk.

## 1. Re-evaluation of D1-D13

### D1 - Cancellation representation

**Original recommendation.** Keep `status='canceled'` immediately, set
`cancel_requested_at`, keep the owner until the worker finalizes or the cancel
grace expires. Derive `cancelling` from canceled + owner.

**Technical justification.** Preserves the existing API/UI response and lets the
current worker persist the chunk it is writing, so the published partial file
and checkpoint agree.

**Potential failures.**

- A consumer that reads only `status` sees `canceled` and assumes no worker or
  file writer is active.
- A consumer may mint a download link for a file that is still being appended.
- If the worker is hung, the row can remain "canceling" until the grace.
- A cancel that arrives after the worker's final write but before the API read
  returns 409, which is correct but can surprise the caller.

**Data-integrity implications.** Strong if the worker finalizes under the same
token and cancel dominance; weak if consumers trust `status` alone.

**Backward compatibility.** Excellent: the six statuses and response codes are
unchanged. Additive `phase`/`is_finalizing` fields are optional.

**Alternatives.**

1. **Separate request + execution phase (recommended).** Persist
   `cancel_requested_at`; keep `status`/owner; expose a derived `phase`
   (`canceling`/`canceled`). Internal guards never use `canceled` alone to mean
   "no writer".
2. **Explicit persisted `cancelling` status.** Clearer but expands the six-status
   vocabulary in 14+ places and still needs owner/request fields. Reject.
3. **Leave status `running` until the worker acknowledges.** Semantically
   cleanest but changes API/UI behavior and existing tests. Defer unless the
   product accepts the break.

**Final recommendation.** **Separate request and execution-phase fields.**
Keep immediate `status='canceled'` as a compatibility projection, but add
`phase='canceling'` while `owner_id IS NOT NULL`, and `is_finalizing=true`.
Internal writes use `cancel_requested_at` + owner + token, never `status` alone.
Download URLs are withheld while `is_finalizing` (or `owner_id` non-null).
**Requires modification.**

### D2 - Pause representation

**Original recommendation.** Keep `status='paused'` immediately, set
`pause_requested_at`, keep the owner until acknowledgment; derive `pausing`.

**Technical justification.** Preserves the API/UI response and lets the worker
finish and persist the current chunk.

**Potential failures.**

- `paused` can mean "requested but still writing" or "stopped".
- A resume issued before acknowledgment must fence the old worker; the original
  design does that with a token bump, but a consumer may not understand why a
  paused row has an owner.
- A pause at the terminal boundary must trigger pause finalize, not a completed
  write.

**Data-integrity implications.** Strong with token bump on resume and
pause-finalize guard; ambiguous only at the presentation layer.

**Backward compatibility.** Excellent. Additive `phase='pausing'` is optional.

**Alternatives.** Same three as D1. Explicit `pausing` status is clearer but
costly. Leaving status `running` until ack is cleaner but breaks current
behavior.

**Final recommendation.** Same as D1: keep immediate `paused` for compatibility,
add derived `phase='pausing'`, internal truth is `pause_requested_at` + owner.
Resume clears owner and bumps the token. **Requires modification.**

### D3 - Retry semantics

**Original recommendation.** Resume when a valid checkpoint + artifact exist;
otherwise restart and record why. Add `retry_of`.

**Technical justification.** The runbook and reaper message promise resume; the
current code restarts. Resume preserves work; restart avoids a corrupt/missing
artifact producing a tail-only file.

**Potential failures.**

- Checkpoint exists but the artifact is truncated, wrong, or zipped.
- Distinct store is missing or behind the checkpoint.
- Retry of a canceled job resumes a partial artifact that is not actually
  usable.
- Retry of a rollup mixes a merge checkpoint with a source list that changed.
- `retry_of` points to a job that was pruned/deleted.

**Data-integrity implications.** High. A tail-only file is worse than a clean
restart. The checkpoint validity rules in section 3.B are mandatory.

**Backward compatibility.** `retry_of` is additive. Behavior changes only when
`RETRY_MODE=resume`; old clients see a new job either way.

**Alternatives.**

1. Always restart (simple, honest, costly).
2. Always resume (cheap, unsafe without validation).
3. Resume only when validation passes, else restart with an event (recommended).

**Final recommendation.** **Resume only with a validated checkpoint + artifact +
store; otherwise restart from zero and record `retry_fallback_reason`.**
Rollup retries always restart the merge. Add `retry_of`. **Requires
modification** (the validation rules were not explicit enough).

### D4 - Attempt-scoped local artifacts

**Original recommendation.** Each attempt writes its own local path and seeds
from the committed prefix.

**Technical justification.** DB fencing cannot stop a stale process from
appending to a shared CSV. Unique paths are the only reliable isolation.

**Potential failures.**

- Cleanup deletes a referenced file.
- Resume copies the wrong prefix or a zipped file.
- Disk usage grows with orphan attempts.
- External consumers expect `job_<id>.csv`.

**Data-integrity implications.** Strongly positive; removes the local-file
corruption class.

**Backward compatibility.** API downloads use the DB path and computed filename;
old code reading `output_file_path` still works. External path consumers are the
only break.

**Alternatives.** Canonical path + token check before every write (still racy),
or a filesystem lock (not reliable across containers). Reject.

**Final recommendation.** **Approved.** Keep the attempt-scoped paths. Add
cleanup tests and document the path change. **Approved recommendation.**

### D5 - Attempt-scoped distinct store

**Original recommendation.** Add `jobs.store_path`; each attempt writes its own
store and merges the previous store while preserving the last-chunk marker.

**Technical justification.** A stale worker can corrupt a shared SQLite store.
Merging without the marker double-counts the chunk that was committed to the
store but not the DB checkpoint.

**Potential failures.**

- `merge_from` drops `last_chunk_committed`, causing double counts.
- SQLite is locked by a live old worker during merge.
- The store is missing/unreadable.
- Rollup/cleanup still reads the canonical path.

**Data-integrity implications.** Critical for aggregation correctness. The
marker-preservation detail is a hard requirement, not an optimization.

**Backward compatibility.** `store_path` is additive. Old rollup/cleanup cannot
read attempt stores; rollback needs a copy/link shim.

**Alternatives.** Keep canonical store + lease guard (racy); disable
aggregation resume (safe but re-extracts); copy the SQLite file (torn if live).
Reject the first and third.

**Final recommendation.** **Approved with mandatory marker-preservation tests.**
If the previous store is missing/unreadable, reset the checkpoint to zero and
re-extract; never resume with a partial store. **Requires modification**
(implementation detail is now explicit).

### D6 - Transactional outbox

**Original recommendation.** Outbox + inline fast path; at-least-once publish,
at-most-once execution via claim.

**Technical justification.** The current commit-then-publish gap leaves
committed jobs that may never run. The outbox makes intent durable and visible.

**Potential failures.**

- A committed job is never dispatched if the dispatcher is down (monitor/alert).
- A duplicate publish occurs after a crash before the mark (safe via claim).
- A lost HTTP response after create makes the client retry and create a second
  job. The outbox does not prevent duplicate *job creation*.
- Old API instances do not write outbox rows (reconciliation covers).

**Data-integrity implications.** Positive for execution; duplicate job creation
remains a user-level risk.

**Backward compatibility.** `DISPATCH_MODE=dual`/`direct` and the existing task
name keep old clients/instances working. Create returns 201 even if the inline
publish fails; this changes a 500 to a queued job.

**Alternatives.** Queued-job sweeper only (simpler, less audit); direct publish
(current, unsafe). Outbox is the best fit.

**Final recommendation.** **Approved.** Add a reconciliation task for queued
jobs without a live outbox row. **Create-idempotency (`Idempotency-Key`) is a
Release 2 item**; Release 1 acceptance is "no duplicate execution of the same
job", not "no duplicate job creation". **Approved recommendation** with a
documented residual.

### D7 - S3 publication

**Original recommendation.** Unique attempt prefix + DB pointer; manifest for
audit; no shared canonical key.

**Technical justification.** S3 PUT is atomic per object but there is no
multi-object transaction. A stale attempt can overwrite a shared key. The DB
pointer is the commit.

**Potential failures.**

- Upload succeeds, DB pointer update fails: orphan objects, no published state.
- DB pointer succeeds, manifest write fails: manifest is audit only; DB still
  points to the artifacts.
- A prior published attempt exists and a retry fails: must not label the job
  "not uploaded".
- Cleanup deletes the published prefix.
- External consumers expect a stable key.

**Data-integrity implications.** Strong if the DB pointer is the only source of
truth. Partial success must be explicit.

**Backward compatibility.** Existing `s3_uri` fields remain. New prefixes change
object listings. Old code reads `s3_uri` and ignores the new fields.

**Alternatives.** Stable canonical key with conditional writes (not universally
available); single manifest object at a stable key (stale writer race). Reject.

**Final recommendation.** **Approved.** Add `s3_published_with_error`; never
delete the published prefix; document the prefix layout for external consumers.
**Requires additional investigation** for S3-compatible storage listing/
multipart cleanup. **Approved recommendation** otherwise.

### D8 - Lease timing

**Original recommendation.** `LEASE_TTL=600s`, heartbeat `120s`, reclaim grace
`60s`, reaper at the existing `stale_job_minutes=60`.

**Technical justification.** Matches the current 10-minute reclaim threshold and
tolerates a long blocking call while the heartbeat thread runs.

**Potential failures.**

- Heartbeat thread keeps the lease alive while the main loop is hung; the job is
  never reaped. **This was a design defect.**
- A DB/network outage prevents renewal; the worker must stop before the TTL.
- A 60-minute reaper based on lease expiry plus another 60-minute grace delays
  recovery.
- Worker clock skew if lease comparisons use the worker clock.

**Data-integrity implications.** Critical. A lease without progress liveness can
hold a job forever; a lease that expires while a worker is alive can create a
second writer unless artifacts are attempt-scoped.

**Backward compatibility.** The values are settings, not API/schema changes. A
shorter TTL can expire live old-worker leases; keep the event fallback until all
workers are new.

**Alternatives.** Heartbeat-only liveness (rejected: hung jobs never reap);
event-age liveness (current; false positives on long silent retries); a
30-minute progress timeout (faster recovery, higher false-positive risk). The
recommended 60-minute progress timeout is conservative.

**Evidence:**

- Current runner status poll: 10 s **[V]** (`runner.py:57`).
- Current heartbeat event: 300 s **[V]** (`runner.py:503`).
- Current reclaim threshold: 10 min **[V]** (`config.py:56-60`).
- Current stale-job threshold: 60 min **[V]**.
- Last9 client: 10 attempts, 60 s HTTP timeout, exponential backoff capped at
  300 s; a single request chain can take roughly 18 minutes
  **[V]** (`client.py:58-72`, `197-198`; `runner.py:367`).
- DB engine: Postgres 16, default READ COMMITTED **[V/A]**.
- No worker-side DB clock skew handling; lease must use DB `now()`.

**Revised recommendation:**

| Setting | Value | Reason |
|---|---|---|
| `JOB_LEASE_TTL_SECONDS` | 600 | 10 min; matches current reclaim; tolerates 10 missed 60 s beats. |
| `JOB_HEARTBEAT_SECONDS` | **60** | More resilient to network/GIL delays than 120; negligible DB load. |
| `JOB_RECLAIM_GRACE_SECONDS` | 60 | Avoid stealing a lease that expired a moment ago. |
| `JOB_PROGRESS_TIMEOUT_SECONDS` | **1800-3600** | Stop renewing when the main loop has no progress; persist `progress_at` for NOC/reaper defense. Recommend 3600 to cover multiple sequential Last9 retry chains; 1800 is acceptable only with evidence that no legitimate chunk is silent longer. |
| `JOB_REAPER_GRACE_SECONDS` | **60** | Once the lease is expired, fail quickly; do not add another 60 min. |

Effective recovery:

- dead process: lease expiry 10 min + reaper grace 1 min = ~11 min;
- hung main loop with live heartbeat thread: progress timeout 60 min + lease
  expiry 10 min + reaper grace 1 min = ~71 min;
- DB outage: no renewal; the worker stops at the TTL margin; when the DB
  returns, another worker/reaper recovers.

**Final recommendation.** **Requires modification.** Add progress-aware heartbeat
and reaper grace; use DB time; document the 11-minute/71-minute recovery bounds.

### D9 - Celery and Redis reliability

**Original recommendation.** Treat duplicate delivery as normal; bounded
`self.retry`; keep the broker default visibility timeout.

**Technical justification.** Redis is the broker; long jobs will be redelivered
at the visibility timeout. The claim makes duplicates safe.

**Verified facts:**

- Celery 5.4.0, kombu 5.4.2, redis-py 5.2.1, Redis 7 image, Python 3.12
  **[V]** (`worker/requirements.txt`, `docker-compose.yml`).
- `task_acks_late=True`, `task_reject_on_worker_lost=True`,
  `worker_prefetch_multiplier=1`, `task_track_started=True`,
  `result_expires=3600` **[V]** (`celery_app.py:20-31`).
- No `broker_transport_options`, no `visibility_timeout`, no
  `task_time_limit`, no `task_soft_time_limit` **[V]**.
- Celery 5.4 Redis visibility timeout default is **3600 s (1 hour)**
  **[V]** (official Celery 5.4 Redis docs).
- No `task_acks_on_failure_or_timeout` override; default true.
- Redis has no `maxmemory`/eviction policy in compose; AOF is on
  **[V]** (`docker-compose.yml:20-31`).

**Potential failures.**

- A task longer than 1 hour is redelivered; the new task sees a live lease and
  must not steal.
- `self.retry` with an ETA longer than the visibility timeout loops; keep the
  countdown short.
- A hung task holds a worker slot forever; the reaper frees the row but not the
  process.
- `result_expires=3600` loses Celery result state for long jobs; the DB is the
  source of truth, but support tooling may be confused.
- Redis eviction under memory pressure can remove broker keys; use `noeviction`
  or sufficient memory.
- `task_reject_on_worker_lost` redelivers immediately; the lease may still be
  valid, so the duplicate must retry, not steal.

**Data-integrity implications.** Duplicate delivery is safe only if the claim is
the gate. A hung task can hold a slot, but not corrupt a row if the lease
progress timeout is enforced. Result expiry does not affect the DB.

**Backward compatibility.** Explicit visibility/result settings are
configuration-only. `ignore_result`/time limits change Celery introspection, not
the product API.

**Alternatives.** Increase visibility to 24 h (delays crash recovery; still
needs fencing); disable `acks_late` (loses redelivery); use RabbitMQ (new
infrastructure, rejected for Release 1).

**Revised recommendation:**

- Set `broker_transport_options={'visibility_timeout': 3600}` explicitly and
  `result_backend_transport_options={'visibility_timeout': 3600}` (or the same
  value) so a version change cannot silently alter behavior.
- On redelivered + live lease: bounded `self.retry(countdown<=300,
  max_retries=3)`; do not steal. On expired lease: claim.
- Keep `acks_late=True`, `task_reject_on_worker_lost=True`, prefetch 1.
- Add a configurable high hard/soft runtime limit for `run_job` (e.g.,
  soft 24 h, hard 25 h) **or** explicitly accept that a hung process can hold a
  slot indefinitely. A hard limit kills the child; the checkpoint resumes. A
  soft limit must be caught by the runner and leave a recoverable state. This is
  a **business decision**.
- Set `ignore_result=True` for `run_job` or raise `result_expires` to exceed the
  max job duration; the DB is authoritative. `task_track_started` is not needed
  for the product UI.
- Document Redis `noeviction` and memory headroom.

**Final recommendation.** **Requires additional investigation + business
decision** for time limits. The visibility timeout, retry bound, and
`ignore_result` changes are approved. **Not fully resolved until the max job
runtime is agreed.**

### D10 - Completion integrity

**Original recommendation.** Defer `completion_state`/`gap_count` to Release 2;
keep `error_message`/warn events.

**Technical justification.** Ownership and terminal correctness were considered
the Release 1 theme; completeness is orthogonal.

**Challenge.** This is too narrow. Release 1 can still:
- report `completed` after skipped ID batches;
- report `completed` after a rollup skipped a source store;
- report `completed` after BigQuery dropped unmatched rows;
- feed those results into group/report "success".

That directly conflicts with the objective "prevent partial results from being
reported as successful." Deferring it leaves a known data-integrity defect in
the release that claims state integrity.

**Minimum Release 1 additions:**

- `completion_state varchar(16) NOT NULL DEFAULT 'unknown'`
  (`unknown|complete|partial`).
- `gap_count integer NOT NULL DEFAULT 0`.
- `gap_reason text NULL`.
- Set `complete` only when: full window covered, no skipped ID batches, no
  rollup source skipped, no BQ rows dropped. Preview is `partial` with
  `gap_reason='preview'` and remains excluded from reports by ownership.
- Set `partial` for skipped batches, rollup skips, BQ drops, canceled jobs.
- Leave legacy rows `unknown`; do not guess beyond the unambiguous
  `error_message` skipped-batch pattern.
- Group: any child partial -> group `partial`.
- Report: any partial -> day `partial` (after failed/running, before ok).
- API: add fields to `JobOut`; add partial counts to group/report only if cheap.

**Data-integrity implications.** This is the minimum needed to stop partial
results from looking clean. It is more important than a richer gap taxonomy.

**Backward compatibility.** Additive fields; `unknown` for legacy; no new
terminal status; old clients ignore.

**Alternatives.** Defer all completeness (rejected: keeps incorrect success);
add a seventh terminal status (rejected: vocabulary fan-out); infer from
`error_message` only (rejected: fragile and rollup-invisible).

**Final recommendation.** **Requires modification: include the minimum
completeness fields in Release 1 (M1/M2).** Defer richer gap categories and
historical backfill beyond the unambiguous pattern to Release 2.

### D11 - Schedule recovery

**Original recommendation.** Keep the current "any existing job blocks the
window" policy; add only a unique window index.

**Technical justification.** The unique index prevents duplicate jobs for one
window with minimal schema change; the existing cursor/backfill logic was
considered sufficient for normal operation.

**Challenge.** This preserves the known failure: a failed or canceled scheduled
window is never retried automatically, and the cursor says the schedule ran.
A unique index prevents duplicates but does not track missing, failed, or
dispatch-failed obligations.

**Reliable approach: `schedule_windows` ledger.**

| Field | Purpose |
|---|---|
| `id` | Window identity. |
| `schedule_id` | Owner. |
| `window_key` | Stable identity: `day:YYYY-MM-DD` or `slot:<epoch>`. |
| `scheduled_for` | Due time for the slot. |
| `start_epoch`, `end_epoch` | Actual extraction window. |
| `status` | `pending`, `dispatched`, `running`, `completed`, `failed`, `canceled`. |
| `completion_state` | `unknown`, `complete`, `partial` for the winning attempt. |
| `attempts`, `max_attempts` | Retry policy. |
| `current_job_id` | Latest attempt. |
| `next_attempt_at` | Backoff/manual retry. |
| `last_error` | Dispatch/execution failure. |
| `config_snapshot` | Source/filter/format at window creation, so a retry is deterministic. |
| `created_at`, `updated_at` | Audit. |
| `UNIQUE (schedule_id, window_key)` | Duplicate prevention. |

- Beat computes owed windows and upserts ledger rows (`pending`), capped at 14.
- A window dispatcher creates one active job per window, sets
  `jobs.schedule_window_id` and `attempt_no`, and moves the window to
  `dispatched`.
- The worker's terminal write updates the window in the same transaction:
  `completed`, `failed`, or `canceled`; sets `last_error`/`next_attempt_at`.
- Failed/canceled windows are retried with capped attempts and backoff; manual
  retry resets a window; completed never retries.
- Missing windows are `pending` past due; dispatch failures remain `pending`
  with `last_error`.
- Backfill inserts pending rows oldest-first, capped.
- On first enable, seed ledger rows from existing scheduled jobs for the
  lookback/backfill range (map completed/failed/canceled, current_job_id) so the
  first ledger scan does not re-run a window that legacy code already covered.
- Reports use the ledger for missed/pending/failed and the job/window start for
  day attribution; rows come from the successful attempt only. Rollup source
  selection must also use the successful attempt per window, not every terminal
  job, or a retry would double-count a day.
- `last_run_at` remains a scan/dispatch cursor; success is derived from
  `schedule_windows.status='completed'`.

Schedule change policy:

- The window snapshots its extraction config in `config_snapshot`; editing a
  schedule affects future windows, not an in-flight/pending window's retry.
- Calendar-day windows use UTC (the code already uses UTC; the model comment
  mentioning IST is documentation drift). No DST handling is required for UTC.
- Interval schedules use a fixed `slot:<epoch>` identity even though the
  lookback window rolls; overlapping actual windows are expected and are not
  duplicate slots.
- Deleting a schedule marks pending/dispatched windows `canceled` and keeps
  terminal rows for audit; it does not delete job history. A worker that is
  already running may finish; its terminal update keeps the window auditable.
- A partial window is `completed` with `completion_state='partial'`; it is not
  auto-retried by default. Failed/canceled windows retry up to
  `max_attempts`; partial needs manual review or an explicit retry.

This is more schema than the unique index, but it is the minimum reliable
recovery model. If schedule recovery is not a Release 1 acceptance criterion,
D11 must be explicitly accepted as a known defect; the recommendation is to
include it.

**Data-integrity implications.** Prevents silent missing days and duplicate
backfill; makes retry explicit.

**Backward compatibility.** New table and nullable `jobs.schedule_window_id`;
legacy scheduled jobs have null and use the old report path. Mixed old/new beat
needs the scan lock and ledger.

**Alternatives.** Unique jobs index + no retry (rejected: known defect); reuse
the failed job in place (rejected: terminal lifecycle violation); a separate
job per retry without a ledger (rejected: no obligation/current status).
The ledger is the minimum reliable model.

**Final recommendation.** **Requires modification: add the schedule ledger; do
not rely on a unique jobs index alone.** This is a business-scope decision
because it expands Release 1.

### D12 - Beat singleton

**Original recommendation.** Mandate one beat; unique index as defense.

**Technical justification.** A single scheduler avoids duplicate scans with no
new infrastructure; the unique index is a correctness backstop if the mandate is
violated.

**Challenge.** A deployment can overlap an old `-B` worker and a new dedicated
beat. A crash can leave no beat until the orchestrator restarts. The mandate
alone is not an enforceable guarantee.

**Recommended approach:**

1. Run a **dedicated `celery beat` service**, one replica; remove `-B` from
   workers. Docker/systemd enforce one instance; `restart: unless-stopped`/
   `Restart=always` handles crash recovery.
2. Add a **scan lock** (`SET NX EX 90` in Redis, or a Postgres advisory lock)
   around `scan_schedules`/cleanup. If another beat holds it, skip.
3. Keep the `schedule_windows` unique key and outbox unique key as the
   correctness backstop; the lock is an efficiency/overlap guard.
4. During rollout, stop the old `-B` beat before enabling the ledger; an old
   beat does not acquire the scan lock and inserts jobs without ledger rows. The
   lock coordinates new beat instances; the ledger prevents duplicates among
   them.
5. Beat's local schedule file is not critical (the schedule is static in code);
   a lost file restarts the static schedule.

**Data-integrity implications.** Prevents duplicate scans/backfill and duplicate
cleanup events. The ledger/outbox prevent duplicate jobs even if the lock fails.

**Backward compatibility.** No API change; deployment change only.

**Alternatives.** Mandate one `-B` worker only (fragile under scaling); rely only
on task-level locks (works but leaves duplicate beat load); use a database-backed
scheduler (new complexity). Dedicated beat + scan lock is the simplest reliable
option.

**Final recommendation.** **Approved recommendation**, strengthened with the scan
lock. **Requires deployment approval.**

### D13 - Status CHECK constraint

**Original recommendation.** Add after a distinct-status audit, in hardening.

**Technical justification.** Prevents invalid status strings and catches future
drift.

**Potential failures.**

- A legacy value (typo/manual row) fails the migration.
- A future Release 2 state (if `completed_with_gaps` were added) would require a
  new migration; the design intentionally avoids a seventh status.
- Mixed old/new code both write the six statuses; safe if the audit is clean.

**Revised recommendation.**

- Preflight:
  `SELECT status, count(*) FROM jobs GROUP BY status;`
- If every value is in the six, add the CHECK in M8 (`0037`) after the audit;
  if not, stop and map/decide manually. Do not auto-delete.
- Add CHECKs for `completion_state` and `schedule_windows.status` at the same
  time.
- Do not add a strict `running => owner` constraint in the first rollout;
  legacy/mixed rows may violate it. Add later if desired.

**Data-integrity implications.** Positive; catches invalid writes. The real
protection is the transition guard, not the CHECK.

**Backward compatibility.** Safe for the six-status vocabulary; risky only for
unexpected historical values.

**Alternatives.** No CHECK (relies on application guards); CHECK in the first
migration (fails on legacy values); CHECK a future seventh status (requires a
migration). Audit-first is the balanced choice.

**Final recommendation.** **Approved recommendation after audit; requires
additional investigation of historical values.** Add the CHECK when the audit is
clean, preferably in M1, not as an afterthought.

## 2. Critical concerns

### A. Cancellation and pause semantics

**Does immediate status create ambiguity?** Yes, at the consumer boundary:
`status='paused'`/`canceled` can mean "requested but still executing" or
"finalized". The original design resolved it internally with `owner_id`,
`cancel_requested_at`, and `pause_requested_at`, but consumers that read only
`status` can still be wrong (downloads, reports, integrations).

**Comparison:**

| Approach | Clarity | Compatibility | Cost |
|---|---|---|---|
| Separate request fields + derived phase | High if `phase` is exposed; internal truth is unambiguous | High: status unchanged; fields additive | Low |
| Explicit persisted `pausing`/`cancelling` statuses | High, but adds two statuses to every set | Medium: breaks status maps/API vocabulary | Medium-High |
| Current derived-phase only | Medium: internal truth clear, external status ambiguous | High | Low |

**Recommendation.** Use **separate request fields + a derived `phase`**:

- Persist `pause_requested_at`, `cancel_requested_at`, `owner_id`.
- Keep the immediate `status` for compatibility.
- Add `phase` to `JobOut`: `queued|claimed|running|pausing|paused|canceling|canceled|completed|failed`.
- Add `is_finalizing` (`owner_id` non-null while paused/canceled).
- Withhold download URLs while `is_finalizing`.
- Internal guards use request timestamps + owner + token, never status alone.
- Do not add persisted `pausing`/`cancelling` statuses.

**Safest alternative if API break is acceptable:** leave `status='running'`
until the worker acknowledges pause/cancel, and expose the request flags. This
eliminates the ambiguity completely but changes the current UI/API contract; it
is a product decision.

### B. Checkpoint consistency

**Definition of a valid, recoverable checkpoint:**

1. The DB row has `checkpoint` with `completed_chunks >= 0`,
   `next_chunk_start` (if set) between `start_epoch` and `end_epoch`, and
   `file_offset >= 0`.
2. `artifact_path` (or legacy `output_file_path`) exists, is not a zip, and
   `file_offset <= file size`.
3. The artifact belongs to the same job and a prior/current attempt; the path is
   not another job's file.
4. The DB checkpoint is committed **after** the artifact was flushed and
   `fsync`ed. The DB commit is the recovery marker.
5. For aggregation, `store_path` exists and its `last_chunk_committed` is
   `>= completed_chunks - 1` (the store may be one chunk ahead). If it is behind
   or missing, the checkpoint is not recoverable for aggregation.
6. `completed_chunks` and `next_chunk_start` agree with the checkpoint's
   `chunk_hours`/adaptive history; do not trust one without the other.
7. A preview checkpoint is not resumable as a full run; `is_preview` is the
   discriminator.

**Chunk boundaries:**

- Chunks are non-overlapping `[start, end)`.
- `completed_chunks` is the index of the next chunk to run.
- The CSV `file_offset` is the byte position after the last committed chunk.
- The distinct-store marker is the last chunk whose values are committed.
- A replay of a chunk within the marker must drop occurrence counts, not rows.

**Crash cases:**

| Crash point | DB checkpoint | Artifact | Recovery |
|---|---|---|---|
| Before fsync | old | partial suffix | copy old offset; replay chunk |
| After fsync before DB commit | old | full chunk suffix | copy old offset; replay chunk; extra ignored |
| During DB commit | atomic old/new | full | old -> replay; new -> next |
| After DB commit | new | full | next chunk |
| Store flushed, DB not | old | full | merge store + preserve marker; replay rows, drop counts |
| DB committed, store behind | new | full | **invalid** for aggregation; restart from zero |
| Artifact missing/truncated | any | missing | reset checkpoint to zero; re-extract; warn |

**Retry vs restart:**

- Retry from checkpoint only after validation.
- If validation fails: set `checkpoint=NULL` (or zeroed), `completed_chunks=0`,
  `next_chunk_start=None`, `file_offset=0`, `gap_reason='checkpoint_invalid'`,
  and re-extract from `start_epoch`.
- Never resume at `next_chunk_start` with a new/empty file; that produces a
  tail-only artifact.
- Rollup retry always restarts the merge; its checkpoint is not a merge cursor.

**Required tests:** T10/T11, plus a store-behind test and a zipped-artifact test.

### C. Lease timing

See D8. Key evidence:

- Last9 request chain can be ~18 min; current reaper threshold is 60 min.
- Current heartbeat event is 300 s; proposed dedicated heartbeat 60 s.
- Lease TTL 600 s tolerates 10 missed beats.
- Progress-aware timeout 3600 s (recommended) covers multiple silent retry
  chains; 1800 s only if runtime evidence shows no legitimate chunk is silent
  that long.
- Reaper grace 60 s after lease expiry; do not reuse the 60-minute stale
  threshold as a second grace.

**DB/network interruption:** heartbeat renewal fails; the worker must stop at
`lease_ttl - safety_margin` (e.g., 8 min) and not write further. The DB row
remains `running` until lease expiry; another worker/reaper recovers. Attempt
paths prevent local corruption.

**Delayed heartbeat:** 60 s interval, 600 s TTL; up to 9 missed intervals. A
GIL-blocked heartbeat thread for >600 s is not recoverable in-process; the lease
expires and the old worker must be fenced on its next DB write. Attempt paths
protect files.

### D. Celery and Redis reliability

See D9. Verified versions and settings are in section 1.D9. Revised settings:

```python
broker_transport_options = {"visibility_timeout": 3600}
result_backend_transport_options = {"visibility_timeout": 3600}
task_acks_late = True
task_reject_on_worker_lost = True
worker_prefetch_multiplier = 1
task_acks_on_failure_or_timeout = True
```

- Keep the visibility timeout explicit; default is 3600 in Celery 5.4.
- Redelivery is normal for jobs >1 h. The claim/token makes it safe.
- `self.retry` countdown <= 300 to stay under visibility; max 3.
- Add a high soft/hard runtime limit or accept the stuck-slot risk. Recommended:
  configurable, default soft 24 h/hard 25 h, `ignore_result=True` for `run_job`.
  This is a business decision.
- `result_expires=3600` is shorter than long jobs; either ignore results or
  increase. The DB is authoritative.
- Redis: `noeviction`, enough memory, AOF on. If Redis evicts broker keys, jobs
  can be lost; outbox reconciliation helps queued jobs, not running ones.

### E. Completion integrity

Minimum Release 1 fields and rules are in D10. The key acceptance criterion:

> No `completed` job with a known gap may be reported as `complete`; group and
> report statuses must expose `partial`.

Legacy rows are `unknown` and are not silently labeled complete. Backfill only
the unambiguous skipped-batch `error_message`; do not guess rollups.

### F. Schedule recovery

The `schedule_windows` ledger in D11 is the recommendation. Minimum behavior:

- **Failed/Missing:** retry with capped attempts/backoff; manual reset; report
  `failed`/`missed` based on the ledger.
- **Duplicate:** unique `(schedule_id, window_key)`; one active job per window.
- **Backfill:** upsert pending windows, oldest first, cap 14.
- **Dispatch failure:** window remains pending with `last_error`; outbox/reconcile
  retries; no silent success.
- **Success:** `completed` + `current_job_id` + completed_at; `last_success_at`
  derived.
- **Retry:** new job attempt, same window; `jobs.schedule_window_id`/`attempt_no`.
- **Report:** day from window start; rows from the successful attempt; partial
  completion propagated.

If the ledger is too large for Release 1, explicitly accept the current
failed-window defect and move D11 to Release 2; do not claim schedule recovery
is fixed by the unique index alone.

### G. Beat singleton

Recommendation in D12:

- Dedicated single `celery beat` service; workers without `-B`.
- Scan lock (`SET NX EX 90` or advisory lock) around `scan_schedules` and
  cleanup.
- Ledger/outbox unique keys are the correctness backstop.
- Rollout overlap is safe with the lock + ledger; remove `-B` after cutover.
- Crash recovery is orchestrator restart; missed scans are caught by owed
  windows/backfill.

### H. Database constraints

Recommendation in D13:

- Audit statuses before the CHECK.
- Add CHECKs for `jobs.status`, `completion_state`,
  `schedule_windows.status` when the audit is clean.
- Do not add `running => owner` strictness in the first rollout.
- The six-status vocabulary is unchanged, so mixed old/new writers are
  compatible with the CHECK.
- A future state requires a migration; the design intentionally avoids a
  seventh status.

## 3. Failure-mode analysis

| # | Scenario | Expected behavior | Possible failure | Recovery | Required test | Pass? |
|---|---|---|---|---|---|---|
| 1 | Crash after claim, before starting | Claim sets running/owner/token; heartbeat stops; lease expires; redelivery/reaper recovers | Job appears running for up to ~11 min; progress timeout may extend if heartbeat thread survives | Redelivery after grace; reaper; retry | T6, T19 | **Pass with caveat** (recovery time bound) |
| 2 | Crash during extraction | Resume from last committed checkpoint; replay at most one chunk | Invalid checkpoint/artifact -> tail-only file | Validate; reset to zero; re-extract | T6, T10 | **Pass** |
| 3 | DB connectivity lost, worker continues | Heartbeat/progress fail; worker stops at TTL margin; old writes fenced | Local writes continue until next DB write; uncommitted suffix | Attempt paths; new attempt seeds committed prefix; orphan cleanup | T3, T19b | **Pass with caveat** (progress timeout, local orphans) |
| 4 | Worker A resumes after B reclaims | A's token stale; all DB writes 0 rows; no S3 publication | A writes local file/orphan | Attempt paths; cleanup | T2, T3 | **Pass** |
| 5 | Cancellation during finalization | Cancel first -> canceled; completion first -> completed, cancel 409 | `canceled` overwritten by completion if guard missing | Cancel dominance + token/status guard | T4 | **Pass** |
| 6 | Pause during a chunk write | Pause sets paused; chunk checkpoint allowed; worker finalizes paused | Terminal write races pause | Re-read; pause finalize; no completed overwrite | T5, T5c | **Pass** |
| 7 | S3 succeeds, DB publication fails | Objects under unique prefix; DB pointer unchanged; orphan/retry | Objects look current to external lister | DB pointer source of truth; cleanup; retry | T9 | **Pass with caveat** (external listing) |
| 8 | DB publication succeeds, API response fails | Job/outbox committed and runs | Client retries, creates duplicate job | Outbox ensures execution; manual dedupe; idempotency key deferred | T14 | **Partial** (duplicate creation risk) |
| 9 | Redis redelivers long task | Live lease -> bounded retry; expired -> claim; terminal -> exit | Retry loop/ETA > visibility | Countdown <=300; max 3; claim | T8 | **Pass** |
| 10 | Beat crashes after dispatching schedule | Job/outbox committed; ledger records; next scan sees state | Crash before commit -> window retried | Ledger unique; outbox; restart | T12 | **Pass with ledger** |
| 11 | Two beats simultaneously | Scan lock lets one scan; ledger unique prevents duplicate jobs | Lock expiry/overlap | Unique ledger/outbox; lock TTL | T12 | **Pass with lock** |
| 12 | Retry with incomplete checkpoint | Validation fails -> restart from zero with event | Tail-only file | Checkpoint validity rules | T21 | **Pass** |
| 13 | Old and new workers simultaneously | New worker fences itself; old ignores tokens | Old worker overwrites cancel/completion | Deployment gates: observe, drain, enforce; no mixed enforcement | T26 | **Fail if mis-sequenced; pass only under deployment gates** |
| 14 | Crash after artifact, before completion | Artifact attempt-scoped; DB pointer not published; new attempt resumes/restarts | Complete artifact orphaned/reworked | Checkpoint/lease; orphan cleanup | T10, T22 | **Pass with rework** |

## 4. Decision register

| ID | Original Decision | Revised Decision | Reason | Risk | Approval |
|---|---|---|---|---|---|
| D1 | Immediate canceled + owner + derived canceling | Keep immediate status; add derived `phase`/`is_finalizing`; internal truth request+owner | Consumer ambiguity; preserve compatibility | Medium | **Requires modification** |
| D2 | Immediate paused + owner + derived pausing | Same as D1 | Same | Medium | **Requires modification** |
| D3 | Resume valid checkpoint, else restart | Same, with explicit validity rules; rollup always restarts | Prevent tail-only file | High if invalid | **Requires modification** |
| D4 | Attempt-scoped local paths | Approved | DB fencing cannot protect shared files | Medium | **Approved recommendation** |
| D5 | Attempt-scoped store + `store_path` | Approved with mandatory marker preservation; reset on invalid store | Double-count/torn store risk | High if marker lost | **Requires modification** |
| D6 | Outbox + inline fast path | Approved; add reconciliation; create idempotency deferred | Commit/publish gap | Medium | **Approved recommendation** |
| D7 | Unique S3 prefix + DB pointer | Approved; add `s3_published_with_error`; cleanup/listing investigation | No multi-object transaction | Medium | **Approved recommendation / investigation** |
| D8 | 600/120/60, reaper at stale 60 | 600/60/60 + progress timeout 3600 + reaper grace 60 | Heartbeat alone holds hung jobs forever | High | **Requires modification** |
| D9 | Treat duplicates; broker default | Explicit visibility 3600; retry bound; time-limit decision; ignore_result | Long jobs/hung slots/result expiry | High | **Requires investigation + business decision** |
| D10 | Defer completeness | Include `completion_state`/gap fields + group/report partial | Partial reported as success | High | **Requires modification** |
| D11 | Unique index only | Add `schedule_windows` ledger + retries/backfill/success | Failed/missing windows never recover | High | **Requires modification / business scope** |
| D12 | Mandate one beat | Dedicated beat + scan lock + ledger/outbox backstop | Overlap/crash | Medium | **Approved recommendation** |
| D13 | Status CHECK after audit | Add jobs/completion/schedule status checks if audit clean; no strict owner check | Legacy values; mixed versions | Medium | **Requires investigation** |

## 5. Final recommendation

### 5.1 Final recommended architecture

- Per-job lease (`owner_id`, `lease_token`, `lease_expires_at`,
  `heartbeat_at`) with DB-time comparisons and guarded writes.
- Request timestamps (`pause_requested_at`, `cancel_requested_at`) plus a
  derived `phase`/`is_finalizing` API field; immediate status for compatibility,
  internal truth from request + owner.
- Progress-aware heartbeat: renew only while the main loop is making progress;
  stop at `JOB_PROGRESS_TIMEOUT_SECONDS`; reaper grace after lease expiry.
- Attempt-scoped local CSV/summary/counts/unmatched and distinct stores; DB
  pointers are publication commits; checkpoint validation before resume.
- Attempt-scoped S3 prefixes + manifest + `s3_published_attempt`; DB pointer is
  the commit; cleanup never deletes the published attempt.
- Transactional outbox + inline fast path + queued-job reconciliation; duplicate
  Celery delivery safe via claim.
- Minimum completeness fields and group/report `partial` propagation in
  Release 1.
- `schedule_windows` ledger for failed/missing/duplicate/backfill/retry/success.
- Dedicated single beat + scan lock; ledger/outbox unique keys as backstop.
- Explicit Celery/Redis settings; high runtime limit or accepted stuck-slot risk.

### 5.2 Decisions that must be approved before implementation

1. D1/D2: derived `phase`/`is_finalizing` and download gating.
2. D3: resume only with validated checkpoint/artifact/store; rollup restarts.
3. D5: `store_path` and marker-preservation semantics.
4. D8: 600/60/60 + progress timeout 3600 + reaper grace 60.
5. D9: visibility timeout, retry bound, result handling, and the soft/hard
   runtime limit business decision.
6. D10: include minimum completeness in Release 1.
7. D11: include the schedule ledger or explicitly accept the failed-window
   defect.
8. D12: dedicated beat + scan lock.
9. D13: status/completion/schedule CHECK timing.

### 5.3 Technical questions still requiring investigation

- Confirm production Redis `visibility_timeout` and eviction/AOF settings.
- Confirm Postgres isolation/read behavior in the deployed environment.
- Confirm exports volume filesystem semantics.
- Confirm S3-compatible listing/multipart cleanup and whether conditional writes
  are available.
- Determine the maximum legitimate job runtime for soft/hard limits.
- Confirm no external consumer depends on the exact local/S3 path.
- Measure the longest silent period in a real chunk (ID batches, retries) to
  choose 1800 vs 3600 progress timeout.
- Confirm Celery `self.retry` ETA behavior under Redis 5.4/5.2.1.

### 5.4 Minimum Release 1 scope

- M1 lease/fencing + request fields + progress-aware heartbeat + minimum
  completeness.
- M2 attempt-scoped artifacts/stores + checkpoint validation.
- M3 rollup through the lifecycle.
- M4 outbox + dispatcher.
- M5 schedule ledger + dedicated beat.
- M6 S3 attempt publication.
- M7 retry consistency.
- M8 tests, deployment, status constraints, monitoring, rollback.

### 5.5 Safe Release 2 items

- Create-idempotency keys for HTTP requests.
- Richer completeness taxonomy and historical backfill.
- Per-credential token refresh lock/CAS.
- Login/OAuth/health/notification hardening.
- Comparison `running` persistence.
- Preview promotion lineage and group/report UX overhaul.
- Notification delivery persistence.
- State-machine library (still not recommended).

### 5.6 Implementation sequence

1. Approve D1-D13 revised decisions.
2. Preflight audits (status, duplicate windows, backups, Redis/Postgres/S3).
3. M1 schema + worker lease + API control/phase + completeness.
4. M2 artifacts/stores/checkpoint validation.
5. M3 rollup.
6. M4 outbox/dispatcher.
7. M5 schedule ledger + beat singleton.
8. M6 S3 publication.
9. M7 retry.
10. M8 status constraints, chaos, rollout, rollback rehearsal.

### 5.7 Production acceptance criteria

- No two workers can write one job; stale tokens affect 0 rows.
- Cancel always wins over completion; pause/resume cannot create a second
  writer.
- A 0-row guarded write aborts the worker and never publishes S3.
- A crash at any checkpoint step resumes with at most one chunk replay and no
  duplicate/missing committed rows.
- No `completed` job with a known gap is reported as `complete`; group/report
  show `partial`.
- One `schedule_windows` row and one active job per window; failed/missing
  windows retry or are explicitly reported.
- Outbox guarantees eventual dispatch; duplicate messages execute once.
- One published S3 attempt per job; cleanup never deletes it.
- Mixed-version deployment gates are followed; enforcement is never on while an
  old worker owns a job.
- Rollback restores the previous safety level without dropping columns or
  deleting attempt stores.
- Alerts exist for fenced writes, expired leases, pending/failed outbox, stuck
  canceling, and S3 publish mismatches.

## 6. Approval checklist

- [ ] D1/D2: derived phase + immediate status + download gating.
- [ ] D3: resume-vs-restart rules.
- [ ] D5: `store_path` marker preservation.
- [ ] D8: lease/progress/reaper timings.
- [ ] D9: Celery visibility/retry/result/time-limit decision.
- [ ] D10: minimum completeness in Release 1.
- [ ] D11: schedule ledger in Release 1 (or explicit accepted defect).
- [ ] D12: dedicated beat + scan lock.
- [ ] D13: CHECK constraint timing.
- [ ] Confirm the minimum scope and implementation sequence.
- [ ] Confirm no implementation starts before explicit approval.

## 7. Stop point

This is the end of the challenge review. No source code, schema, migration, API,
dependency, or deployment change has been made. Implementation must wait for
explicit approval.
