# Release 1 Production Test Strategy

Status: test strategy only. No tests have been implemented for Release 1. The
existing suite is unchanged.

## 1. Evidence and limits

- API tests: in-memory SQLite **[T]** (`api/tests/conftest.py`).
- Worker tests: SQLite file **[T]** (`worker/tests/conftest.py`).
- No real Postgres/Redis concurrency suite exists **[T]**.
- Celery 5.4.0/Redis 7/Celery Redis visibility 3600 **[C]**.
- SQLite cannot prove row-lock, fencing, outbox, or schedule concurrency
  correctness. Those tests are mandatory on Postgres.

## 2. Test environments

| Profile | Dependencies | Purpose |
|---|---|---|
| `unit` | SQLite | State tables, path builders, validation matrix, API serialization. |
| `pg` | Postgres 16 | Claims, fencing, cancel/pause, reaper, outbox locks, schedule ledger. |
| `broker` | Redis 7 + Celery 5.4 | Visibility, redelivery, retry/ETA, worker loss, broker restart. |
| `fs` | Temp directory | Attempt paths, checkpoint copy, store merge, cleanup. |
| `s3` | Fake boto3 client or MinIO | Attempt prefixes, manifest, publish fence, cleanup. |

Do not add a new test dependency. Use the existing SQLAlchemy/psycopg/redis/
Celery stack. Use pytest markers and CI service containers.

### 2.1 Postgres fixture

- Dedicated test database, never the app DB.
- `Base.metadata.create_all` or Alembic `upgrade head`.
- Two independent engines/sessions; barrier synchronization.
- Row-lock/statement timeouts to fail instead of hanging.
- Set lease/progress timestamps directly; no sleeps.
- Truncate/rollback between tests.

### 2.2 Redis/Celery fixture

- Dedicated Redis DBs for broker/result/beat lock.
- A worker process (or eager mode for decision tests).
- Fault injection for `send_task`, worker kill, Redis restart.
- Do not rely on `task_id` dedupe; assert claim count.

### 2.3 Fault injection

- `fail_before_fsync`, `fail_after_fsync`, `fail_before_checkpoint_commit`,
  `fail_after_checkpoint_commit`.
- Fake lease/token, fake `current_task.request.redelivered`.
- Fake S3 client with per-artifact failure/latency.
- Fake DB outage for heartbeat/progress.
- Fake Redis outage/restart.
- No random sleeps; use events/barriers.

## 3. Required tests

| # | Test | Setup | Action | Expected DB | Expected worker | Expected artifact | Expected API | Expected monitoring |
|---|---|---|---|---|---|---|---|---|
| T1 | Two workers claim same job | One queued job; two Postgres sessions | Concurrent claim | One owner/token=1; loser 0 rows | One runs; loser exits | None yet | 201/queued before; status later | `job_claim_total{result=won/lost}` |
| T2 | Stale worker reclaimed | A running; lease expired; redelivered | B claims | Token increments; owner B | B runs; A eventually fenced | New attempt path | Same job status running | `job_reclaim_total` |
| T3 | A writes after B reclaims | A token 1; B token 2 | A progress/terminal | 0 rows from A; B state only | A raises `LeaseLost`, closes files, no publish | A's path orphan | No A status change | `job_fenced_total` |
| T4 | Cancel during extraction | Running; cancel | Cancel then worker continues | status canceled, `cancel_requested_at`, final `canceled` | Worker finalizes canceled, keeps partial | Partial path published | 200 cancel; download later | `job_cancel_to_final_seconds` |
| T5 | Cancel during final artifact publication | Running near terminal; cancel | Cancel vs terminal update | cancel wins if first; completed if terminal first | Fenced/no S3 if cancel first | No stale S3 publish | 200/409 | `job_fenced_total`, S3 mismatch 0 |
| T6 | Pause then resume while old active | Running; pause; resume | Old worker progress after resume | status queued, owner null, token+1 | Old aborts; new claims | New attempt seeds checkpoint | 200 pause/resume | `job_fenced_total` |
| T7 | Crash after chunk data before checkpoint | 3-chunk job; kill before DB commit | Restart/redeliver | Checkpoint old; token new | New attempt copies old prefix | CSV has chunk once | Job completes | `checkpoint_replay_total` |
| T8 | Crash after checkpoint | Kill after DB commit | Restart/redeliver | Checkpoint new | Resume next chunk | No replay | Job completes | `checkpoint_resume_total` |
| T9 | Artifact exists, checkpoint invalid | Corrupt/truncated/zip artifact | Retry/resume | Checkpoint reset; token new | Restart from zero | No tail-only file | Job completes/partial | `checkpoint_invalid_total` |
| T10 | Checkpoint exists, artifact missing | Delete artifact | Retry/resume | Checkpoint reset | Restart from zero | New artifact | Job completes | `checkpoint_invalid_total` |
| T11 | S3 succeeds, DB publication fails | Fake S3; fail publish update | Retry | `s3_published_attempt` unchanged; `s3_error` set | No stale publish | Orphan attempt prefix | Job completed; retry available | `s3_orphan_bytes`, mismatch 0 |
| T12 | DB publication succeeds, worker crashes | Fake S3; kill after publish update | Restart | `s3_published_attempt` set | New worker sees completed | Published objects remain | Download/S3 UI | `s3_publish_total` |
| T13 | Celery redelivers while original active | Long task; live lease; duplicate message | Deliver twice | One owner | Redelivered task retries/exits; no steal | One attempt | Job continues | `job_redelivery_total` |
| T14 | Outbox crash after publish before mark | Dispatcher publish succeeds; mark fails | Dispatcher restart | Outbox pending/stale lock | One claim; one execution | One artifact | Job runs | `outbox_duplicate_publish_total` |
| T15 | Two dispatchers | Two dispatcher workers | Concurrent claim | One row locked; one publish | One execution | One artifact | Job runs | `outbox_publish_total{result}` |
| T16 | Two beats scan | Two beat processes; scan lock | Concurrent scan | One window/one active job | One dispatch | One artifact | Report one run | `schedule_duplicate_skips_total` |
| T17 | Schedule window fails/retries | Failed window; attempts<max | Next scan/dispatch | Window pending/failed; attempts++; new job | New attempt | New artifact | Job/retry | `schedule_window_retry_total` |
| T18 | Retry after schedule config change | Pending window; edit schedule | Retry | Window uses `config_snapshot` | New attempt with snapshot | Same window key | Report correct | `schedule_window_retry_total` |
| T19 | Job finished with skipped batches | Fake batch 400s | Run | completed + partial + gap_count | Runner completes | Artifact short; gap visible | Job partial badge | `completion_partial_total` |
| T20 | Group complete/partial/failed | One of each child | Read group | Group partial/failed per precedence | N/A | N/A | `/groups/{id}` partial | `group_partial_total` |
| T21 | Report incomplete source | Partial + failed jobs/day | Read report | Day failed/partial; rows correct | N/A | N/A | `/reports` | `report_incomplete_days` |
| T22 | Cleanup while attempt active | Running attempt; cleanup/delete | Cleanup/customer delete | Referenced paths kept; unreferenced removed | Attempt continues | Published path intact | Download works | `artifact_cleanup_deleted_total` |
| T23 | Old/new workers coexist | Old worker no token; new worker | Observe then enforce | Old writes in observe; enforce rejects stale new | New fences itself; old unsafe if enforce | No corruption in observe | Same API | `job_lease_mode` |
| T24 | Rollback after schema | Apply 0032-0037; run new code; rollback code | Disable flags/revert | Columns remain; old code works | Old workers ignore tokens | Attempt stores remain | Old API works | `job_lease_mode{off}` |

## 4. D3 recovery matrix tests

T7-T10 must cover every row in
[`RELEASE_1_READINESS_REVIEW.md`](./RELEASE_1_READINESS_REVIEW.md) section 2.4:

- no checkpoint/no artifact -> restart;
- valid/clean/same lineage/fingerprint -> resume;
- missing/shorter/corrupt/zip artifact -> restart;
- artifact newer than checkpoint -> resume/replay;
- checkpoint newer than artifact -> restart;
- store behind/missing -> restart;
- store ahead -> resume;
- fingerprint/lineage mismatch -> restart;
- skipped batches/partial -> restart;
- unknown schema/path escape/IO -> manual fail.

Acceptance: no test produces a tail-only file, duplicate committed rows, or a
completed status with known gaps.

## 5. D8 timing tests

- Heartbeat renews while progress marks advance.
- Heartbeat stops when progress is stale.
- `progress_at` does not advance on heartbeat alone.
- Reaper fences on stale `progress_at` even if a heartbeat was renewed.
- Long Last9 retry chain with per-attempt progress does not fence.
- A blocked main loop with a live heartbeat thread fences at the timeout.
- DB outage: worker stops at TTL margin; no terminal write.
- Healthy worker with a stage > progress timeout is **expected to be fenced**
  until measured/configured; document.

## 6. D9 Celery/Redis tests

Mark these as **isolated integration tests**, not assumptions:

- Visibility timeout 3600: task >1h redelivered; claim safe.
- `self.retry` ETA < visibility; no loop.
- Worker kill -9: redelivery; resume.
- Warm shutdown vs SIGKILL; `stop_grace_period`.
- Redis restart/AOF: unacked/outbox behavior.
- `acks_on_failure_or_timeout`: failed task is acked, job status remains.
- `result_expires`: long task result state; DB is authoritative.
- Hard/soft time limit (if approved): kill/resume/checkpoint.

## 7. D10 completion tests

- Clean -> `complete`.
- Skipped ID batches -> `partial` + count.
- Rollup skipped source -> `partial`.
- BQ rows dropped -> `partial`.
- Canceled -> `partial`.
- Failed before coverage -> `unknown`.
- Reaped -> `unknown`.
- Preview -> `partial` and excluded from reports.
- Legacy -> `unknown`.
- Group/report/job list/detail all agree; UI badge visible.

## 8. D11 schedule tests

- Calendar `window_key=day:...`; interval `slot:...`.
- Two scans -> one window/one active job.
- Failed -> retry/backoff; max attempts -> failed/manual.
- Missing -> pending/missed.
- Backfill cap 14.
- Dispatch failure -> pending with `last_error`.
- Completed window -> no retry.
- Partial -> completed+partial, manual retry.
- Schedule edit -> pending uses snapshot, future uses new config.
- Delete -> pending canceled, history retained.
- Report/rollup winner only.
- Timezone UTC; no DST.
- Beat crash/restart; lock expiry; two starts.

## 9. Real-environment acceptance

- All T1-T24 pass on Postgres 16 + Redis 7 + Celery 5.4.
- T7-T10 pass at every fault point.
- T23/T24 pass in a staging mixed-version deployment.
- No SQLite-only evidence accepted for concurrency.
- Test reports include DB rows, artifact hashes/row counts, API response, and
  metric deltas.

## 10. CI layout

```bash
pytest -q                       # unit/SQLite
pytest -q -m pg                 # Postgres concurrency
pytest -q -m broker             # Redis/Celery
pytest -q -m fs                 # artifact/checkpoint
pytest -q -m s3                 # fake S3
```

Do not make the default unit suite require Postgres/Redis; do require the
release gate to run all profiles.

## 11. Acceptance criteria

- No test leaves two owners.
- Terminal is absorbing; cancel dominance holds.
- Every 0-row guarded write stops the worker before artifact/S3 publication.
- Checkpoint recovery never produces a tail-only or duplicate-row artifact.
- Outbox never leaves a committed job without intent; duplicate messages
  execute once.
- Schedule ledger never loses or duplicates a successful window.
- Partial results are visible and not reported as clean success.
- Rollback after schema is exercised once in staging.
