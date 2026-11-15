# Release 1 Blocker Closure Review

Status: closure review only. No implementation, schema, migration, API, frontend,
dependency, or deployment change has been made.

This document closes or narrows the six NOT READY areas identified in
[`RELEASE_1_READINESS_REVIEW.md`](./RELEASE_1_READINESS_REVIEW.md) and links the
new detailed contracts.

## 0. Verdict

**Overall: NOT READY for full Release 1 implementation approval; P0 validation
has been executed and closes the primitive-evidence gap with one failed test.**

P0 evidence: 19 executed, 18 passed, 1 failed (P0-13 visibility), 1 real-S3
area blocked. See
[`RELEASE_1_P0_EXECUTION_REPORT.md`](./RELEASE_1_P0_EXECUTION_REPORT.md).
P1 is not authorized. D9 must add a DB lease-expiry re-dispatch reconciler.

The six blocker areas now have contracts; P0 tested their DB/broker primitives,
but production behavior and integration are not implemented:

- D3: contract is complete; tests/code not implemented.
- D8: liveness model is defined; values need measurement.
- D9: architecture options are defined; the hard/soft runtime decision is still
  a business decision; Redis/Celery integration tests are not run.
- D10: contract is complete; backend/frontend derivation is not implemented.
- D11: contract is complete; scope is still a business decision.
- Artifact/cleanup: lifecycle is complete; canonical-path code corrections are
  not implemented.

P0 is the only implementation-adjacent work that should be authorized next, and
only after this document is approved.

## 1. Traceability matrix

Status meanings: **Conditional** = design closed, implementation/test pending;
**Open** = code correction not designed enough; **Business** = approval needed;
**Blocked** = cannot proceed without another decision.

| ID | Original finding | Current decision | Source | Required correction | Required test | Status |
|---|---|---|---|---|---|---|
| F1 | Commit then publish | Outbox + inline fast path | `jobs.py:324-327`; `tasks_client.py` | Outbox table/dispatcher/reconcile | T14-T18 | Conditional |
| F2 | Conditional claim, no fence | Lease/token/owner guards | `db.py:193-230` | `lease.py`; guarded writes | T1-T3 | Conditional |
| F3 | `started_at` overwritten | Preserve first start | `runner.py:229-234` | `COALESCE(started_at, now())` | T2 | Conditional |
| F4 | Unconditional terminal writes | Guarded finalize/cancel dominance | `runner.py:830-895`; `rollup.py:85` | `finalize_owned` | T4, T7 | Conditional |
| F5 | Immediate pause/cancel ORM | Request fields + phase | `jobs.py:829-865` | Conditional updates; phase API | T4-T6 | Conditional |
| F6 | Event-age reaper | Lease + progress + reaper grace | `scheduler.py:192-249` | New reaper | T13, T29 | Conditional |
| F7 | Retry no checkpoint | Strict D3 resume/restart | `jobs.py:975-996` | Checkpoint contract | T7-T10, T21 | Conditional |
| F8 | Retry lineage gaps | `retry_of` + lineage | `jobs.py`; `groups.py` | Copy/preserve lineage | T21 | Open |
| F9 | Rollup bypasses lifecycle | Claim/cancel/source winner | `rollup.py` | P5 | T7, T12d | Open |
| F10 | Shared S3 keys | Unique attempt prefix + DB pointer | `s3.py:97-179` | P8 | T9, T11, T24 | Conditional |
| F11 | Canonical local paths | Attempt-scoped artifacts | `runner.py:151-180` | P4 | T10, T22 | Conditional |
| F12 | Customer delete hardcoded | Artifact scan + ledger/outbox policy | `customers.py:73-86` | P4 update | T22 | Open |
| F13 | Rollup concat canonical | Attempt path | `rollup.py:285` | P4 update | T7 | Open |
| F14 | Cleanup canonical store | `store_path` + orphan scan | `scheduler.py:322`; `rollup.py:130` | P4 update | T22 | Open |
| F15 | Report day `created_at` | Ledger/window start + partial | `reports.py:100-125` | P3/P7 | T21 | Conditional |
| F16 | Group ignores partial child | Any partial -> partial | `groups.py:38-50` | P3 | T20 | Conditional |
| F17 | Web has no partial badge | Completion/phase UI | `api.ts:265-371`; jobs pages | P3 | T19 | Conditional |
| F18 | Celery no visibility/time limit | Option C/DB dispatch | `celery_app.py:20-37` | D9 decision + tests | T13, T23 | **Business** |
| F19 | `-B` worker topology | Dedicated beat + lock | compose/systemd | P7 deployment | T12e | Conditional |
| F20 | SQLite-only tests | Postgres/Redis harness | conftest | P0 | P0-1..P0-15 | **Blocked until P0** |
| F21 | Alembic transaction | Audit/backfill/concurrent index | `env.py` | P1/P4/P7 migration plan | P0/migration tests | Conditional |
| F22 | Worker DB pool | Size to concurrency | `db.py:176-178` | Config review | T28 | Conditional |
| F23 | Delete vs S3 retry | Ownership/deletion rules | `jobs.py:868-910` | P4/P8 | T22 | Open |
| F24 | UTC vs IST comment | Document UTC | `scheduler.py:81-87`; model comment | P7 docs | T12h | Closed (doc) |
| F25 | `_already_extracted` status-blind | Ledger obligation | `scheduler.py:94-108` | P7 | T12/T12b | Conditional |
| F26 | `_mark_failed` bypass | Lease-aware fail | `tasks.py:112-136` | P2 | T1/T23 | Conditional |
| F27 | S3 retry no attempt | Attempt token/lock | `tasks.py:180-228` | P8 | T9 | Conditional |
| F28 | Customer delete vs ledger | Deletion policy | `customers.py:146-163` | P4/P7 | T22 | Open |
| F29 | Low-disk unmatched path | Null all paths | `scheduler.py:352-367` | P4 | T22 | Open |
| F30 | No status CHECK | Audit then CHECK | models/migrations | P9 | P0/migration | Conditional |

## 2. D3 closure summary

The complete contract is
[`RELEASE_1_CHECKPOINT_RECOVERY_CONTRACT.md`](./RELEASE_1_CHECKPOINT_RECOVERY_CONTRACT.md).

Key closure points:

- Checkpoint v1 identity: version, source job, lineage root, attempt token,
  spec fingerprint, window, chunk cursor, offsets, artifact/store paths,
  store marker.
- Resume only when lineage/fingerprint/artifact/store/no-gap rules all pass.
- Partial/skipped batches restart, not resume.
- Unknown schema/path escape/IO -> manual fail.
- Artifact newer than checkpoint: copy committed prefix and replay.
- Store behind, artifact missing/short/corrupt/zip: restart.
- Source data mutability is an accepted assumption, not a proof.

**Status: Conditional** - contract complete; implementation/tests pending.

## 3. D8 closure summary

The full liveness model is in
[`RELEASE_1_READINESS_REVIEW.md`](./RELEASE_1_READINESS_REVIEW.md) section 3 and
[`LEASE_AND_FENCING.md`](./LEASE_AND_FENCING.md) sections 5 and 8.

### 3.1 Five liveness concepts

1. **Process liveness:** the worker process/thread exists.
2. **Job execution liveness:** a task is executing the job.
3. **Processing progress:** rows/chunks/requests/stages are advancing.
4. **Lease ownership:** this worker has a valid token/lease.
5. **Finalization activity:** zip/summary/counts/terminal transaction.

A heartbeat proves only process liveness; a lease proves ownership; neither
proves progress.

### 3.2 Progress sources

| Stage | Progress mark | Persisted |
|---|---|---|
| Source query | before/after each HTTP attempt and backoff | In-memory; `progress_at` via heartbeat |
| ID-batch retrieval | per attempt/backoff | same |
| Record processing | per row or bounded interval | in-memory |
| Chunk persistence | after fsync + DB checkpoint | `progress_at` via heartbeat |
| SQLite updates | before/after flush | in-memory |
| CSV generation | before/after write/flush | in-memory |
| Compression | start/end; optionally per entry | in-memory |
| S3 upload | post-completion, no job lease | no lease renewal |
| Rollup processing | per source merge | in-memory + checkpoint |
| Finalization | start/end terminal transaction | `progress_at` via heartbeat |

### 3.3 Timing policy

- `JOB_HEARTBEAT_SECONDS=60` (DB renewal).
- `JOB_LEASE_TTL_SECONDS=600`.
- `JOB_RECLAIM_GRACE_SECONDS=60`.
- `JOB_PROGRESS_TIMEOUT_SECONDS=3600` (initial; measure).
- `JOB_REAPER_GRACE_SECONDS=60`.
- Reaper also checks `progress_at` stale as defense-in-depth.

Recovery: dead process ~11 min; hung main loop ~71 min. A healthy stage silent
longer than 60 min is falsely fenced; this must be measured and the timeout
raised if necessary.

### 3.4 Outages

- **DB down:** heartbeat/progress fail; worker stops at TTL margin; row remains
  running until DB returns; reclaim/reaper.
- **Redis down:** existing task continues; beat/reaper/redelivery unavailable
  until Redis returns; DB row remains authoritative.
- **S3 down:** post-completion delivery failed; job remains completed with
  `s3_error`; retry.
- **External API slow:** per-attempt progress; if no callbacks, 60 min may false
  fence; instrumentation is mandatory.
- **Long retry backoff:** progress mark before/after sleep; no 60-min silence.

**Status: Conditional** - model complete; values and instrumentation need
measurement/tests.

## 4. D9 closure summary

Full decision:
[`RELEASE_1_CELERY_REDIS_DECISION.md`](./RELEASE_1_CELERY_REDIS_DECISION.md).

- Redis visibility 3600 is real; a >1 h task is redelivered while original
  runs. DB fencing prevents duplicate writes, not duplicate delivery.
- Recommended Release 1: **Option C** - one task per job, hard/soft runtime
  limits, visibility >= hard limit + margin, and a **DB lease-expiry
  re-dispatch reconciler** so crash recovery does not wait for visibility.
- Option B (bounded execution units) is the long-term robust architecture but a
  major refactor.
- Time limits (e.g., soft 23 h/hard 24 h) are a **business decision**.
- Redis AOF/noeviction and worker shutdown need integration tests.

**Status: Business decision required**; tests blocked until P0.

## 5. D10 closure summary

### 5.1 Contract

| Case | Status | Completion | Publication | UI |
|---|---|---|---|---|
| Clean | completed | complete | local/S3 published or pending | Completed |
| Partial | completed | partial | local published; S3 may be pending/failed | Partial badge + gap reason |
| Failed | failed | unknown/partial | may have partial local | Failed |
| Canceled | canceled | partial | partial local | Canceled |
| Paused | paused | n/a | partial local | Paused |
| S3 pending | completed | complete/partial | s3 pending | Completed + S3 pending |
| S3 failed | completed | complete/partial | s3 failed | Completed + S3 failed |

- No seventh execution status.
- `completion_state` is orthogonal; `unknown` for legacy/reaped.
- Partial job remains downloadable; UI must label it; API adds
  `completion_state`/gap fields; optionally a response header
  `X-LogVault-Completeness: partial`.
- Group: any child partial -> partial.
- Report: any partial -> partial; successful attempt/window only.
- Rollup: skipped source -> partial.

### 5.2 Derivation paths

`groups.py:_group_status`, `reports.py:_day_status`, `reports.py:_rows`,
`jobs.py:JobOut`, `web/lib/api.ts:Job`, jobs list/detail, group detail, reports
page. A shared helper and contract test are required.

**Status: Conditional** - contract complete; implementation/UI pending.

## 6. D11 closure summary

Full contract:
[`RELEASE_1_SCHEDULE_WINDOW_CONTRACT.md`](./RELEASE_1_SCHEDULE_WINDOW_CONTRACT.md).

- `window_key`: `day:YYYY-MM-DD` / `slot:<epoch>`.
- `scheduled_for`, `schedule_version`, `config_snapshot`, `completion_state`.
- Unique `(schedule_id,window_key)`, one active job per window.
- Pending -> dispatched -> running -> completed/failed/canceled; retry.
- Partial = completed + partial; manual retry only.
- Edits affect future windows; pending retries use snapshot.
- Delete cancels pending windows; running may finish; history kept.
- UTC calendar; interval slots; overlap allowed.
- Ledger owns obligation; Schedule owns config/cadence; jobs own execution.

**Status: Conditional / business scope** - contract complete; full ledger vs
calendar-only split must be approved.

## 7. Artifact closure summary

Full contract:
[`RELEASE_1_ARTIFACT_LIFECYCLE.md`](./RELEASE_1_ARTIFACT_LIFECYCLE.md).

- Attempt-scoped local/S3 paths; DB pointer is publication.
- Cleanup never deletes active/published/rollup-needed/checkpoint-needed data.
- Existing canonical assumptions in `customers.py`, `rollup.py`,
  `scheduler.py` are concrete corrections.
- Customer delete must handle windows/outbox; low-disk purge must null all
  four paths; delete-files must coordinate with S3.
- S3 published attempt is never deleted.

**Status: Conditional** - contract complete; code/tests pending.

## 8. Document contradictions found and resolved

| Contradiction | Resolution |
|---|---|
| `RELEASE_1_DESIGN` earlier deferred completion | Revised: minimum completion in Release 1 |
| `WORKER_OWNERSHIP` heartbeat 120 s | Revised: 60 s + `progress_at` |
| `LEASE_AND_FENCING` unique schedule index | Revised: `schedule_windows` ledger + `window_key` |
| `RELEASE_1_TEST_PLAN` T12 unique-index policy | Revised: ledger/retry/winner tests |
| `RELEASE_1_DEPLOYMENT` schedule unique flag | Revised: `SCHEDULE_WINDOWS_ENABLED` |
| `RELEASE_1_ARCHITECTURE_DECISIONS` D11 `start_epoch` identity | Revised: `window_key` |
| Old `STATE_MACHINE_ROADMAP` migration numbers | Superseded by Release 1 docs; note remains |
| `artifacts` canonical path assumptions | Revised: attempt-scoped lifecycle |

No unresolved contradiction should be used as an implementation source. The
Release 1 documents are authoritative.

## 9. P0 foundation

Full plan:
[`RELEASE_1_P0_VALIDATION_PLAN.md`](./RELEASE_1_P0_VALIDATION_PLAN.md).

P0 was executed. Results: 19 tests, 18 passed, 1 failed (P0-13 visibility),
real S3 provider blocked. The P0 evidence supports the DB claim/fence/outbox/
ledger/checkpoint/artifact primitives, but shows visibility is not a reliable
recovery timer. See
[`RELEASE_1_P0_EXECUTION_REPORT.md`](./RELEASE_1_P0_EXECUTION_REPORT.md).

P0 **does not** implement production schema/behavior. If P0 fails, revise the
architecture before P1.

## 10. Migration and deployment safety

- Additive migrations first; old code ignores fields.
- Fencing enforcement only after all workers are new and old running jobs drain.
- Cancel-fence only after all workers are new.
- Attempt paths only after cleanup/rollup/customers code is updated.
- Outbox dual-write before outbox-only.
- Schedule ledger only after old `-B` beat is stopped.
- S3 attempt fencing after local paths and tests.
- CHECK constraints after audits.
- Rollback leaves columns/tables/attempt stores; never drop data.

Exact sequence: [`RELEASE_1_DEPLOYMENT.md`](./RELEASE_1_DEPLOYMENT.md).

## 11. Updated readiness verdict

| # | Area | Classification |
|---|---|---|
| 1 | Worker ownership and fencing | READY WITH CONDITIONS |
| 2 | Checkpoint recovery | READY WITH CONDITIONS |
| 3 | Lease and heartbeat | READY WITH CONDITIONS |
| 4 | Celery and Redis | **BUSINESS DECISION REQUIRED** |
| 5 | Completion integrity | READY WITH CONDITIONS |
| 6 | Artifact isolation | READY WITH CONDITIONS |
| 7 | S3 publication | READY WITH CONDITIONS |
| 8 | Cleanup and deletion | READY WITH CONDITIONS |
| 9 | Transactional outbox | READY WITH CONDITIONS |
| 10 | Schedule-window ledger | **BUSINESS DECISION REQUIRED** (scope) |
| 11 | PostgreSQL migrations | READY WITH CONDITIONS |
| 12 | Production test coverage | **NOT READY** (P0 not run) |
| 13 | Deployment and rollback | READY WITH CONDITIONS |
| 14 | NOC monitoring | READY WITH CONDITIONS |

Counts: **0 READY, 11 READY WITH CONDITIONS, 1 NOT READY, 2 BUSINESS DECISION
REQUIRED** (14 areas).

## 12. Smallest safe implementation scope

**P0 is executed; P1 is not authorized.** The smallest safe production scope
after separate approval is:

1. P1 schema/state primitives.
2. P2 claim/fencing/progress/control phases.
3. P4 attempt artifacts/stores/checkpoint validation.
4. P3 minimum completion + UI/derivation.
5. P8 S3 attempt publication (because P4 local paths otherwise leave S3
   canonical-key races).

Defer P5 rollup lifecycle, P6 outbox, and P7 schedule ledger until separately
approved. Their risks must be explicitly accepted in the interim:

- rollup can still bypass lifecycle;
- dispatch can still commit-then-fail;
- schedule windows can still be missed/duplicated.

Do not claim full Release 1 state integrity for this reduced scope.

## 13. What still requires production evidence

- Max silent stage/chunk/finalization/DB wait.
- Max legitimate attempt runtime.
- Redis visibility/unacked/AOF behavior.
- S3-compatible multipart/listing/conditional behavior.
- Exports filesystem semantics.
- Production Postgres isolation/lock behavior.
- External path consumers.
- Source data mutability.

## 14. Conclusion

The six blockers now have concrete contracts, but no blocker has executable
evidence. The correct next step is P0, not Release 1 implementation. Full Release
1 remains **NOT READY** until P0, D9, D11 scope, code corrections, and
Postgres/Redis tests are complete.
