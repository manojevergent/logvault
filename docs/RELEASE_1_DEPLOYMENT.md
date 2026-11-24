# Release 1 Deployment and Rollback

Status: design proposal. Not executed. No deployment, migration, or
configuration change was made.

Companion: [`RELEASE_1_DESIGN.md`](./RELEASE_1_DESIGN.md),
[`LEASE_AND_FENCING.md`](./LEASE_AND_FENCING.md),
[`OUTBOX_AND_DISPATCH.md`](./OUTBOX_AND_DISPATCH.md),
[`RELEASE_1_TEST_PLAN.md`](./RELEASE_1_TEST_PLAN.md).

Legend: **[V]** verified current behavior, **[P]** proposed, **[A]** unverified
assumption, **[D]** decision needed.

## 1. Current deployment facts

| Fact | Evidence |
|---|---|
| Production API runs 4 uvicorn workers. | `docker-compose.prod.yml:14-15`; `install-prod.sh:337` |
| Production worker is one service with embedded beat (`-B`) and `WORKER_CONCURRENCY=4`. | `docker-compose.yml:61-86`; `docker-compose.prod.yml:18-23`; `celery_app.py:20-31` |
| `deploy.sh` builds, runs `alembic upgrade head`, then `up -d --no-deps` for selected services. | `deploy.sh:18-27` |
| The API does not migrate on startup. | `deploy.sh:21-24` |
| The runbook documents `--scale worker=N`; each scaled worker also starts a beat because of `-B`. | `RUNBOOK.md:63-65`; `docker-compose.yml:79-86` |
| Redis is broker and result backend; no `visibility_timeout` is configured. | `docker-compose.yml:68-69`; `celery_app.py` |
| Migrations run in a single Alembic transaction by default. | `api/migrations/env.py` |
| The systemd install also starts one worker service with `-B`. | `install-prod.sh:349-366` |

Implications:

- A rolling restart can briefly mix old/new API instances. The outbox must be
  dual-written until all API instances are new.
- A worker-only deploy is possible; it must not enable enforcement that the
  old API/workers cannot satisfy.
- Scaling workers without a dedicated beat creates duplicate scans. Release 1
  mandates one beat.
- `CREATE INDEX CONCURRENTLY` cannot run inside the default Alembic
  transaction; plan a separate step or a maintenance window.
- A migration before code is safe only because new columns are additive. Never
  run a destructive migration first.

## 2. Feature flags

Flags are environment settings; both configs use pydantic settings with
`lru_cache` **[V]**, so changing a flag requires a process restart.

| Flag | Default at first deploy | Target | Purpose |
|---|---|---|---|
| `JOB_LEASE_MODE` | `off` | `observe` -> `enforce` | Acquire/write leases; enforce guards. |
| `JOB_LEASE_TTL_SECONDS` | `600` | `600` | Lease lifetime. |
| `JOB_HEARTBEAT_SECONDS` | `60` | `60` | Renewal cadence. |
| `JOB_RECLAIM_GRACE_SECONDS` | `60` | `60` | Extra time after expiry before reclaim. |
| `JOB_PROGRESS_TIMEOUT_SECONDS` | `3600` | `3600` | Stop heartbeat renewal when the main loop is silent. |
| `JOB_REAPER_GRACE_SECONDS` | `60` | `60` | Reap shortly after lease expiry. |
| `JOB_CANCEL_GRACE_SECONDS` | `120` | `120` | Force-finalize a stuck cancel. |
| `JOB_PAUSE_GRACE_SECONDS` | `120` | `120` | Release a stuck pause owner. |
| `JOB_RECLAIM_MODE` | `event` | `lease` | Event-age fallback vs lease-based reclaim/reap. |
| `JOB_CANCEL_FENCE` | `false` | `true` | API cancel leaves owner for running; worker cancel dominance. |
| `ARTIFACT_ATTEMPT_PATHS` | `false` | `true` | Attempt-scoped local paths/store. |
| `DISPATCH_MODE` | `direct` | `dual` -> `outbox` | Direct publish vs outbox. |
| `OUTBOX_DISPATCH_INTERVAL_SECONDS` | `30` | `30` | Dispatcher cadence. |
| `OUTBOX_MAX_ATTEMPTS` | `10` | `10` | Give-up threshold. |
| `SCHEDULE_WINDOWS_ENABLED` | `false` | `true` | Use the `schedule_windows` ledger + retry. |
| `S3_ATTEMPT_FENCING` | `false` | `true` | Unique S3 attempt prefixes + DB pointer. |
| `RETRY_MODE` | `restart` | `resume` (if D3) | Retry behavior. |
| `JOB_PROGRESS_TIMEOUT_SECONDS` | `3600` | `3600` | Stop heartbeat renewal when the main loop is silent. |
| `JOB_REAPER_GRACE_SECONDS` | `60` | `60` | Reap shortly after lease expiry. |
| `CELERY_VISIBILITY_TIMEOUT_SECONDS` | `3600` | `3600` | Explicit Redis redelivery behavior. |
| `CELERY_TASK_SOFT_TIME_LIMIT_SECONDS` | unset | decision | High soft limit for `run_job`. |
| `CELERY_TASK_TIME_LIMIT_SECONDS` | unset | decision | High hard limit for `run_job`. |
| `JOB_ARTIFACT_CLEANUP` | `false` | `true` | Orphan attempt cleanup. |

Do not enable `JOB_LEASE_MODE=enforce`, `JOB_CANCEL_FENCE=true`, or
`JOB_RECLAIM_MODE=lease` until every worker is new.

## 3. Phased rollout

Each phase has a stop/go gate. Do not combine phases in one production change
unless the test plan has been run against that exact combination.

### Phase 0 - Preflight

1. Confirm a fresh database backup and restore drill. The runbook already
   documents `pg_dump`/`pg_restore` **[V]** (`RUNBOOK.md:74-99`).
2. Record counts and distinct statuses/completion states:
   ```sql
   SELECT status, count(*) FROM jobs GROUP BY status;
   SELECT completion_state, count(*) FROM jobs GROUP BY completion_state;
   ```
3. Record duplicate schedule windows:
   ```sql
   SELECT created_by, start_epoch, count(*)
   FROM jobs WHERE created_by LIKE 'schedule:%'
   GROUP BY created_by, start_epoch HAVING count(*) > 1;
   ```
4. Confirm the Postgres test database is available for the concurrency suite.
5. Confirm the worker topology: one `-B` worker or one dedicated beat. If
   `--scale worker=N`, fix the topology before Release 1.
6. Confirm Celery 5.4's Redis `visibility_timeout=3600` and set it explicitly
   **[V]**; decide the task runtime limit (D9).
7. Confirm the exports volume is persistent and shared as expected.
8. Confirm no external consumer depends on the exact `job_<id>.csv` path
   **[A]**.

**Stop/go:** no unresolved duplicate status/values; no unexplained duplicate
windows; backup verified.

### Migration mechanics

Alembic revisions are linear. `deploy.sh` runs `upgrade head` **[V]**
(`deploy.sh:21-24`). If the build contains all Release 1 migrations, applying
head applies all of them; a later phase cannot skip an earlier revision.

Choose one:

- **Bundle (recommended for one release):** complete the status/duplicate
  audits, then apply `0032`-`0036` once in the migration window and gate
  behavior with flags. Apply `0037` (constraints) separately in P9 after the
  audit.
- **Milestone branches:** keep each milestone's migrations out of `main` until
  its phase, or target revisions explicitly (`alembic upgrade 0032`, then
  `0033`, etc.). Do not assume `upgrade 0034` skips `0033`.

The phase plan below assumes a milestone-branch or explicit-revision rollout.
A single-release bundle is safe if the preflight audits pass.

### Phase 1 - Schema 0032 (ownership and completion) with behavior off

**Note:** the final operator runbook splits P1 into `0032` (columns) and
`0032b` (concurrent indexes). This phase list is the older behavior-rollout
view; the final runbook is authoritative for P1 execution.

- Deploy `0032_job_ownership_and_completion.py`.
- No application behavior change; old code ignores the columns.
- Add the indexes (non-concurrent on a small table, or a separate concurrent
  step).
- Verify columns/indexes and that the API/worker still serve traffic.

**Stop/go:** migration applied; no errors; `/ready` ok; existing job creation
works.

### Phase 2 - Worker M1 in observe mode

- Deploy the new worker with `JOB_LEASE_MODE=observe`,
  `JOB_RECLAIM_MODE=event`.
- The worker claims and writes owner/token/lease, but does not reject stale
  writes and does not use lease-based reclaim.
- Start the progress-aware heartbeat; it may stop renewal on a hung main loop,
  but enforcement is still off.
- Do not enable API cancel-fencing yet.
- Monitor claim/lease logs, heartbeat/progress age, and any SQL errors.

**Stop/go:** all workers are the new version; no claim failures; no unexpected
writer errors; heartbeats/progress advance.

### Phase 3 - API control phases + enforcement

1. Deploy the API with conditional pause/resume/cancel, `phase`/
   `is_finalizing`, and `JOB_CANCEL_FENCE=true`.
2. Deploy the worker with `JOB_LEASE_MODE=enforce` and
   `JOB_RECLAIM_MODE=lease`.
3. Drain or wait for old running jobs to finish so they are not affected by
   lease-based reaping.

**Unsafe if:** an old worker still owns a running job and lease reclaim is
enabled. It has no heartbeat/token and can be stolen. Drain first or keep
`JOB_RECLAIM_MODE=event` until drained.

**Stop/go:** a canary job completes; pause/resume/cancel races pass; no fenced
writes on live jobs; reaper sees fresh leases as live; a hung main loop stops
heartbeating at the progress timeout.

### Phase 4 - Attempt-scoped artifacts and completion propagation (M2)

- Deploy `0033_job_artifact_paths.py` (adds `store_path`,
  `spec_fingerprint`, `checkpoint_version`) first if it was not included in the
  P1 schema bundle.
- Deploy the worker next with `ARTIFACT_ATTEMPT_PATHS=true`.
- New attempts write attempt paths and `store_path`; old rows remain on
  canonical paths.
- Deploy the API changes for `store_path`/cleanup and group/report `partial`
  propagation.
- Run a canary extraction, pause/resume, cancel, and a rollup on a small window.

**Stop/go:** downloads work; resume produces no duplicate/missing rows;
cleanup does not delete published paths; rollup reads `store_path`; a partial
child makes the group/report `partial`.

### Phase 5 - Outbox (M4)

1. Deploy `0034_job_dispatch_outbox.py` + backfill queued rows.
2. Deploy the dispatcher task with `DISPATCH_MODE=direct` (dispatcher idle or
   observing).
3. Deploy the API with `DISPATCH_MODE=dual` (writes outbox + direct dispatch).
4. Verify outbox rows are created and marked published.
5. Set `DISPATCH_MODE=outbox` after all API instances are new.
6. Keep the inline fast path; it is part of outbox mode.

**Unsafe if:** API is outbox-only before the dispatcher is running; jobs stay
queued. Or old API instances create jobs without outbox; the reconciliation
must cover them.

**Stop/go:** broker-down test in staging; batch all-or-nothing; no stuck queued
jobs; outbox age normal.

### Phase 6 - Schedule ledger and beat singleton (M5)

1. Deploy `0035_schedule_windows.py` (ledger with `window_key`,
   `scheduled_for`, `completion_state`, `config_snapshot`; jobs
   `schedule_window_id`/`attempt_no`).
2. Deploy a dedicated single `celery beat`; remove `-B` from workers.
3. Enable the scan lock (`SET NX EX 90` or Postgres advisory lock).
4. Deploy `SCHEDULE_WINDOWS_ENABLED=true`; seed ledger rows from existing
   scheduled jobs for the lookback/backfill range so the first scan does not
   re-run a covered day.
5. Resolve/report historical duplicate windows; legacy jobs keep
   `schedule_window_id=NULL`.

**Stop/go:** two concurrent scans produce one window/one active job; failed
windows retry with capped attempts; missing windows are pending; completed
windows never retry; reports use the ledger for missed/pending/failed.

### Phase 7 - S3 attempt publication (M6)

- Deploy `0036_s3_attempt_publication.py`.
- Deploy the worker/API with `S3_ATTEMPT_FENCING=true`.
- Verify a normal upload lands under `attempt_<token>/`.
- Verify a concurrent retry is rejected or gets a new attempt; the DB pointer
  matches one attempt.
- Verify cleanup does not delete the published attempt.

**Stop/go:** one published attempt; partial success visible; no stale publish.

### Phase 8 - Retry consistency (M7)

- Choose `RETRY_MODE` (D3).
- Deploy the API/worker and update the reaper message/UI.
- If `resume`, test a valid checkpoint/artifact and a missing-artifact fallback.
- If `restart`, update the runbook and any UI copy that promises resume.

**Stop/go:** retry behavior matches the message; no tail-only file.

### Phase 9 - Hardening (M8)

- Add `0037_status_constraints.py` after the status/completion/schedule audits.
- Enable orphan artifact cleanup.
- Add alerts/dashboards.
- Run the full Postgres concurrency suite and a soak test.

**Stop/go:** all acceptance gates pass; rollback plan reviewed.

## 4. Mixed-version compatibility matrix

| API | Worker | Safe? | Notes |
|---|---|---|---|
| Old | Old | Yes | Baseline. |
| New (observe) | Old | Mostly | New columns written; old ignores; cancel-fence off. |
| New (enforce) | Old | **No** | Old worker ignores tokens; can overwrite cancel/resume. |
| Old | New (observe) | Mostly | New worker leases; old API cancel is unprotected. |
| Old | New (enforce) | Mostly | New worker fences itself; old API can still write status directly. |
| New (cancel-fence) | Old | **No** | API leaves owner on cancel; old worker writes completed unconditionally. |
| New | New (observe) | Yes | Lease written, not enforced. |
| New | New (enforce) | Yes | Target. |
| New (outbox) | Old | Mostly | Old worker claims queued jobs; no lease/token. |
| New (outbox) | New | Yes | Target. |
| Old (direct) | New | Yes | Direct dispatch is still a valid message. |
| New (outbox) | New + old API | Yes with dual | Old API jobs need reconciliation. |
| New (completion) | Old worker | Mostly | Old worker leaves `completion_state=unknown`; safe but unreported. |
| New (schedule ledger) | Old beat still running | **No** | Old beat inserts jobs without ledger rows; stop old `-B` before enabling the ledger. |
| New (schedule ledger) | New beat + old API | Mostly | New scans use the ledger; old API-created schedule jobs have null windows. |

### 4.1 Unsafe sequences to forbid

1. **Enforce before all workers are new.** Old workers cannot send a token.
2. **Lease-based reclaim before old running jobs drain.** Old rows have no
   heartbeat; they can be stolen.
3. **Cancel-fence API with old workers.** Old workers overwrite canceled.
4. **Outbox-only API before the dispatcher runs.** Jobs stay queued.
5. **Schedule ledger enabled while an old `-B` beat still runs.** Old beat
   inserts jobs without ledger rows; stop/replace the old beat first.
6. **Drop/rename columns during rollback.** New code may still need them.
7. **Roll back the worker while attempt stores are published.** Old rollup
   reads canonical stores and under-reports; run the shim or keep the worker.
8. **Scale workers without a dedicated beat.** Duplicate scans; the scan lock
   and ledger are backstops, not a license.
9. **Change lease TTL/progress timeout drastically mid-flight.** A shorter TTL
   can expire live leases; a longer one delays recovery. Deploy the same values
   across API/worker.
10. **Enable S3 cleanup before the published-attempt pointer is populated.**
    It could delete the only objects.
11. **Enable the status/completion CHECK with legacy invalid values.** Audit
    first; do not auto-delete.

## 5. Monitoring and alerts

### 5.1 Logs

Structured fields on every transition:

```
job_id, from_status, to_status, trigger, owner_id, lease_token,
fenced_reason, source_status, attempt_token, outbox_id, result
```

Do not log credentials, tokens, payloads, or full file contents.

### 5.2 Metrics

| Metric | What it catches |
|---|---|
| `job_claim_total{result=won|lost}` | Claim contention / duplicate delivery. |
| `job_fenced_total{reason}` | Stale writers; a spike indicates a bug. |
| `job_heartbeat_age_seconds` | Leases about to expire. |
| `job_lease_expired_running` | Reaper workload. |
| `job_reaper_total{result}` | Reaper actions. |
| `job_cancel_to_final_seconds` | Stuck canceling rows. |
| `outbox_pending_age_seconds` | Broker/dispatcher outage. |
| `outbox_failed_total` | Permanent dispatch failures. |
| `queued_job_age_seconds` | Orphaned queued work. |
| `s3_attempt_conflicts_total` | Concurrent retries. |
| `s3_published_attempt_mismatch_total` | Stale publish attempts. |
| `schedule_duplicate_skips_total` | Duplicate scans/windows. |
| `artifact_orphan_bytes` | Cleanup backlog. |

### 5.3 Alerts

- Any `outbox_failed_total` increase.
- Oldest pending outbox > 5 min.
- Oldest queued job > 10 min.
- A running job with `lease_expires_at` in the past for > 15 min.
- A running job with no progress (`progress_at`) for >
  `JOB_PROGRESS_TIMEOUT_SECONDS` (warning before the heartbeat stops).
- `completion_state='partial'` rate above the expected baseline.
- `schedule_windows` failed/missed/pending age above the expected cadence.
- `job_fenced_total` above a small threshold for a live job.
- Reaper failures spike.
- S3 published-attempt mismatch > 0.
- Disk free below the configured threshold (existing check).

## 6. Rollback strategy

### 6.1 General

1. Roll back application code first; leave additive columns in place.
2. Disable flags before rolling back a layer that depends on them.
3. Never drop columns or tables in the rollback; they are harmless and may be
   needed for a forward fix.
4. Restore from backup only for data corruption, not for a code rollback.

### 6.2 Per milestone

| Milestone | Rollback | Limitation |
|---|---|---|
| M1 lease/fencing/completion | Set `JOB_LEASE_MODE=off`, `JOB_CANCEL_FENCE=false`, `JOB_RECLAIM_MODE=event`; stop reading completion fields; revert worker/API. | Old workers ignore tokens; if the API already bumped tokens, an unsafe window exists. Drain running jobs first. Completion fields remain as data. |
| M2 attempt artifacts | Set `ARTIFACT_ATTEMPT_PATHS=false`; revert worker. | Attempt stores are not visible to old rollup/cleanup. Run a copy/link shim for `store_path` or keep the new worker. |
| M3 rollup | Revert `run_rollup`. | Only after cancel-fence is off; otherwise canceled rollup can complete. |
| M4 outbox | Set `DISPATCH_MODE=direct`; keep table; drain pending rows. | Old API direct dispatch works; pending outbox rows need manual dispatch or the dispatcher. |
| M5 schedule ledger | Set `SCHEDULE_WINDOWS_ENABLED=false`; keep the table and one beat. | Legacy job-based schedule/report path resumes; ledger rows remain for audit. |
| M6 S3 attempt | Set `S3_ATTEMPT_FENCING=false`; old code reads `s3_uri`. | Attempt objects remain; cleanup can be deferred. |
| M7 retry | Set `RETRY_MODE=restart`; keep `retry_of`. | Behavior/message must be updated. |
| M8 constraints | Drop the CHECKs. | Legacy values can reappear; mixed old/new code still writes six statuses. |

### 6.3 Rollback limitations after fencing tokens

Once new workers use tokens and the API bumps them on resume/reaper:

- Rolling back to an old worker means it ignores the token and can write a
  stale status. There is no way to make old code honor a token.
- Mitigation: drain running jobs, set all flags off, roll back the API first,
  then the worker. Accept a short unprotected window only if necessary.
- Do not roll back the schema. The columns are the forward-compatibility
  bridge.

### 6.4 Rollback and attempt stores

If M2 is rolled back and old rollup code runs:

- It computes `store_path(storage_dir, job_id)` (canonical) and will not see
  `job_<id>.a<token>.distinct.sqlite`.
- Options:
  1. Keep the new worker/rollup deployed and roll back only API/web.
  2. Run a one-time shim that copies/links the `store_path` for completed jobs
     to the canonical name.
  3. Accept under-reported rollups until the new worker is restored.
- Do not delete attempt stores during rollback.

## 7. Post-deploy verification

Run after each phase:

- [ ] `/ready` → Postgres + Redis ok.
- [ ] `/health/ops` → worker beat fresh; backups fresh.
- [ ] `alembic current` / schema columns present.
- [ ] Create a canary job; it becomes `queued`, is claimed, completes.
- [ ] Pause a canary; it becomes paused; owner clears; resume completes.
- [ ] Cancel a canary; it ends canceled; no later completed.
- [ ] Retry a failed canary; behavior matches `RETRY_MODE`.
- [ ] Run two concurrent schedule scans in staging; one job/window.
- [ ] Stop the broker; create a job; API returns 201; outbox pending; restart
      broker; dispatcher publishes; job runs.
- [ ] Run a small rollup; source store path resolves; no duplicate writer; a
      skipped source sets `completion_state=partial`.
- [ ] Run an S3 retry twice; one published attempt; no stale overwrite.
- [ ] Inspect `jobs` for `running` rows with null owner after drain (legacy
      only).
- [ ] Check `job_fenced_total` is not spiking.
- [ ] Check a hung main loop stops heartbeating at the progress timeout.
- [ ] Check `schedule_windows` has one row per window; failed/missing windows
      retry or report correctly.
- [ ] Check a partial job makes the group/report `partial` and shows a partial
      badge on the job list/detail.
- [ ] Check disk/free and orphan artifact growth.

## 8. Operational runbook changes

- **Scale worker:** `--scale worker=N` is unsafe with `-B`. Run exactly one
  dedicated `celery beat`; the scan lock and ledger are backstops.
- **Stuck queued job:** check outbox pending/failed, dispatcher logs, broker
  connectivity; do not create a duplicate job.
- **Stuck canceling:** check cancel grace, lease/progress timeout, reaper logs;
  the reaper should clear the owner.
- **Stuck pausing:** check worker logs; resume bumps the token and fences it.
- **Stuck running with heartbeat:** check progress timeout; a live heartbeat
  alone must not hold the job forever.
- **Retry:** message must match `RETRY_MODE`; do not promise resume if restart.
- **S3 retry:** one attempt at a time; inspect `s3_attempt_token`,
  `s3_uploading_at`, `s3_published_attempt`.
- **Schedule window:** inspect `schedule_windows.status`/attempts/next_attempt_at;
  do not manually insert jobs without a window.
- **Rollback:** follow the flag order; do not drop columns; preserve attempt
  stores and ledger rows.

## 9. Open decisions

- D1/D2: derived `phase`/`is_finalizing` vs persisted intermediate statuses.
- D3: retry resume vs restart with checkpoint validation.
- D4/D5: attempt-scoped artifacts/stores.
- D6: outbox vs sweeper; create idempotency deferred.
- D7: S3 publication model.
- D8: 600/60/60 + progress timeout + reaper grace.
- D9: visibility timeout/retry bound/time-limit business decision.
- D10: minimum completeness in Release 1.
- D11: schedule ledger in Release 1.
- D12: dedicated beat + scan lock.
- D13: status/completion/schedule CHECK timing.
- Whether the production deploy is Docker (`deploy.sh`) or systemd
  (`install-prod.sh`); the same phase order applies, but the restart command
  differs.

## 10. Stop point

This is a design and deployment plan only. No code, schema, migration, API,
flag, or deployment change has been made. Wait for explicit approval before
implementation.
