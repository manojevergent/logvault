# Release 1 Test Plan

Status: design proposal. Tests are not implemented in this task.

Companion: [`RELEASE_1_DESIGN.md`](./RELEASE_1_DESIGN.md),
[`WORKER_OWNERSHIP.md`](./WORKER_OWNERSHIP.md),
[`LEASE_AND_FENCING.md`](./LEASE_AND_FENCING.md),
[`ARTIFACT_PUBLICATION.md`](./ARTIFACT_PUBLICATION.md),
[`OUTBOX_AND_DISPATCH.md`](./OUTBOX_AND_DISPATCH.md).

Legend: **[V]** verified current behavior, **[P]** proposed, **[A]** unverified
assumption, **[D]** decision needed.

## 1. Goals

Prove, with executable tests, that:

1. Exactly one owner can claim a job.
2. Every stale/foreign write affects 0 rows and the worker aborts.
3. Cancel always wins over completion.
4. Pause/resume cannot create two writers.
5. A crash at any checkpoint step resumes without duplicate or missing rows.
6. A rollup cannot bypass the lifecycle.
7. Duplicate Celery delivery cannot execute twice.
8. Concurrent S3 attempts cannot publish over each other.
9. A committed job is eventually dispatched despite broker/API failure.
10. A schedule window cannot be inserted twice.
11. Existing API/UI behavior remains compatible.

## 2. Test infrastructure

### 2.1 Current state

- API tests use in-memory SQLite and `TestClient` **[V]**
  (`api/tests/conftest.py`).
- Worker tests force a SQLite file and recreate the Core tables **[V]**
  (`worker/tests/conftest.py`).
- There are existing claim/reclaim tests on SQLite **[V]**
  (`worker/tests/test_runner.py:142-258`), but they are sequential, not true
  concurrent writers.
- No worker service, Redis, or Postgres is required for the current suite
  **[V]**.

### 2.2 Proposed profiles

| Profile | Database | Use |
|---|---|---|
| `unit` | SQLite | Serialization, SQL shape, state derivation, API compatibility. |
| `pg` | Postgres test database | Claims, fencing, cancel/pause races, reaper, outbox locks, schedule ledger. |
| `broker` | Celery eager or a test broker | Duplicate delivery, retry decision, outbox publish. |
| `fs` | Temp directory | Attempt paths, checkpoint copy, store merge, cleanup. |
| `s3` | Fake boto3 client | Attempt keys, manifest, publication fence, cleanup. |

Do not add a new test dependency. Use the existing SQLAlchemy/psycopg stack and
pytest. A Postgres test database can be created from `TEST_DATABASE_URL`; guard
it with a name assertion, mirroring the worker conftest's safety check.

### 2.3 Postgres fixture requirements

- Create a dedicated database/schema, never the application database.
- Run `Base.metadata.create_all` or Alembic `upgrade head`.
- Provide two independent engines/sessions.
- Use `threading.Barrier` to align two operations.
- Set short statement/lock timeouts so a deadlock fails the test instead of
  hanging.
- Roll back/truncate between tests.
- Do not use sleeps to simulate lease expiry; set `lease_expires_at` to the
  past directly.

### 2.4 Fault injection

Use `monkeypatch` and small hooks, not a new framework:

- `fail_after_file_fsync`, `fail_before_checkpoint_commit`,
  `fail_after_checkpoint_commit` in the runner's chunk hook;
- a fake `Lease` with a controlled token;
- a fake `current_task.request.redelivered`;
- a fake `send_task` that raises or records calls;
- a fake S3 client that records keys and can fail selected artifacts;
- a fake clock only for display fields; lease predicates use DB time.

### 2.5 Test data

A helper creates:

- credential id 1, index target id 1;
- a queued job with a 2-chunk window, no preview;
- a completed source job with a distinct store for rollup tests;
- a schedule with `last_run_at` in the past.

## 3. Test matrix

### T1 - Concurrent worker claims

**Setup:** one `queued` job; two Postgres sessions; a barrier.

**Action:** both run the claim SQL with different owners.

**Expected:**

- exactly one returns a lease;
- the row has one `owner_id`, one `lease_token`;
- the loser returns 0 rows and performs no write;
- `started_at` is set once.

**Acceptance:** `won == 1`, `lost == 1`, `lease_token == 1`.

### T2 - Fencing-token enforcement

**Setup:** claim with token 1; then claim/reclaim with token 2 (simulate resume
or reaper).

**Action:** the token-1 worker attempts each write class: progress, checkpoint,
pause-finalize, terminal-finalize, event.

**Expected:** every write affects 0 rows; the row only reflects token 2.

**Acceptance:** no field changes from token 1; the worker raises `LeaseLost`
for progress/terminal and stops.

### T3 - Stale worker writes after lease expiry

**Setup:** claim; set `lease_expires_at` to the past; do not bump the token.

**Action:** progress and terminal writes.

**Expected:** both affect 0 rows because of `lease_expires_at > now()`; a
heartbeat renewal would be allowed but is not attempted.

**Acceptance:** the row stays `running` with the old token until a new claim or
reaper; no checkpoint/terminal change.

### T4 - Cancellation races

#### T4a - Cancel commits first

**Setup:** running job with token 1, owner A.

**Action:** API cancel sets `canceled`/`cancel_requested_at` but leaves owner;
worker terminal write executes with token 1 and `final_status='completed'`.

**Expected:** terminal SQL chooses `canceled`; owner cleared; `finished_at` set;
partial artifact pointer kept.

**Acceptance:** final status `canceled`, never `completed`.

#### T4b - Completion commits first

**Setup:** running job.

**Action:** worker terminal write commits `completed`; API cancel executes.

**Expected:** cancel affects 0 rows; 409/“already completed”.

**Acceptance:** final `completed`; no cancel overwrite.

#### T4c - Simultaneous

**Setup:** two threads, barrier.

**Action:** cancel and terminal write concurrently.

**Expected:** Postgres serializes; final is either `completed` (if completion
committed first) or `canceled` (if cancel committed first). `canceled ->
completed` never occurs.

**Acceptance:** run 100 iterations; no `canceled` row ends `completed`.

#### T4d - Cancel while queued

**Action:** cancel a queued job.

**Expected:** `canceled`, `finished_at` set, owner null, no lease.

**Acceptance:** a later claim returns 0 rows; retention can select it.

### T5 - Pause/resume race

**Setup:** running job with owner A; pause sets `paused`/`pause_requested_at`;
resume sets `queued`, owner null, token + 1.

**Action:** A's progress write after resume; then a new claim.

**Expected:**

- A's write affects 0 rows (status queued/owner null/stale token);
- the new claim succeeds with a newer token;
- only the new worker writes;
- the checkpoint is unchanged except for committed chunks.

**Acceptance:** one writer; no duplicated rows beyond one replayed chunk.

#### T5b - Pause acknowledgment

**Action:** worker pauses, finalizes `paused`, clears owner/lease.

**Expected:** status paused, owner null, `pause_requested_at` retained; resume
claims cleanly.

#### T5c - Pause at the terminal boundary

**Setup:** worker reaches the final write; pause commits just before it.

**Action:** terminal `completed` update affects 0 rows because status is
`paused`.

**Expected:** worker re-reads, runs pause finalize, clears owner; final status
paused; never completed.

**Acceptance:** a pause committed before the terminal write always wins.

### T6 - Worker crash recovery

**Setup:** running job with a checkpoint; simulate a hard crash (stop
heartbeat; leave row `running`).

**Action:** redelivered task after lease expiry.

**Expected:**

- claim succeeds, token increments;
- old worker's writes fail;
- resume starts at `next_chunk_start`;
- no duplicate rows beyond the in-flight chunk.

**Acceptance:** final `completed`; row count equals the full window exactly
once.

#### T6b - Redelivery before expiry

**Action:** redelivered task with a fresh lease.

**Expected:** no claim; bounded retry scheduled; the original worker finishes.
If the original dies later, a retry claims after expiry.

**Acceptance:** no two owners; the message is not silently acked if it is the
only recovery path.

### T7 - Rollup lifecycle enforcement

**Setup:** a rollup job with two source stores; claim.

**Action:** duplicate dispatch; cancel during merge; fenced old merge.

**Expected:**

- duplicate dispatch: second claim fails;
- cancel: final `canceled`, no output publication;
- fenced merge: 0-row update, no output publication;
- missing source store: skip + `error_message`/warn event; `completion_state='partial'`
  with a gap count.

**Acceptance:** one writer; canceled stays canceled; no partial output pointer
for a canceled rollup; skipped sources are never reported as complete.

### T8 - Celery duplicate delivery

**Setup:** call `run_job` with a fake `current_task` / eager mode.

**Cases:**

1. queued, two deliveries -> one claim;
2. running, fresh lease, not redelivered -> exit, no write;
3. running, fresh lease, redelivered -> retry decision, no claim;
4. running, expired lease, redelivered -> claim, token + 1;
5. terminal -> exit;
6. lease lost during run -> no terminal write.

**Acceptance:** exactly one execution per job; duplicate messages do not
duplicate rows.

### T9 - S3 upload races

**Setup:** a completed job, fake S3 client, two retry requests.

**Action:** both claim an attempt; upload to unique prefixes; both attempt to
publish.

**Expected:**

- only one attempt claim succeeds at a time (`s3_uploading_at`);
- after the first completes, a second can claim a new token;
- the first attempt's publish with its old token affects 0 rows if superseded;
- objects are under `attempt_<token>/`;
- the DB pointer matches the winning attempt.

**Acceptance:** one `s3_published_attempt`; stale attempt objects are not
referenced.

#### T9b - Partial success

**Action:** raw succeeds, summary fails.

**Expected:** `s3_error` set, `s3_published_attempt` not advanced, successful
URI may be recorded; derived state is `s3_partial`.

#### T9c - Stale inline upload

**Action:** worker is fenced before the S3 publish update.

**Expected:** 0-row publish; no DB pointer change; objects orphaned.

### T10 - Checkpoint consistency

Fault injection at each point:

| Point | Expected |
|---|---|
| before fsync | DB checkpoint old; resume replays chunk; file truncated |
| after fsync before DB commit | DB old; resume replays; extra bytes ignored |
| during DB commit | atomic old/new; resume accordingly |
| after DB commit | resume next; no replay |
| after DB commit before event | event is in the same transaction; impossible |
| missing artifact | reset checkpoint; restart from zero; warn event |
| corrupted/truncated artifact | reset/restart; no silent tail-only file |
| zip artifact | cannot seek; reset/restart |
| store behind DB checkpoint | invalid for aggregation; reset/restart |
| store missing/unreadable | reset/restart; no partial-store resume |

**Acceptance:** for a 3-chunk job, kill at every point; final CSV equals the
expected rows exactly once; `rows_written` matches.

### T11 - Distinct-store replay

**Setup:** aggregation job; two chunks; fault after `DistinctStore.flush` but
before the DB checkpoint commit.

**Action:** resume a new attempt; merge the previous store; replay the chunk.

**Expected:**

- values are deduped;
- occurrence counts are not doubled;
- `last_chunk_committed` is preserved across the merge;
- the CSV contains the replayed rows once.

**Acceptance:** exact group/unique/occurrence counts.

### T12 - Schedule ledger and duplicate dispatch

**Setup:** one enabled daily schedule; Postgres; two concurrent scans.

**Action:** both run `scan_schedules` with a barrier.

**Expected:**

- one `schedule_windows` row for the window;
- one active job and one outbox row;
- `last_run_at` advances;
- no duplicate events.

**Acceptance:** window count == 1; one-active-job index/lock blocks the loser.

#### T12b - Failed window retry

**Setup:** a `schedule_windows` row `failed` with attempts < max.

**Action:** the next scan/dispatcher run.

**Expected:** window becomes `pending`/`dispatched` after backoff; a new attempt
job is created with the next `attempt_no`; attempts increment; completed windows
never retry.

**Acceptance:** retry is capped and visible; no duplicate active job.

#### T12c - Missing and dispatch-failure windows

**Setup:** a pending window with no job; a window whose outbox publish failed.

**Expected:** pending window is dispatched; dispatch failure remains
`pending`/`dispatched` with `last_error`; no silent `completed`. Backfill
creates pending rows oldest-first, capped at 14.

#### T12d - Success tracking

**Action:** a window's job completes.

**Expected:** `schedule_windows.status='completed'`, `current_job_id` set;
`last_success_at` derived; report does not show missed/pending; a rollup uses
the successful attempt, not both a failed and a retried job.

### T12e - Beat singleton

**Setup:** two beat processes or a scan-lock contention test.

**Expected:** only one scan proceeds; the other skips; ledger/outbox prevent
duplicates even if the lock expires.

**Acceptance:** one window/job; no duplicate cleanup events.

### T12f - Interval window identity

**Setup:** an interval schedule with a rolling lookback.

**Expected:** each dispatch slot has a stable `slot:<epoch>` window key; two
scans for the same slot do not create two jobs; overlapping actual lookback
windows are allowed but not duplicate slots.

### T12g - Schedule change/delete and partial window

**Setup:** edit a schedule while a window is pending; delete a schedule with a
pending window; complete a window partial.

**Expected:** pending window uses its `config_snapshot`; future windows use the
new config; delete cancels pending windows and keeps history; partial window is
`completed`+`partial` and requires explicit retry, not automatic failed retry.

### T12h - Timezone

**Expected:** calendar-day windows use UTC; the model comment's IST wording is
not the runtime behavior.

### T13 - Reaper fresh vs expired

**Setup:** two running jobs, one fresh lease, one expired (set directly).

**Action:** run reaper.

**Expected:**

- fresh untouched;
- expired -> `failed` (or `canceled` if a cancel request exists);
- owner/lease cleared;
- token + 1;
- event + alert.

**Acceptance:** no fresh job is failed; cancel-requested expired job is
canceled.

### T14 - Outbox: broker down at create

**Action:** create a job with `send_task` raising.

**Expected:**

- API returns 201 (not 500);
- job is `queued`;
- outbox row is `pending` with an error;
- dispatcher later publishes;
- claim executes once.

**Acceptance:** no orphaned committed job without intent.

### T15 - Outbox: crash after publish before mark

**Action:** publish succeeds; mark fails; dispatcher runs again.

**Expected:** republish; two messages; one claim; one execution.

**Acceptance:** duplicate publish count 1; execution count 1.

### T16 - Outbox: batch/group atomicity

**Action:** make one outbox insert fail.

**Expected:** no jobs, no group, no outbox rows committed.

**Acceptance:** transaction rollback.

### T17 - Outbox: queued reconciliation

**Setup:** a queued job with no outbox row; another with a stale published row.

**Action:** reconciliation task.

**Expected:** insert/reopen rows; dispatcher publishes; no duplicate execution.

**Acceptance:** one logical dispatch; one claim.

### T18 - Outbox: retry/backoff

**Action:** dispatcher publish fails N times.

**Expected:** attempts increment; `next_attempt_at` backs off; after max,
`status='failed'`; metric/alert.

**Acceptance:** no tight loop; failed row is visible.

### T19 - Heartbeat renewal

**Setup:** claimed job; heartbeat thread; DB up.

**Action:** wait one interval or invoke renewal.

**Expected:** `heartbeat_at` and `lease_expires_at` advance; progress writes
continue.

**Acceptance:** lease does not expire while the thread runs.

#### T19b - Heartbeat lost

**Action:** make heartbeat writes return 0 rows or fail past the margin.

**Expected:** `lease_lost` set; row loop aborts; no terminal write; no S3.

### T20 - Orphan owner cleanup

**Setup:** canceled-with-owner expired; paused-with-owner expired.

**Action:** reaper owner cleanup.

**Expected:** owner/lease cleared; token + 1; canceled `finished_at` set; paused
remains paused/resumable.

### T21 - Retry resume vs restart

**Setup:** failed job with a valid checkpoint/artifact; another with a missing
artifact.

**Action:** retry (D3 mode).

**Expected:**

- valid: new job resumes from `next_chunk_start`, seeds the prefix, publishes
  its own artifact;
- missing: new job restarts from zero with a warn event;
- `retry_of` links the original;
- group_id copied or an explicit group retry used.

**Acceptance:** no silent tail-only file; no mixed artifact.

### T22 - Artifact path publication

**Setup:** two attempts, token 1 and 2, different paths.

**Action:** token 1 publishes after token 2 (stale), then token 2 publishes.

**Expected:** token 1's pointer write affects 0 rows; token 2's pointer is the
only one; downloads use token 2's file.

**Acceptance:** no stale overwrite.

### T23 - Download/delete with attempt paths

**Action:** complete a job with an attempt path; request download; delete files.

**Expected:** download name is unchanged; the path is read from the row; delete
removes the referenced file and `.zip` variant.

**Acceptance:** no assumption of `job_<id>.csv`.

### T24 - S3 cleanup

**Setup:** attempts 1 (unpublished) and 2 (published).

**Action:** cleanup.

**Expected:** attempt 1 prefix deleted; attempt 2 kept; legacy URIs kept.

**Acceptance:** published attempt is never deleted.

### T25 - API/contract compatibility

- `JobOut` retains all existing fields and adds `phase`, `is_finalizing`,
  `completion_state`, `gap_count`, `gap_reason` additively.
- Status values remain the six.
- Pause/resume/cancel status codes remain 200/409.
- Retry 201.
- Bulk cancel skipped reasons remain.
- Old web status maps still work.

**Acceptance:** existing API tests pass unchanged except where behavior is
explicitly gated.

### T26 - Mixed-version flags

**Setup:** simulate an old worker that writes status without owner/token, and a
new worker that writes owner/token.

**Action:** run with `JOB_LEASE_MODE=observe`, then `enforce`; keep
`JOB_CANCEL_FENCE` off in the mixed case.

**Expected:**

- observe: the old worker can still write; the new worker writes owner/token;
  no rejection. This is a compatibility mode, not a safety proof.
- enforce: a stale token write is rejected; a job claimed by the old worker
  (owner null, no token) is not lease-reclaimable until the event fallback or
  reaper. Do not enable this combination in production.
- Neither mode makes an old worker honor a token; the deployment sequence is
  the control.

**Acceptance:** tests assert the flag behavior and the deployment gate; no
claim that mixed old/new workers are safe under enforcement.

### T27 - Status/completion CHECK migration audit

**Setup:** insert an unexpected `status` or `completion_state`, or an invalid
`schedule_windows.status`.

**Expected:** audit reports it; migration fails clearly; no data loss. Mixed
old/new code uses the same six statuses, so the CHECK is compatible once the
audit is clean.

### T28 - Completion integrity

**Setup:** clean run, skipped ID batches, rollup with a missing source, BQ drops,
preview, legacy row.

**Expected:**

- clean -> `completion_state='complete'`;
- skipped/rollup/BQ/canceled/preview -> `partial` with gap count/reason;
- legacy -> `unknown`;
- group/report day with a partial child -> `partial`, not `completed`/`ok`;
- job list/detail render a partial badge, not only "completed";
- old clients ignore the fields; new fields are additive.

**Acceptance:** no known-gap job is reported as clean success.

### T29 - Progress-aware heartbeat

**Setup:** claimed job; heartbeat thread; main loop blocked without progress.

**Action:** advance past `JOB_PROGRESS_TIMEOUT_SECONDS` (or manipulate the
in-process progress clock).

**Expected:** heartbeat stops renewing; `progress_at` remains stale; lease
expires or the reaper fences on stale progress; old worker cannot write; no S3
publication.

**Acceptance:** a live heartbeat alone cannot hold a hung job forever.

### T30 - Database outage during extraction

**Setup:** worker processing; make DB writes fail.

**Expected:** heartbeat/progress fail; worker stops at the TTL margin; row
remains running until a new claim/reaper; local attempt file is orphaned; no
terminal write.

**Acceptance:** no partial DB commit; recovery resumes from the last committed
checkpoint.

### T31 - Create response lost

**Setup:** create commits but the HTTP response is dropped.

**Expected:** job/outbox committed and eventually runs; a client retry may
create a second job (Release 1 residual). Document that idempotency keys are
Release 2.

**Acceptance:** no duplicate execution of the same job; duplicate job creation
is a known residual.

### T32 - Performance/soak

- 50 queued jobs, 4 worker threads, 10 minutes.
- No duplicate claims; all terminal; outbox empty; no orphan owners.
- Heartbeat query rate is bounded (one per job per 60 s).
- Reaper scan uses the index.

**Acceptance:** stable row counts; no lock timeouts; no memory growth.

## 4. Acceptance gates by milestone

| Milestone | Required tests |
|---|---|
| M1 | T1-T6, T13, T19-T20, T25, T28-T30 |
| M2 | T10-T11, T22-T23 |
| M3 | T7 |
| M4 | T14-T18 |
| M5 | T12, T12b-T12e |
| M6 | T9, T24 |
| M7 | T21 |
| M8 | T26-T27, T31-T32 |

## 5. Global invariants

Every test suite must assert:

1. `status` is one of the six values.
2. Terminal is absorbing.
3. `canceled` never becomes `completed`.
4. A 0-row guarded write means no subsequent worker write in that test.
5. `owner_id IS NULL` implies `lease_expires_at IS NULL`.
6. Only one `s3_published_attempt` per job.
7. One `schedule_windows` row per window; at most one active job.
8. Only one outbox row per `(job_id, task_name)`.
9. The published local file length equals the committed prefix for
   paused/canceled normal termination.
10. A known gap sets `completion_state='partial'`; group/report show partial.
11. The API response shape is unchanged for old clients.

## 6. Test execution

Suggested commands (design only; not run here):

```bash
# Existing fast suite
cd api && pytest -q
cd worker && pytest -q

# Postgres concurrency profile
TEST_DATABASE_URL=postgresql+psycopg://... pytest -q -m pg

# Broker/eager delivery profile
pytest -q -m broker
```

Add markers in `pytest.ini`/`pyproject.toml` for `pg`, `broker`, `fs`, `s3`.
Do not make the default unit suite require Postgres/Redis.

## 7. Open decisions affecting tests

- D1/D2: derived `phase`/`is_finalizing`; tests assert the chosen
  representation and download gating.
- D3: retry resume vs restart; T21 branches.
- D4/D5: attempt paths/stores; T22/T10/T11.
- D6: outbox; T14-T18.
- D7: S3 unique prefixes; T9/T24.
- D8: TTL/progress/reaper values; tests set expiry directly, not sleeps.
- D9: redelivery retry bound/time limits; T8/T6b.
- D10: minimum completeness; T28.
- D11: schedule ledger; T12/T12b-T12e.
- D12: beat scan lock; T12e.
- Download gating while finalizing; T23.
