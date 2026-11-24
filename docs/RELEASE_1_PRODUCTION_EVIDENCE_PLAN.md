# Release 1 Production Evidence Plan

Status: **plan only.** No measurement, test harness, schema, or runtime change
has been made. P1 is not authorized. This plan separates what must be proven
before P1, before P2, and before production rollout.

Related:

- [`RELEASE_1_FINAL_ARCHITECTURE_APPROVAL.md`](./RELEASE_1_FINAL_ARCHITECTURE_APPROVAL.md)
- [`RELEASE_1_FINAL_DECISION_REGISTER.md`](./RELEASE_1_FINAL_DECISION_REGISTER.md)
- [`RELEASE_1_P1_SCOPE_AND_MIGRATION.md`](./RELEASE_1_P1_SCOPE_AND_MIGRATION.md)
- [`RELEASE_1_P0_EXECUTION_REPORT.md`](./RELEASE_1_P0_EXECUTION_REPORT.md)
- [`RELEASE_1_P0_TEST_RESULTS.md`](./RELEASE_1_P0_TEST_RESULTS.md)
- [`RELEASE_1_P0_FAILURE_ANALYSIS.md`](./RELEASE_1_P0_FAILURE_ANALYSIS.md)
- [`RELEASE_1_P0_CONFIGURATION_FINDINGS.md`](./RELEASE_1_P0_CONFIGURATION_FINDINGS.md)

## 1. Purpose

P0 proved a set of primitives in an isolated stack. It did **not** prove:

- real S3-compatible provider behavior;
- production job runtime distribution;
- the longest legitimate silent stage;
- production Postgres locking and isolation behavior;
- production Redis capacity, persistence, and eviction behavior;
- worker slot occupancy under real load;
- external canonical-path consumers;
- schedule/report/rollup integration;
- the proposed soft/hard runtime limits.

This plan defines the evidence required to move from design approval to P1, from
P1 to P2 behavior, and from P2 to production rollout.

## 2. Evidence classes

| Class | Meaning | May be used for |
|---|---|---|
| **Measured** | Collected from a production-like environment or real provider | Approving behavior |
| **P0-observed** | Collected in the isolated P0 stack | Validating primitives only |
| **Assumption** | Stated but unmeasured | Design only; not approval |
| **Business decision** | Policy choice, not a measurement | Approval by the user |

No P0 result may be relabeled as a production measurement.

## 3. Gate model

| Gate | Question | Blocks |
|---|---|---|
| **G-P1** | Can the additive schema be applied and rolled back without behavior change? | P1 start |
| **G-P2** | Is there enough evidence to enforce claim/fence/recovery and choose safe lease/progress values? | P2 start |
| **G-PROD** | Is there enough evidence to run the new behavior in production? | Production rollout |

P1 itself is schema-only, so it can be authorized before real-provider S3 and
runtime measurements. P2 behavior must not be authorized on assumptions alone.

## 4. Before P1 (G-P1)

P1 does not read the new columns, so these are migration-safety gates only.

| ID | Evidence | Method | Pass criteria |
|---|---|---|---|
| G-P1-01 | Upgrade applies | `alembic upgrade 0031:0036` on a populated Postgres 16 copy | Success; row counts unchanged |
| G-P1-02 | Schema shape | Inspect columns, defaults, indexes, unique constraints | Match [`RELEASE_1_P1_SCOPE_AND_MIGRATION.md`](./RELEASE_1_P1_SCOPE_AND_MIGRATION.md) |
| G-P1-03 | No behavior change | Run existing API/worker test suite | Same results as pre-migration |
| G-P1-04 | Old-version compatibility | Old API read + old worker smoke on migrated copy | Responses/tasks unchanged |
| G-P1-05 | New tables inert | Count outbox/window rows | 0 rows; no readers |
| G-P1-06 | Downgrade | `alembic downgrade 0036:0031` | Success; objects removed |
| G-P1-07 | Re-upgrade | Upgrade again | Success |
| G-P1-08 | Lock/duration | Time each migration and capture lock waits | Fits approved window |
| G-P1-09 | No flags/config/deps | Diff deployment/config/dependency files | Empty |
| G-P1-10 | Rollback rehearsal | Restore snapshot and repeat | Documented, reproducible |

**Gate rule:** P1 may start only after G-P1-01..10 are planned and the user
authorizes P1. The evidence is produced during P1, before P2 is requested.

## 5. Before P2 (G-P2)

P2 enforces claim, fencing, heartbeat, progress, and control phases. These
measurements set the values that P2 uses.

### 5.1 Runtime distribution

| ID | Question | Method | Pass criteria / use |
|---|---|---|---|
| G-P2-RT-01 | What is the total job duration distribution? | Query `jobs.started_at`/`finished_at` for completed jobs over a representative period | p50/p95/p99/p999 and max by region/source |
| G-P2-RT-02 | What is the longest legitimate single chunk? | Worker instrumentation or chunk event timings | Sets heartbeat/soft-limit floor |
| G-P2-RT-03 | What is the longest finalization/summary/rollup stage? | Stage timestamps/events | Must fit the soft limit |
| G-P2-RT-04 | How long does the largest S3 upload take? | Provider timing | Must fit the hard limit or be post-completion |
| G-P2-RT-05 | How long does recovery/replay take after a kill? | Kill/resume test on a representative job | Bounds operational impact |
| G-P2-RT-06 | What is the queue wait/slot occupancy? | Worker task start vs enqueue time | Sets capacity assumptions |

**Outputs:** measured max attempt duration, p99 chunk, p99 finalization, and a
recommended soft/hard policy. **These values remain unapproved until the user
accepts them.**

### 5.2 Longest silent stage

| ID | Question | Method | Pass criteria |
|---|---|---|---|
| G-P2-SL-01 | Longest interval with no committed chunk | Instrument or derive from existing logs | p99 and max |
| G-P2-SL-02 | Longest single Last9 request/retry chain | Provider/client timing | Fits progress timeout |
| G-P2-SL-03 | Longest DB lock wait | `pg_stat_activity` / `pg_locks` sampling | Fits lease TTL |
| G-P2-SL-04 | Is progress observable during the longest stage? | Add temporary metrics in staging, not production code | A progress signal exists before timeout |

**Outputs:** `progress_timeout`, `lease_expires_at`, and heartbeat interval
recommendations. If no progress signal exists during a legitimate stage, the
design must add one or the progress timeout must exceed that stage.

### 5.3 Postgres claim/fence/lease

| ID | Question | Method | Pass criteria |
|---|---|---|---|
| G-P2-PG-01 | Does exactly one claim win under real concurrency? | N concurrent sessions on a production-like Postgres | One winner, N-1 zero rows |
| G-P2-PG-02 | Does a stale token always write 0 rows? | Reclaim, then old-token write | 0 rows, no side effect |
| G-P2-PG-03 | Is a healthy lease ever stolen? | Claim against a fresh lease | 0 rows |
| G-P2-PG-04 | Does the reaper touch only stale rows? | Mixed stale/fresh rows | Only stale reaped |
| G-P2-PG-05 | Does cancel dominate completion? | Race cancel/terminal | Final status canceled |
| G-P2-PG-06 | Does pause/resume create two writers? | Pause, resume, old write | Old 0 rows |
| G-P2-PG-07 | What is the lock wait under load? | Measure claim/terminal transactions | Within approved latency |
| G-P2-PG-08 | Does the reconciler find expired jobs exactly once? | Concurrent reconciler runs | One re-dispatch intent |

P0-01..07 passed these on scratch tables; G-P2-PG must repeat them on the real
schema and production-like isolation.

### 5.4 Real S3-compatible provider

P0 used an HTTP stub because MinIO was unavailable. The stub is not provider
evidence.

| ID | Question | Method | Pass criteria |
|---|---|---|---|
| G-P2-S3-01 | Does multipart upload/abort work? | Upload a large artifact via the production client | Correct object; clean abort |
| G-P2-S3-02 | Are conditional writes/ETags reliable? | Attempt conditional put/compare | Expected conflict behavior |
| G-P2-S3-03 | Does IAM/signature/region work? | Use the production credential shape | Auth succeeds; no stub shortcuts |
| G-P2-S3-04 | Does versioning/object lock behave as assumed? | Inspect provider configuration | Documented, no surprise retention |
| G-P2-S3-05 | Is listing consistent after publish? | Publish then list by attempt prefix | Current attempt visible; old attempts separable |
| G-P2-S3-06 | Does cleanup preserve the published attempt? | Delete old attempt prefix | Published prefix remains |
| G-P2-S3-07 | Do stale attempt writes stay unreferenced? | Two attempts, stale pointer update | Stale 0 rows; objects orphaned |

**Gate rule:** P2 local artifact enforcement may start with the stub results, but
**S3 publication (P8) and any production S3 claim require G-P2-S3-01..07**.

### 5.5 Redis recovery and persistence

| ID | Question | Method | Pass criteria |
|---|---|---|---|
| G-P2-RD-01 | Does AOF preserve broker keys? | Restart Redis; inspect queue/unacked | Keys survive |
| G-P2-RD-02 | Does a queued message survive restart? | Enqueue, restart, consume | Consumed once |
| G-P2-RD-03 | Does memory stay below the limit? | Load test with long unacked tasks | Headroom; no eviction |
| G-P2-RD-04 | What is the eviction policy in production? | `CONFIG GET maxmemory*` | Documented; broker keys protected |
| G-P2-RD-05 | How large does `unacked` grow? | Long-task load test | Bounded and alerted |
| G-P2-RD-06 | Does visibility redelivery behave in production? | Repeat P0-13/P0-13b on production config | Documented; not relied on |
| G-P2-RD-07 | Does result expiry lose state? | Observe a long task past `result_expires` | DB remains authoritative |

### 5.6 Worker slot occupancy and termination

| ID | Question | Method | Pass criteria |
|---|---|---|---|
| G-P2-WK-01 | How many slots does a long job occupy? | Concurrency test | Measured |
| G-P2-WK-02 | What happens to a hung worker? | Simulate a hung task | Documented; no false claim of auto-free |
| G-P2-WK-03 | Does a hard limit kill the child? | Prefork test at the proposed value | Child killed; checkpoint resumes |
| G-P2-WK-04 | Does a soft limit allow cleanup? | Soft-limit handler test | Handler checkpoints/exits |
| G-P2-WK-05 | Does SIGTERM finish a long task? | Stop-grace test at production duration | Documented; grace chosen |
| G-P2-WK-06 | Does a replacement duplicate-start? | Start a new worker while original runs | Duplicate start observed; fencing safe |

## 6. Before production (G-PROD)

### 6.1 Canonical-path external consumers

| ID | Question | Method | Pass criteria |
|---|---|---|---|
| G-PROD-CP-01 | Who reads `job_<id>.*` paths outside the app? | Code/search + ops/consumer inventory | List complete |
| G-PROD-CP-02 | Who reads S3 keys without an attempt prefix? | Bucket/consumer inventory | List complete |
| G-PROD-CP-03 | Can each consumer use the DB pointer? | Contract review | All migrated or explicitly exempt |
| G-PROD-CP-04 | Does download work for attempt paths? | API/UI test | Correct file; no stale path |
| G-PROD-CP-05 | Does customer delete handle attempt paths? | Delete test | No dangling files/rows |

### 6.2 Schedule/report/rollup integration

| ID | Question | Method | Pass criteria |
|---|---|---|---|
| G-PROD-SR-01 | Is one window created per key? | Two beats/two scanners | One row |
| G-PROD-SR-02 | Is one job dispatched per window? | Concurrent dispatch | One winner |
| G-PROD-SR-03 | Is a failed window retried with backoff? | Inject failure | Retry once per policy |
| G-PROD-SR-04 | Is there one active job per window? | Race two jobs | Unique index holds |
| G-PROD-SR-05 | Does config edit preserve the snapshot? | Edit schedule after window creation | Snapshot unchanged |
| G-PROD-SR-06 | Does report select one winner? | Retry then report | No double count |
| G-PROD-SR-07 | Does rollup select the successful source? | Retry then rollup | No duplicate/missing source |
| G-PROD-SR-08 | Does delete/cancel behave? | Delete/cancel window/schedule | Consistent state |
| G-PROD-SR-09 | Does timezone/calendar identity hold? | IST boundary test | Correct day/slot |

P0-09 passed the DB primitives only; G-PROD-SR must test the real scheduler,
reports, and rollup.

### 6.3 Operational readiness

| ID | Question | Method | Pass criteria |
|---|---|---|---|
| G-PROD-OP-01 | Are lease/progress/outbox alerts live? | Inject stale/outbox failure | Alert fires |
| G-PROD-OP-02 | Is the reconciler observable? | Re-dispatch a stale job | Event/metric recorded |
| G-PROD-OP-03 | Is rollback rehearsed? | Restore snapshot, downgrade, redeploy | Documented |
| G-PROD-OP-04 | Is a mixed-version drain safe? | Old+new worker test | No double writer |
| G-PROD-OP-05 | Is the migration window approved? | Change record | Approved |
| G-PROD-OP-06 | Is there capacity headroom? | Disk/Redis/DB check | Within policy |
| G-PROD-OP-07 | Is a stuck-slot runbook ready? | Tabletop/real test | Documented owner/action |

### 6.4 Full test coverage

| ID | Requirement | Pass criteria |
|---|---|---|
| G-PROD-TC-01 | T1–T24 lifecycle/API/frontend suite | All pass or explicitly waived |
| G-PROD-TC-02 | Crash-at-each-stage on real runner | No missing/duplicate committed chunks |
| G-PROD-TC-03 | Partial-result UI | Visible and downloadable with warning |
| G-PROD-TC-04 | S3 provider integration | G-P2-S3 passed |
| G-PROD-TC-05 | Production-like load | No lease storms or pool exhaustion |

## 7. Measurement method (no production code now)

When authorized, collect evidence without changing behavior:

1. **Read-only SQL** for runtime distribution and row counts.
2. **Existing logs/events** for chunk/finalization timing where available.
3. **Staging instrumentation** behind a temporary, non-production flag.
4. **Load tests** in an isolated environment with production-like Postgres,
   Redis, and S3.
5. **Provider tests** against a real S3-compatible endpoint, not the P0 stub.
6. **Kill/restart tests** on a representative job, with checkpoint validation.

Do not add permanent metrics or columns outside the approved phase.

## 8. Evidence record template

Each evidence item must record:

| Field | Content |
|---|---|
| ID | `G-P1-*`, `G-P2-*`, `G-PROD-*` |
| Date/environment | Where and when |
| Versions | Postgres, Redis, Celery, Kombu, redis-py, Python, provider |
| Setup | Data volume, concurrency, job shape |
| Procedure | Exact commands/queries |
| Expected | Pass criteria |
| Actual | Measured result |
| Verdict | Pass / fail / blocked |
| Artifacts | Logs, query output, screenshots, IDs |
| Decision impact | Which D decision it supports |
| Owner | Who approves |

Store records under `docs/evidence/` or an equivalent approved location. Do not
mark an item passed from code inspection alone.

## 9. Assumptions that must not be treated as evidence

| Assumption | Status |
|---|---|
| "Visibility timeout will eventually redeliver." | **False per P0-13**; do not rely on it |
| "A new worker will always restore unacked work." | Observed in P0-13b, not a guarantee |
| "Lease expiry kills the process." | **False**; it only changes authority |
| "Fencing frees a worker slot." | **False** |
| "The P0 S3 stub proves provider behavior." | **False** |
| "23 h/24 h is safe." | **Unmeasured** |
| "3600 s progress timeout fits all stages." | **Unmeasured** |
| "Redis AOF means no message loss." | P0 passed in isolation; capacity/eviction unproven |
| "Canonical paths have no external consumers." | **Unverified** |
| "Report/rollup already handle retries correctly." | **Unverified** |

## 10. Gate summary

| Gate | Required evidence | Decision unlocked |
|---|---|---|
| G-P1 | Migration up/down, no behavior change, rollback rehearsal | P1 |
| G-P2 | Postgres concurrency, runtime distribution, silent stage, real S3, Redis, slot behavior | P2 enforcement; D3/D8/D9 values |
| G-PROD | Canonical consumers, schedule/report/rollup, operational readiness, full suite | Production rollout |

## 11. Stop condition

This plan defines evidence only. Do not execute production measurements, apply
migrations, or change behavior until the user authorizes the relevant phase.
