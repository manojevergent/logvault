# Release 1 Operations and Monitoring

Status: operations design only. No dashboards, alerts, or code have been
implemented.

## 1. Principles

- Metrics prove ownership, dispatch, schedule, and completion behavior; they do
  not replace the database row.
- Do not ship fixed alert thresholds without a baseline. Start in observe mode,
  collect 7-14 days, then set thresholds from p95/p99 behavior.
- Alert on **stuck work and incorrect success**, not on every retry.
- Every alert links to a runbook action that does not require guessing.

## 2. Required metrics

| Metric | Meaning | Source | Aggregation | Operational significance | Alert strategy | Dashboard |
|---|---|---|---|---|---|---|
| `job_active_leases` | Jobs with a current owner/lease | `jobs` count `status='running'` | Gauge by status/worker | Current execution load | Capacity planning; not an alert alone | Ownership |
| `job_expired_leases` | Running rows with `lease_expires_at < now()` | `jobs` | Gauge/age | Reaper/reclaim backlog | Alert if oldest > 2× reaper grace | Ownership |
| `job_lease_reclaimed_total` | Reclaims after redelivery | Worker claim result | Counter by result | Recovery activity | Alert on spike vs baseline | Ownership |
| `job_fenced_total` | 0-row guarded writes | Worker log/metric | Counter by reason | Stale/duplicate writers | Alert on any sustained increase | Ownership |
| `job_progress_age_seconds` | `now - progress_at` for running | `jobs`/worker gauge | p50/p95/p99/max | Stalled main loop | Warn at 80% of timeout; page at timeout | Ownership |
| `job_heartbeat_age_seconds` | `now - heartbeat_at` | `jobs`/worker | p50/p95/p99/max | Lease health | Warn at 3× heartbeat interval | Ownership |
| `job_running_no_owner` | Running with owner null | `jobs` | Gauge/age | Legacy/inconsistency | Alert after grace | Ownership |
| `job_stuck_finalizing_seconds` | Paused/canceled with owner | `jobs` | Gauge/age | Finalization stuck | Alert after cancel/pause grace | Ownership |
| `job_running_seconds` | Time in running | `jobs` | Histogram by status | Long jobs vs hung | Compare to p99; no fixed cap | Jobs |
| `completion_partial_total` | Terminal partial jobs | `jobs` | Counter by reason | Data gaps | Alert on rate above baseline | Completeness |
| `completion_unknown_total` | Legacy/reaped unknown | `jobs` | Counter | Coverage unknown | Alert on new unknown after rollout | Completeness |
| `completion_gap_count` | Sum/avg gaps | `jobs` | Gauge by reason | Size of missing data | Trend; alert on spike | Completeness |
| `outbox_pending` | Pending outbox rows | `job_dispatch_outbox` | Gauge/age | Dispatch backlog | Alert oldest > dispatch interval×2 | Dispatch |
| `outbox_failed_total` | Permanent dispatch failures | outbox | Counter | Jobs not dispatched | **Page on any increase** | Dispatch |
| `outbox_publish_total` | Publish attempts | dispatcher | Counter by result | Broker health | Alert failure rate | Dispatch |
| `outbox_dispatch_delay_seconds` | created -> published | outbox | p95/p99/max | Latency | Warn at p99×2 | Dispatch |
| `queued_job_age_seconds` | Oldest queued | `jobs` | Gauge/age | Orphaned/backlogged | Alert > 10 min or baseline p99×2 | Dispatch |
| `schedule_windows_due` | Pending due windows | ledger | Gauge/age | Scheduler backlog | Alert oldest > cadence | Schedules |
| `schedule_windows_failed` | Failed windows | ledger | Gauge | Missed data | Alert/trend | Schedules |
| `schedule_windows_missed` | Derived missed | ledger/report | Gauge | Silent missing days | Alert on any new daily miss | Schedules |
| `schedule_window_retry_total` | Window retries | ledger | Counter by result | Recovery activity | Alert on repeated retry | Schedules |
| `schedule_duplicate_skips_total` | Duplicate scans/windows | scan lock/ledger | Counter | Beat overlap | Alert on spike | Schedules |
| `checkpoint_recovery_failures_total` | Invalid/missing checkpoint | worker | Counter by reason | Lost progress/rework | Alert on spike | Recovery |
| `checkpoint_replay_chunks_total` | Replayed chunks | worker | Counter | Crash/recovery cost | Trend | Recovery |
| `artifact_publish_failures_total` | Local/S3 publication failures | worker/API | Counter by kind | Missing delivery | Alert on any S3 publish failure | Artifacts |
| `s3_orphan_bytes` | Unpublished attempt prefixes | cleanup/S3 | Gauge | Storage leak | Warn on growth | Artifacts |
| `s3_publish_attempt_mismatch_total` | Stale S3 publish attempts | worker | Counter | Duplicate/race | Alert on any | Artifacts |
| `artifact_cleanup_failures_total` | Cleanup errors | cleanup | Counter | Disk growth/data loss risk | Alert on any | Artifacts |
| `artifact_cleanup_deleted_total` | Files removed | cleanup | Counter | Retention activity | Trend | Artifacts |
| `beat_lock_acquired_total` | Scan lock wins | beat | Counter by result | Beat health | Alert if no win in 2 ticks | Scheduler |
| `beat_lock_failures_total` | Lock contention/errors | beat | Counter | Overlap/Redis | Alert on sustained contention | Scheduler |
| `celery_redelivery_total` | Redelivered tasks | worker | Counter | Long jobs/broker | Trend; alert on spike | Celery |
| `celery_retry_total` | `self.retry`/task retry | worker | Counter by reason | Broker/lease | Trend | Celery |
| `celery_task_runtime_seconds` | Task duration | worker | Histogram | Capacity/time limits | Compare p99 to limits | Celery |
| `celery_result_expired_total` | Result state missing | worker/ops | Counter | Support confusion | Trend | Celery |

## 3. Alerts

Initial alerts are **symptom-based**; thresholds should be tuned after a
baseline:

| Alert | Condition | Why | Runbook |
|---|---|---|---|
| Outbox permanently failed | `outbox_failed_total` increases | Committed job may never run | Inspect outbox, broker, dispatcher; republish/manual. |
| Oldest outbox pending | Age > 2× dispatch interval or baseline p99 | Dispatcher/broker slow | Check dispatcher, Redis, queue depth. |
| Queued job old | Age > 10 min or baseline p99×2 | Orphaned dispatch | Check outbox/reconciliation, worker capacity. |
| Expired lease old | Oldest expired > 2× reaper grace | Reaper/worker issue | Check reaper, DB, worker logs. |
| Progress stale | `progress_age` > 80% timeout | Hung main loop | Inspect worker stack; expect reaper. |
| Fenced writes | Sustained `job_fenced_total` | Duplicate/stale worker | Identify job/owner; check reclaim/resume. |
| Stuck finalizing | Paused/canceled owner > grace | Finalization hang | Check worker; reaper/force-finalize. |
| Partial spike | `completion_partial_total` above baseline | Data gaps | Inspect `gap_reason`, skipped batches, rollup sources. |
| Schedule missed | Daily window missed | Silent data gap | Inspect ledger, beat, dispatcher, worker. |
| Schedule duplicate skips | Spike | Beat overlap | Check `-B`/dedicated beat/lock. |
| Checkpoint recovery failures | Spike | Artifact/store inconsistency | Inspect path/offset/store marker; restart/manual. |
| S3 publish mismatch | Any | Stale attempt | Do not delete; inspect attempt token/pointer. |
| Orphan S3 growth | Trend | Cleanup failing | Inspect cleanup task/lifecycle rules. |
| Beat lock failures | Sustained | Redis/lock/overlap | Check lock TTL, Redis, beat instances. |
| Celery redelivery spike | Above baseline | Long jobs/broker instability | Check visibility, worker kills, broker. |

## 4. Baselines

1. Deploy metrics in observe mode; no enforcement.
2. Collect 7-14 days, including a daily schedule cycle and a month-end rollup
   if possible.
3. Record p50/p95/p99/max for:
   - claim/heartbeat/progress age;
   - chunk duration and silent stage;
   - finalization/zip/S3;
   - outbox dispatch delay;
   - schedule window age;
   - Celery task runtime/redelivery.
4. Set progress timeout ≥ 2-3× max legitimate silent stage.
5. Set alerts at 80% of the timeout and page at 100%.
6. Re-baseline after any schedule/volume change.

## 5. Dashboards

1. **Ownership:** active/expired leases, heartbeat/progress age, fenced writes,
   running-no-owner, reclaims.
2. **Dispatch:** queued age, outbox pending/failed/delay, publish result,
   reconciliation.
3. **Schedules:** due/pending/dispatched/running/completed/failed/missed,
   retries, duplicate skips, beat lock.
4. **Completion:** partial/unknown/gap reasons, group/report partial.
5. **Artifacts:** local publish failures, S3 attempt/publish, orphan bytes,
   cleanup.
6. **Celery/Redis:** task runtime, redelivery/retry, worker loss, broker/result
   errors, Redis memory/AOF.

## 6. Runbook entries

- **Outbox failed:** inspect `status`, `attempts`, `last_error`; verify broker;
  reset with a new attempt; do not create a duplicate job.
- **Stuck queued:** check outbox/reconciliation/worker; confirm no active claim.
- **Expired lease:** check reaper/DB; do not manually set `completed`.
- **Stuck canceling:** wait for cancel grace; inspect reaper; force-finalize via
  the documented path; never overwrite `canceled` with `completed`.
- **Stuck pausing:** resume fences the old worker; if not, cancel and retry.
- **Progress stale:** inspect worker stack/logs; let the lease/reaper recover;
  do not extend TTL without understanding the stage.
- **Schedule missed:** inspect ledger and beat; manually retry the window; do
  not create a bare job without a window.
- **Checkpoint invalid:** inspect artifact size/offset/store marker; allow
  restart; do not resume a tail-only file.
- **S3 mismatch:** do not delete objects; inspect attempt token/published
  pointer; retry a new attempt.
- **Rollback:** disable flags in the documented order; keep columns/attempt
  stores/ledger rows.

## 7. Observability implementation notes

- Structured logs: `job_id`, `from/to`, `trigger`, `owner`, `lease_token`,
  `phase`, `completion_state`, `outbox_id`, `attempt_token`, `result`.
- Do not log credentials, tokens, payloads, or customer log contents.
- Use DB time for age metrics.
- Expose worker-local progress/heartbeat gauges via the existing metrics path
  (or logs) until a metrics backend is chosen.
- A metric is not proof of correctness; pair each alert with a DB query.
