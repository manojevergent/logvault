# Release 1 P0 Test Results

Status: P0-only validation evidence. No production code or schema was changed.

## 0. Environment and versions

| Item | Value |
|---|---|
| Runtime | Isolated Docker containers |
| PostgreSQL | `postgres:16-alpine`, healthy |
| Redis | `redis:7-alpine`, `--appendonly yes --save ""` |
| Python | 3.12.16 |
| Celery | 5.4.0 |
| Kombu | 5.4.2 |
| redis-py | 5.2.1 |
| SQLAlchemy | 2.0.36 |
| psycopg | 3.2.3 |
| boto3 | 1.35.36 |
| Test data | Scratch `p0_*` tables and temporary files only |
| Isolation | `p0/docker-compose.p0.yml`, `p0_default` Docker network |
| Production code | Not imported/modified |

Artifacts:

- `p0/results/p0_results.json`
- `p0/results/p0_manual_evidence.json`
- `p0/results/logs/worker-*.log`
- `p0/results/checkpoint/`, `p0/results/artifacts/`, `p0/results/s3/`

## 1. Summary

| Metric | Count |
|---|---|
| Executed | 19 |
| Passed | 18 |
| Failed | 1 |
| Blocked / not fully executable | 1 (real S3 provider behavior) |
| Requires production measurement | D8 timing, 24 h limits, Redis eviction, real S3 |
| Business decision | D9 runtime limit, D11 ledger scope |

The P0 harness is intentionally a **protocol/model** harness:
- P0-01..07 use a scratch `p0_leases` table with the proposed SQL shape, not
  production models.
- P0-08 uses a scratch outbox.
- P0-09 uses a scratch schedule ledger.
- P0-12 uses a checkpoint protocol model, not the production runner.
- P0-11 uses a P0 HTTP S3 stub, not a real S3 provider.

## 2. Test results

| ID | Test | Setup / procedure | Expected | Actual | Result | Evidence | Defect | Implication |
|---|---|---|---|---|---|---|---|---|
| P0-01 | Concurrent claim | Two sessions; barrier; conditional `UPDATE ... RETURNING` | Exactly one claim wins | B won; A 0 rows; token 1 | **PASS** | `results=[('B',1,(1,)),('A',0,None)]` | None | Postgres conditional claim is deterministic. |
| P0-02 | Fencing token | Token 1 then token 2; old/new writes | Old 0 rows; new 1 | old 0; new 1 | **PASS** | `old_token_rowcount=0, new_token_rowcount=1` | None | Token fencing works at DB level. |
| P0-03 | Lease reclaim | Fresh lease then expired lease | Fresh not stolen; expired reclaimed | healthy 0; expired 1; token 2 | **PASS** | `healthy_claim=0, expired_claim=1, token=2` | None | Lease predicate works. |
| P0-04 | Progress marker | Flag true/false around `progress_at` update | Advances only with progress | true advanced; false unchanged | **PASS** | timestamps in result | None | `progress_at` can be progress-gated. |
| P0-05 | Reaper | One expired, one fresh | Only expired reaped | reaped 1; fresh running | **PASS** | `rows=[(1,'failed',2),(2,'running',1)]` | None | Reaper predicate works. |
| P0-06 | Cancel dominance | Running token 1; cancel; terminal CASE | Final canceled | canceled; 1 row | **PASS** | `terminal_rowcount=1, status=canceled` | None | Cancel can dominate a terminal write. |
| P0-07 | Pause/resume fence | Pause; resume token+1; old/new writes | Old 0; new claim 1 | old 0; new claim 1; token 3 | **PASS** | `old_write=0, new_claim=1, token=3` | None | Resume token bump fences the old writer. |
| P0-08 | Outbox claim/republish | Two dispatchers; publish then crash-before-mark | One claim; republish; one execution | claims [1,0]; retry 1; published 2; executions 1 | **PASS** | `published=2, executions=1` | None | Outbox + claim gate works in model. |
| P0-09 | Schedule ledger/lock/retry | Two scans; Redis lock; duplicate dispatch; failed retry; edit/delete | One window/dispatch; retry; snapshot; cancel | inserts [1,0]; lock [True,False]; dispatch [1,0]; retry 1; active_dup 1; snapshot {'v':1}; canceled | **PASS** | result string | None | Ledger uniqueness/lock/retry primitives work. |
| P0-10 | Attempt file isolation | Two threads write `job_1.a1/a2.csv` | Distinct paths/content | both files; A/B content | **PASS** | `first=['A-0','A-1'], second=['B-0','B-1']` | None | Attempt-scoped paths isolate bytes. |
| P0-11 | S3 attempt publication/cleanup | P0 HTTP S3 stub; two attempts; stale/current publish; delete old | Unique keys; stale 0; current 1; current remains | keys 2; stale 0; current 1; remaining attempt_2 | **PASS** | result string | Real provider behavior unverified | Unique-prefix + DB pointer model works for basic ops. |
| P0-12 | Checkpoint crash matrix | Child process `os._exit` at fsync/store/DB boundaries | Resume only valid; restart invalid; final rows/counts exact | after_db resume; after_store resume; after_fsync/before_fsync restart; missing/newer/fingerprint/partial restart; artifact_newer resume; all 9 rows/store [9,9] | **PASS** | full case JSON | Initial zero-committed contract ambiguity found and fixed | Protocol works; zero committed chunks must restart. |
| P0-13 | Visibility redelivery while two workers active | Celery 5.4, Redis visibility 5 s, two solo workers already running, task sleeps 10 s | Duplicate start within visibility | starts=1 after 18 s; no redelivery | **FAIL** | `starts=1, hosts=[...], pids=[37]`; Redis unacked stayed | **Confirmed:** visibility alone did not redeliver with idle running workers | Do not depend on visibility for long-task recovery. |
| P0-13b | New worker restores unacked task | Long task unacked 6 s; start a new worker | New worker restores and duplicate starts | before 1; after 2 | **PASS** | `before_new_worker=1, after_new_worker=2` | None | Worker startup can trigger duplicate delivery. |
| P0-14 | Worker kill redelivery | SIGKILL worker; start new worker | Second start observed | starts=2 | **PASS** | `starts=2` | None | Broker/worker-loss path works with new worker. |
| P0-15 | `self.retry`/ETA | Retry countdown 1 s | Two attempts | retries=2; values [0,1] | **PASS** | result string | None | Retry/ETA works with short countdown. |
| P0-16 | Hard time limit | Prefork worker; 3 s hard limit; task sleeps 10 s | Start; no normal end | starts=1; ends=0 | **PASS** | result string | 23/24 h not tested | Hard limit kills child behavior observed. |
| P0-17 | Cleanup ownership model | Active/published/orphan/rollup files | Protect referenced; delete unreferenced | two candidates deleted; protected exist | **PASS** | result string | Model, not production cleanup | Ownership rule is implementable. |
| P0-18 | SIGTERM warm shutdown | SIGTERM during 5 s task | Task finishes; end recorded | starts=1; ends=1; stop 4.6 s | **PASS** | result string | None | Warm shutdown can let a short task finish. |
| P0-AOF-01 | Redis AOF key persistence | SET, restart Redis, GET | Value persists | appendonly=yes; persisted; PONG | **PASS** | manual evidence | None | AOF persistence works in P0 stack. |
| P0-AOF-02 | Queued Celery message survives Redis restart | No worker; enqueue; restart; consume | Queue remains; worker runs | LLEN 1 before/after; one start | **PASS** | manual evidence | None | Broker list survives AOF restart in P0. |
| P0-S3-LIMIT | Real S3-compatible provider | MinIO image unavailable; HTTP stub used | P0 stub only | Multipart/conditional/IAM/versioning unverified | **BLOCKED** | manual evidence | Registry limitation | Requires real S3/MinIO staging test. |

## 3. Critical result detail: P0-13

This is the most important P0 finding.

- Celery app: `task_acks_late=True`, `task_reject_on_worker_lost=True`,
  visibility 5 s.
- Two solo workers were already running.
- A task sleeping 10 s was sent.
- After 18 s, only one start was recorded.
- Redis `unacked_index` retained the delivery; the message did not appear on the
  queue while both workers were blocked/idle.

Kombu 5.4.2 `QoS.restore_visible` is called on poll/worker startup paths and
only every 10th call (`interval=10`). A new worker startup triggered restoration
(P0-13b), producing a second start while the first task was still active.

**Architectural implication:** broker visibility is not a reliable recovery
mechanism for long-running jobs. A database lease-expiry re-dispatch reconciler
is required. Fencing prevents duplicate writes, but not duplicate task starts or
slot consumption.

## 4. Critical result detail: P0-12

The checkpoint model passed all cases after correcting one contract ambiguity:

- **Zero committed chunks:** a checkpoint row with `completed_chunks=0` must
  restart; the partial artifact/store is uncommitted.
- **Crash after DB:** resume.
- **Crash after store before DB:** resume; marker prevents double counts.
- **Crash after/before fsync:** restart.
- **Artifact missing / checkpoint newer:** restart.
- **Artifact newer:** resume, copy committed prefix, replay suffix.
- **Fingerprint/partial:** restart.

All final cases produced 9 rows and store `[9,9]`.

## 5. Critical result detail: P0-16/P0-18

- Hard time limit with a prefork worker killed the child; no normal end event.
- SIGTERM allowed a 5 s task to finish in 4.6 s.
- The proposed 23 h/24 h limits were **not** tested; only the mechanism.

## 6. Evidence files

- `p0/results/p0_results.json` - 19 executed records.
- `p0/results/p0_manual_evidence.json` - AOF and S3 limitation.
- `p0/results/logs/worker-*.log` - worker logs.
- `p0/results/checkpoint/` - per-case artifacts/stores.
- `p0/results/artifacts/` - isolation files.
- `p0/results/s3/` - P0 S3 stub objects.

## 7. Pass/fail declaration

- **Passed:** P0-01..12, P0-13b, P0-14..18, AOF-01/02.
- **Failed:** P0-13.
- **Blocked:** P0-S3-LIMIT (real provider).
- **Not executed:** 23/24 h limits, production Redis eviction, production S3,
  production-scale timing, full T1-T24 lifecycle suite.
- **Requires business decision:** D9 hard/soft limit; D11 ledger scope.
- **Requires production measurement:** D8 timing, max runtime, real S3.
