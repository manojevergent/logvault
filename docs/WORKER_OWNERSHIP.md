# Worker Ownership

Status: design proposal for Release 1. Not implemented.
Companion: [`LEASE_AND_FENCING.md`](./LEASE_AND_FENCING.md) for exact schema
and SQL, and [`RELEASE_1_DESIGN.md`](./RELEASE_1_DESIGN.md) for scope.

Legend: **[V]** verified current behavior, **[P]** proposed, **[A]** unverified
assumption, **[D]** decision needed.

## 1. Goal and invariants

Release 1 must guarantee:

1. **One owner.** At most one worker may write a job's execution state,
   checkpoint, or artifacts at a time.
2. **No resurrection.** A terminal row never becomes `running` again.
3. **Cancel dominance.** A cancel request always ends `canceled`, never
   `completed`.
4. **Fence, not hope.** Permission is proven by a database condition on every
   write, not by a process-local flag or an event timestamp.
5. **Crash recovery.** A dead owner is replaceable; a live owner is not stolen.
6. **Artifact isolation.** A stale worker's local/S3 writes cannot corrupt the
   current attempt.

## 2. Ownership fields

| Field | Purpose | Written by |
|---|---|---|
| `owner_id` | Identifies the worker attempt (host/pid/task id) for logs and guards. | Claim, heartbeat |
| `lease_token` | Monotonic per-job fencing epoch. Every claim/reclaim/resume/reaper bump invalidates older writers. | Claim, resume, reaper |
| `lease_expires_at` | Authoritative expiry, based on the database clock. | Claim, heartbeat, clear on finalize |
| `heartbeat_at` | Last successful renewal, for operations and derived phase. | Heartbeat |
| `cancel_requested_at` | Distinguishes a cancel request from a terminal cancel. | API cancel |
| `pause_requested_at` | Distinguishes a pause request from an acknowledged pause. | API pause |

The token is **per job**, not global. A global sequence would add coordination
without protecting any additional resource: the job row, its local files, and
its S3 prefix are all scoped by job id.

`owner_id` format:

```
<hostname>:<pid>:<task-id-or-uuid8>
```

It is diagnostic; the token is the security boundary. Do not use the owner id
as the token.

## 3. Phases

The public `status` remains the existing six values. The operational phase is
derived:

| Phase | Representation | Owner | Allowed worker writes |
|---|---|---|---|
| Queued | `status='queued'` | none | none (only claim) |
| Claimed | `status='running'`, `owner_id` set, no progress | yes | progress/terminal |
| Running | `status='running'`, `owner_id` set, progress exists | yes | progress/terminal |
| Pausing | `status='paused'`, `pause_requested_at` set, owner set | yes | progress, pause-finalize, cancel-finalize |
| Paused | `status='paused'`, owner null | none | none until resume |
| Cancelling | `status='canceled'`, `cancel_requested_at` set, owner set | yes | progress, cancel-finalize |
| Cancelled | `status='canceled'`, owner null, `finished_at` set | none | none |
| Completed | `status='completed'`, owner null, `finished_at` set | none | none |
| Failed | `status='failed'`, owner null, `finished_at` set | none | none |

Notes:

- `claimed` is a phase, not a status. A UI can derive it from `status='running'
  AND started_at IS NOT NULL AND completed_chunks=0 AND rows_written=0`.
- `pausing`/`canceling` are derived from `owner_id IS NOT NULL`. They preserve
  the existing status vocabulary and API responses.
- Add `phase` and `is_finalizing` to `JobOut` (additive). `is_finalizing` is
  true while a paused/canceled row still has an owner. Withhold `download_url`
  while it is true.
- Internal guards use `pause_requested_at`/`cancel_requested_at` + owner +
  token; never `status` alone.
- A canceled row with an owner is *canceling*, not *cancelled*. This lets the
  worker write a consistent partial artifact before clearing the owner.
- A paused row with an owner is *pausing*. Resume can safely fence it.

## 4. Ownership acquisition

### 4.1 Claim

`run_job` acquires the lease once, before any job validation or file work. The
claim is a single conditional `UPDATE ... RETURNING`:

```
queued
  -> running (owner=me, token+1, lease=now+TTL, started_at=coalesce(started_at,now))

running with expired lease + redelivered
  -> running (owner=me, token+1, lease=now+TTL)
```

Everything else (terminal, paused, fresh running, running without redelivery)
returns 0 rows. The worker exits without writing.

Exact SQL and dialect notes: [`LEASE_AND_FENCING.md`](./LEASE_AND_FENCING.md)
section 3.

### 4.2 Why claim before validation

Current code loads the job and can write `failed` for a missing
credential/index before claiming **[V]** (`runner.py:201-214`). That write is
not fenced and can overwrite a cancel. The proposed order is:

1. Acquire the lease.
2. Load job, credential, index, checkpoint.
3. If validation fails, finalize `failed` (or `canceled` if a cancel was
   requested) under the lease.
4. Otherwise run.

If the claim fails, do nothing. The job is either owned, terminal, or paused.

### 4.3 Reclaim

Only a redelivered Celery task may reclaim, and only when the lease has
expired plus a grace:

```
status='running'
AND lease_expires_at < now() - reclaim_grace
AND redelivered=True
```

A live worker renews `lease_expires_at`; a fresh lease is never stolen, even if
the task is redelivered by the Redis broker. This is the key difference from
the current event-age check.

If a redelivered task arrives while the lease is still valid, it must **not**
just return and ack; if the original worker then dies, no message remains. The
task should schedule a bounded retry for the remaining lease time (see
[`OUTBOX_AND_DISPATCH.md`](./OUTBOX_AND_DISPATCH.md) section 6). If it returns
and acks, the reaper is the only recovery path.

## 5. Heartbeat

### 5.1 Thread

A daemon thread starts immediately after the claim and stops in `finally`.
It renews every `JOB_HEARTBEAT_SECONDS` (revised: 60 s):

```sql
UPDATE jobs
SET heartbeat_at = now(),
    lease_expires_at = now() + :ttl
WHERE id = :job_id
  AND owner_id = :owner
  AND lease_token = :token
  AND status IN ('running','paused','canceled');
```

The heartbeat is independent of the row loop, so a long HTTP retry, a large
`zipfile` write, or a slow S3 upload does not let the lease expire.

### 5.2 Progress-aware renewal

The heartbeat must not prove only that the process is alive. The main loop
updates an in-process `last_progress_at` when it writes rows or completes a
chunk/request. The heartbeat writes `progress_at=now()` only when that mark has
advanced; a heartbeat without progress does not move it. The persisted
`progress_at` is for NOC visibility and a reaper defense-in-depth.

The heartbeat renews only while:

```
now - last_progress_at <= JOB_PROGRESS_TIMEOUT_SECONDS
```

Recommended value: **3600 s**. A single Last9 request chain can be ~18 minutes,
and a chunk can contain multiple silent ID-batch retry chains. 1800 s is
acceptable only if runtime evidence shows no legitimate chunk is silent longer.
When the progress timeout is exceeded:

- stop renewing the lease;
- set `lease_lost`;
- let the main loop stop at the next row boundary.

A hung main loop with a live heartbeat thread therefore cannot hold the job
forever. Recovery is progress timeout + lease TTL + reaper grace
(about 71 minutes with 3600/600/60 settings).

### 5.3 Renewal is the only write allowed on an expired lease

Progress/terminal writes require `lease_expires_at > now()`. The heartbeat may
extend an expired lease if the token still matches, because no new owner has
claimed yet. This races safely with a claim:

- heartbeat wins -> lease extended -> claim's expiry predicate fails;
- claim wins -> token changes -> heartbeat's token predicate fails.

A heartbeat renewal after the progress timeout is not allowed; the lease must
expire so the reaper can recover.

### 5.4 Heartbeat failure

The heartbeat thread must not silently continue forever when the database is
unreachable:

- On a database error, retry with backoff.
- Track `last_successful_renewal` (monotonic).
- When `now - last_successful_renewal > lease_ttl - safety_margin` (e.g., 8 of
  10 minutes), set an in-process `lease_lost` event.
- The main row loop checks that event every row (cheap boolean) and aborts
  before writing more data.
- If the database recovers before the margin, renew and continue.

A worker that cannot prove ownership must stop writing, even if it can still
reach Last9.

### 5.5 On lost lease

When a heartbeat or progress write returns 0 rows:

1. Set `lease_lost`.
2. Stop reading new rows at the next row boundary (or immediately if possible).
3. Flush/close local files without publishing them.
4. Stop the heartbeat thread.
5. Return without writing a terminal status.
6. Do not upload S3.
7. Log `{job_id, owner, token, reason}` at warning.

The new owner (or reaper) decides the final state. The old attempt's files are
orphans and cleanup candidates.

## 6. Guarded writes

Every worker write is one of four classes.

### 6.1 Progress / checkpoint

Allowed source statuses: `running`, `paused`, `canceled` (the last two let the
worker persist a consistent final chunk while pausing/canceling). Required:
owner, token, `lease_expires_at > now()`. The update returns
`status`, `cancel_requested_at`, `pause_requested_at` so the worker can decide
to stop without a second query.

Writes:

- `completed_chunks`, `total_chunks`, `rows_written`,
  `current_chunk_start`, `checkpoint`, `preview`, `aggregation_result`;
- `output_file_path` / `store_path` when the attempt's artifact becomes the
  published pointer;
- the chunk event in the same transaction.

### 6.2 Pause finalization

Allowed source statuses: `running`, `paused`, `canceled` (cancel wins).
Required: owner, token, lease valid.

```
status = 'paused'
owner_id = NULL
lease_expires_at = NULL
heartbeat_at = now()  (last heartbeat, optional)
```

If `cancel_requested_at` is set, finalize `canceled` instead. A pause must never
override a cancel.

### 6.3 Terminal finalization

Allowed source statuses: `running`, `canceled` (canceled means a cancel request
landed; the worker is finalizing it). Required: owner, token, lease valid.

```
if cancel_requested_at is not null or status == 'canceled':
    final_status = 'canceled'
else:
    final_status = 'completed' or 'failed'
```

Set `finished_at`, `owner_id=NULL`, `lease_expires_at=NULL`, artifact pointers,
`completion_state`/`gap_count`/`gap_reason`, and the completion/error fields in
the same transaction as the terminal event. If the job has
`schedule_window_id`, update `schedule_windows` in that same transaction
(`completed`/`failed`/`canceled`, `last_error`, `next_attempt_at`).

Completion classification:

- `complete`: full window covered, no skipped ID batches, no rollup source
  skipped, no BQ rows dropped.
- `partial`: skipped batches, rollup skips, BQ drops, canceled work, or preview
  (`gap_reason='preview'`).
- `unknown`: failure before coverage is known, or legacy rows.

If the update affects 0 rows, re-read the row:

- if it is `paused` and the owner/token still match, run the pause finalize;
- if it is `canceled` and the owner/token still match, run the cancel finalize;
- if the owner/token changed, or the row is terminal, abort: do not publish
  S3, do not rename artifacts.

This handles a pause/cancel that lands between the last status check and the
terminal write without ever writing `completed` over `paused`/`canceled`.

### 6.4 Event write

Events are diagnostic but can mislead. Guard them with the same owner/token
condition using `INSERT ... SELECT ... WHERE EXISTS (SELECT 1 FROM jobs WHERE
id=:id AND owner_id=:owner AND lease_token=:token ...)`. If the event insert
affects 0 rows, treat it as a lost lease only if the surrounding operation
requires the event; otherwise log and continue. The chunk event must be in the
same transaction as the checkpoint, so it is atomic with the state.

## 7. Control operations

### 7.1 Pause

API:

```
UPDATE jobs
SET status='paused',
    pause_requested_at=now()
WHERE id=:id AND status IN ('queued','running')
RETURNING ...
```

- If `queued`: no owner exists; the job is paused and will not be claimed until
  resume.
- If `running`: the owner remains. The worker sees `paused` at its next status
  check, persists the current chunk, finalizes `paused`, and clears the owner.
- `pausing` = status paused + owner non-null.
- Do not bump the token on pause; the current worker must be able to persist
  the final chunk.

### 7.2 Resume

API:

```
UPDATE jobs
SET status='queued',
    pause_requested_at=NULL,
    owner_id=NULL,
    lease_expires_at=NULL,
    lease_token=lease_token + 1,
    finished_at=NULL,
    error_message=NULL
WHERE id=:id AND status='paused'
RETURNING ...
```

- Clearing the owner and bumping the token immediately fences a worker that has
  not yet acknowledged the pause.
- The new worker's claim increments again.
- If the worker is still writing, its next progress write fails (status queued /
  owner null / stale token) and it aborts.
- The new attempt starts from the checkpoint and seeds its artifact from the
  published prefix.

### 7.3 Cancel

API:

```
UPDATE jobs
SET status='canceled',
    cancel_requested_at=COALESCE(cancel_requested_at, now())
WHERE id=:id AND status NOT IN ('completed','failed','canceled')
RETURNING ...
```

- Do **not** clear the owner or bump the token for a running job. The owner must
  finalize the partial artifact.
- Any row with no owner (queued, fully paused, or a legacy running row) has
  nothing to finalize: set `finished_at=now()` and `owner_id=NULL` in the same
  update.
- With an owner (running or pausing), leave `finished_at` null. The worker or
  reaper sets it.
- `canceling` = status canceled + owner non-null.
- The worker's terminal write chooses `canceled` when `cancel_requested_at` is
  set or status is canceled. This is cancel dominance.
- A cancel grace (proposed 120 s) lets a stuck worker be force-finalized by the
  reaper: clear owner, bump token, copy the committed prefix to a recovered
  attempt path (or hide the pointer), set `finished_at`.

Why not bump the token immediately? It would prevent the current worker from
persisting the chunk it is in the middle of writing, leaving the published file
and the checkpoint inconsistent. Letting it finalize for a bounded grace
produces a consistent partial artifact. If it does not, the reaper fences it.

### 7.4 Group cancel

Group cancel currently loops over active children and writes `canceled` via the
ORM **[V]** (`groups.py:236-240`). It should apply the same per-job cancel
update (conditional, leave owner for running, set `finished_at` for queued) in
one transaction or one transaction per child with a summary. Do not use a bulk
ORM status write.

### 7.5 Retry

Retry creates a new row. It must not mutate the original. The new row starts
with `lease_token=0`, no owner, no lease. `retry_of` links it.

If D3 chooses resume, the new row copies the checkpoint (including
`artifact_path`/`store_path`) but not the published pointers. The runner seeds
from the checkpoint after validation. If it chooses restart, the checkpoint is
null and the reaper message/UI must say so.

## 8. Reaper

The reaper is a system actor, not an owner. It performs conditional transitions
only on rows whose lease has expired. The heartbeat stops renewing at the
progress timeout; the reaper does not need to inspect progress directly.

### 8.1 Running

```
status='running'
AND lease_expires_at < now() - :reaper_grace
```

`reaper_grace` is a short value (revised: 60 s), not the 60-minute progress
timeout. Once the lease is expired, recovery should not wait another hour.

Atomic update:

- if `cancel_requested_at` is set -> `canceled`, else `failed`;
- `owner_id=NULL`, `lease_expires_at=NULL`, `finished_at=now()`,
  `lease_token=lease_token+1`;
- `completion_state='unknown'` (or `partial` if a known gap existed);
- update `schedule_windows` to `failed`/`canceled` if linked;
- `error_message` for failed; a cancel-finalized message for canceled;
- event + scheduled alert in the same transaction.

The token bump fences any late worker. The reaper does not need a token because
it is the system transition; it proves the lease is expired by the `WHERE`
clause and affects 0 rows if another actor won.

### 8.2 Canceled with an owner

A cancel request may leave an owner while the worker finalizes. If
`status='canceled'`, `owner_id IS NOT NULL`, and
`cancel_requested_at < now() - cancel_grace` (or the lease is expired):

- copy the first `checkpoint.file_offset` bytes to a new "recovered" attempt
  path and publish it in a guarded update; if the copy fails, hide the pointer
  and record an error;
- clear owner, clear lease, bump token, set `finished_at`;
- keep `status='canceled'`;
- event: "Cancel finalized by reaper".

Do not truncate a file that a live worker may still be writing. The copy is the
safe way to publish a consistent partial artifact. The old file becomes an
orphan cleanup candidate.

This prevents a permanently "canceling" row.

### 8.3 Paused with an owner

If `status='paused'`, owner non-null, and
`pause_requested_at < now() - pause_grace` (or the lease is expired):

- clear owner, clear lease, bump token;
- keep `status='paused'`;
- event: "Paused worker released by reaper".

The job remains resumable.

### 8.4 Legacy fallback

During mixed versions, old workers do not write leases. The reaper can use the
old event-age rule behind `JOB_RECLAIM_MODE=event` until all workers are new.
Do not enable lease-based reaping while an old worker may own a row: it has no
token and cannot be fenced.

## 9. Rollup ownership

`run_rollup` currently bypasses the claim **[V]** (`rollup.py:85`). It must:

1. Receive the lease from `run_job` (same claim as extraction).
2. Use guarded progress writes for `completed_chunks`, `total_chunks`,
   `aggregation_result`.
3. Poll `cancel_requested_at`/`status` between source merges.
4. On cancel: stop, close the store, do not publish output, set `canceled`,
   `finished_at`, error "Rollup canceled"; clear owner.
5. On completion: publish attempt-scoped `store_path`, summary/counts/raw under
   the lease; set `completed`.
6. On source skip: keep `completed` in Release 1 but set `completion_state='partial'`,
   `gap_count`, and a warn event.
7. On fenced write: abort; do not publish.
8. Source selection for a scheduled window uses the successful attempt
   (`schedule_windows.current_job_id`), not every terminal retry.

Duplicate dispatch is safe because the second claim fails. Two rollups can
never write the same row; attempt-scoped paths prevent file overlap.

A retry of a rollup restarts the merge from its source list; `checkpoint` is not
a merge-resume cursor. Re-running a deterministic `merge_from` into a fresh
attempt store is idempotent and avoids partial-merge ambiguity.

## 10. Scenario walkthroughs

### A. Worker completes while cancellation is being requested

**Case A1 - completion commits first.**

- Worker terminal update matches `status='running'`, owner/token valid, no
  cancel request.
- Row becomes `completed`, owner null, `finished_at` set.
- Cancel API's conditional update requires status not in terminal; it affects 0
  rows and returns 409 (or reports already completed).
- Expected: `completed`. The cancel was too late. No data corruption.

**Case A2 - cancel commits first.**

- Cancel update sets `status='canceled'`, `cancel_requested_at`, leaves owner
  and token.
- Worker continues to its next safe boundary; its terminal update matches
  `status IN ('running','canceled')` and owner/token, but chooses `canceled`
  because `cancel_requested_at` is set.
- Row becomes `canceled`, owner null, `finished_at` set. Partial artifact is
  published.
- If the worker is stuck, the cancel grace/reaper clears the owner and sets
  `finished_at`; token bump fences the old worker.
- Expected: `canceled`, never `completed`.

**Case A3 - both updates race at the database.**

- Both are conditional updates on the same row; Postgres serializes them.
- If cancel's predicate (`status NOT IN terminal`) runs first, the worker's
  terminal predicate sees `canceled` and chooses canceled.
- If the worker's terminal predicate runs first, cancel sees `completed` and
  affects 0 rows.
- Expected: one of the two, with cancel winning whenever it committed before
  the terminal write. No `canceled -> completed`.

### B. Worker continues after its lease expires

- The worker's heartbeat stops or fails; `lease_expires_at` passes.
- The worker's next progress write requires `lease_expires_at > now()` and
  affects 0 rows. It aborts immediately.
- If it is between writes, it may still write local bytes to its attempt file;
  no DB pointer changes, and its files are orphaned.
- A redelivered task may claim after `lease_expires_at + grace`; token
  increments.
- The old worker's later writes fail the token/expiry guard.
- If no redelivery, the reaper fails/cancels after the progress timeout + lease
  expiry + reaper grace.
- Expected: the new owner or reaper is the only writer; old attempt files are
  ignored.

### C. Job is resumed before the previous worker exits

- Pause sets `status='paused'`, `pause_requested_at`, leaves owner.
- Resume sets `status='queued'`, clears owner/lease, bumps token.
- Old worker's next progress write sees `status='queued'` and a new token; it
  affects 0 rows and aborts.
- New worker claims `queued`, token increments again.
- The new attempt seeds from the last committed checkpoint and ignores bytes
  after `file_offset`.
- Expected: one writer; no duplicated rows beyond one replayed chunk; the old
  attempt file is orphaned.

### D. Rollup overlaps with another attempt

- Two `run_job` deliveries for the same rollup: the first claims; the second
  sees a fresh lease and no reclaim permission, exits/retries.
- If the lease expires and a redelivered task claims, token increments; the old
  rollup's merge writes fail and it aborts.
- Cancel during merge: status canceled + request; rollup checks between sources,
  stops, finalizes canceled, does not publish.
- Expected: one winner; canceled stays canceled; no duplicate output/store.

### E. Celery delivers the same task more than once

- First delivery claims `queued`; second sees `running` with a fresh lease.
  - Not redelivered: exit and ack. The original owns.
  - Redelivered: schedule a bounded retry for the remaining lease; do not
    claim a live lease.
- If both arrive while queued: the conditional claim makes exactly one win; the
  loser exits.
- If the first already reached terminal: second exits.
- If the first is dead and the lease expired: the redelivered task claims.
- Expected: at most one execution; duplicate messages are acked or retried
  without duplicate writes.

### F. Worker crashes during checkpoint persistence

Sequence in the runner:

1. Write rows to the attempt file.
2. `flush` + `fsync`.
3. Update job counters/checkpoint + insert chunk event in one DB transaction.
4. Continue.

Cases:

| Crash point | DB checkpoint | File | Recovery |
|---|---|---|---|
| Before fsync | old | partial bytes | New attempt copies only old `file_offset` bytes; replay chunk. |
| After fsync, before DB commit | old | complete chunk bytes | Copy old offset; replay chunk; extra bytes ignored. |
| During DB commit | old or new (atomic) | complete | If old, replay; if new, resume next. |
| After DB commit | new | complete | Resume next chunk; no replay. |
| During S3 upload | new | complete | Job completed; S3 retry/publish is separate. |

The chunk event is in the same transaction as the checkpoint. The attempt file
contains a committed prefix plus possibly an uncommitted suffix; the new
attempt reads exactly `file_offset` bytes.

Distinct store:

- If the store was flushed for a chunk but the DB checkpoint was not committed,
  the new attempt merges the previous store and preserves
  `last_chunk_committed`. The replay's `flush` sees the marker and drops
  duplicate occurrence counts. The CSV still gets the replayed rows.
- If the store is missing or unreadable, reset the checkpoint to zero and
  re-extract from the start; record an event. Do not resume aggregation with a
  partial store.

## 11. Code touchpoints

This table is the implementation checklist. Signatures are proposals, not
changes made in this task.

| File | Function | Required change |
|---|---|---|
| `worker/app/db.py` | table mirror | Add new columns to the Core `jobs` table. |
| `worker/app/db.py` | `claim_job` | Return a lease (`owner_id`, `lease_token`, `lease_expires_at`) and enforce expiry/redelivery. |
| `worker/app/db.py` | `update_job` | Keep for system/non-lease writes; add `update_job_owned` with rowcount. |
| `worker/app/db.py` | `current_status` | Add `read_lease_state` returning status/token/cancel/pause. |
| new `worker/app/lease.py` | - | `Lease` dataclass, `acquire`, `renew`, `update`, `finalize`, `add_event`, `LeaseLost`. |
| `worker/app/tasks.py` | `run_job` | `bind=True`; acquire lease once; pass to runner/rollup; bounded retry on live redelivery; guarded `_mark_failed`. |
| `worker/app/tasks.py` | `_mark_failed` | Fail `queued` conditionally without a lease; fail `running` only with a valid lease. |
| `worker/app/runner.py` | `run_extraction` | Accept lease; claim before validation; guarded progress/terminal writes; attempt paths; heartbeat. |
| `worker/app/runner.py` | `on_chunk` | Guarded update + event; `LeaseLost` on 0 rows; publish attempt path. |
| `worker/app/runner.py` | `_Stopped` paths | Finalize paused/canceled under the lease; cancel dominance. |
| `worker/app/rollup.py` | `run_rollup` | Accept lease; remove unconditional `running`; guarded writes; cancel/pause; attempt store/output. |
| `worker/app/scheduler.py` | `reap_stale_jobs` | Lease-based conditional updates; short reaper grace; cancel dominance; orphan owner cleanup; update schedule windows. |
| `worker/app/scheduler.py` | `cleanup_exports` | Use `store_path`; avoid deleting referenced attempt files. |
| `worker/app/scheduler.py` | `scan_schedules` | Use `schedule_windows` ledger, scan lock, outbox; retry failed/missing windows. |
| `api/app/models.py` | `Job` | Add fields, completion/gap, schedule window link, indexes. |
| `api/app/routers/jobs.py` | pause/resume/cancel/bulk | Conditional updates; resume bumps token/clears owner; cancel leaves owner for running; set `finished_at` for no-owner rows. |
| `api/app/routers/groups.py` | cancel/retry | Same per-job cancel semantics; preserve/copy `group_id`/lineage on retry; propagate partial. |
| `api/app/routers/reports.py` | report day | Use `completion_state=partial` and `schedule_windows` for missed/pending/failed. |
| `api/app/schemas.py` | `JobOut` | Add `phase`, `is_finalizing`, `completion_state`, `gap_count`, `gap_reason`; additive. |
| `web` | job pages | Consume phase/completion; gate download while finalizing. |

## 12. Failure modes

| Failure | Detection | Behavior |
|---|---|---|
| Worker killed -9 | Heartbeat stops; lease expires | Redelivery claims; reaper after 60 s grace. |
| Worker paused by OS | Heartbeat stops; lease expires | Old writes fenced; new owner. |
| Database down | Heartbeat/progress errors | Retry; stop before TTL margin; leave row for reclaim. |
| Broker down during create | Outbox pending | Dispatcher retries; no orphaned committed job. |
| Broker redelivers long job | `redelivered=True` | Fresh lease -> bounded retry; expired -> claim. |
| Heartbeat thread dies | No renewal | Progress writes stop at expiry; reaper/reclaim. |
| Main loop hung, heartbeat alive | No progress for 60 min | Heartbeat stops renewing; lease expires; reaper. |
| Hung process holds a slot | No progress; optional runtime limit | Soft/hard limit or accepted slot risk. |
| Clock skew | DB `now()` used | Avoids worker clock authority. |
| Token overflow | bigint | Not a practical concern. |
| Stale worker writes | 0-row update | Abort; orphan artifacts. |
| Cancel while worker stuck | Cancel grace | Reaper fences and copies the committed prefix or hides the partial pointer. |
| Pause while worker stuck | Resume bump | Old worker fenced; new claim. |
| Rollup duplicate | Claim | One owner. |
| Schedule window failed | Ledger status | Retry with backoff/cap; report failed/missed. |

## 13. Open decisions

- D1/D2: derived `phase`/`is_finalizing` while keeping immediate status, or
  persisted intermediate statuses. Recommendation: derived phase.
- D3: retry resume vs restart. Recommendation: resume only with validated
  checkpoint/artifact/store; otherwise restart.
- D8: lease timings. Recommendation: 600/60/60 + progress timeout 3600 +
  reaper grace 60.
- D9: task runtime limit. Recommendation: high soft/hard limit or explicit
  accepted stuck-slot risk.
- D10: minimum completeness. Recommendation: include in Release 1.
- D11: schedule ledger. Recommendation: include in Release 1.
- Download gating while `owner_id IS NOT NULL`: recommendation yes.
- Cancel grace duration: recommendation 120 s.
- Whether `owner_id` should be exposed in `JobOut` for support. Recommendation:
  expose only a boolean `is_finalizing`/`derived_phase`, not the raw owner.
