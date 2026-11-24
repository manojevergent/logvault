# Release 1 Final Decision Register

Status: **final approval register.** P0 has been executed. **P1 and every later
phase remain unauthorized.** No application source, schema, migration, API,
frontend, dependency, or deployment file was changed.

This register is authoritative over earlier readiness snapshots. Each decision
lists recommended decision, evidence, remaining assumptions, risks,
dependencies, required approval, implementation phase, and readiness.

Inputs:

- [`RELEASE_1_FINAL_ARCHITECTURE_APPROVAL.md`](./RELEASE_1_FINAL_ARCHITECTURE_APPROVAL.md)
- [`RELEASE_1_P1_SCOPE_AND_MIGRATION.md`](./RELEASE_1_P1_SCOPE_AND_MIGRATION.md)
- [`RELEASE_1_PRODUCTION_EVIDENCE_PLAN.md`](./RELEASE_1_PRODUCTION_EVIDENCE_PLAN.md)
- [`RELEASE_1_CELERY_REDIS_DECISION.md`](./RELEASE_1_CELERY_REDIS_DECISION.md)
- [`RELEASE_1_P0_EXECUTION_REPORT.md`](./RELEASE_1_P0_EXECUTION_REPORT.md)
- [`RELEASE_1_P0_TEST_RESULTS.md`](./RELEASE_1_P0_TEST_RESULTS.md)
- [`RELEASE_1_P0_FAILURE_ANALYSIS.md`](./RELEASE_1_P0_FAILURE_ANALYSIS.md)
- [`RELEASE_1_P0_CONFIGURATION_FINDINGS.md`](./RELEASE_1_P0_CONFIGURATION_FINDINGS.md)
- [`RELEASE_1_P0_FINAL_RECOMMENDATIONS.md`](./RELEASE_1_P0_FINAL_RECOMMENDATIONS.md)
- [`RELEASE_1_CHECKPOINT_RECOVERY_CONTRACT.md`](./RELEASE_1_CHECKPOINT_RECOVERY_CONTRACT.md)
- [`RELEASE_1_SCHEDULE_WINDOW_CONTRACT.md`](./RELEASE_1_SCHEDULE_WINDOW_CONTRACT.md)
- [`RELEASE_1_ARTIFACT_LIFECYCLE.md`](./RELEASE_1_ARTIFACT_LIFECYCLE.md)
- [`LEASE_AND_FENCING.md`](./LEASE_AND_FENCING.md)
- [`ARTIFACT_PUBLICATION.md`](./ARTIFACT_PUBLICATION.md)
- [`OUTBOX_AND_DISPATCH.md`](./OUTBOX_AND_DISPATCH.md)

## 1. Verdict and decision-level counts

**Overall: architecture conditionally ready; Gate A is HOLD. NOT READY for P2
behavior or production rollout.**

| Classification | Count | Meaning |
|---|---|---|
| READY | 0 | No decision is approved yet |
| ARCHITECTURE READY WITH CONDITIONS | 7 | D1/D2, D3, D8, D10, D13, A1, A2: approvable as inert P1 schema with later enforcement; this is architecture readiness only and does not grant or imply Gate A authorization |
| BUSINESS DECISION REQUIRED | 2 | D9 runtime limits/production Redis; D11 ledger scope |
| NOT READY | 1 | Production evidence: real S3, runtime/silent-stage, Redis capacity, slot occupancy, canonical consumers, integration |
| INFORMATIONAL | 1 | P0 validation |

P0 evidence is **partial**: 19 harness tests, 18 passed, 1 failed, 2 manual AOF
passes, 1 blocked real-S3 area. No P0 result proves production timing, Redis
capacity, or real-provider S3 behavior. No decision above is silently approved.

## 2. Decision summary

| ID | Decision | Recommended decision | Readiness | Approval | Phase |
|---|---|---|---|---|---|
| D1/D2 | Cancellation and pause semantics | Immediate status for compatibility + request timestamps + derived `phase`; owner/token is the internal truth | Conditional | Required | P1/P2/P3 |
| D3 | Checkpoint recovery | **Final recommendation:** strict validated resume; `completed_chunks=0` restarts; manual fail on unknown/unsafe | Conditional | Required | P1/P4 |
| D8 | Lease and progress configuration | **Final recommendation:** 600/60/60/3600/60 as provisional defaults only; measured before P2 enforcement | Conditional | Required | P2/P6 |
| D9 | Celery/Redis and DB recovery | Option C: Postgres authority + mandatory lease-expiry re-dispatch + visibility backstop; limits after measurement | Conditional | **Required** | P2/P6/P9 |
| D10 | Completion integrity and UI | Minimum completion fields + group/report/job partial; no seventh status | Conditional | Required | P1/P2/P3 |
| D11 | Calendar and interval schedule ledger | **Final recommendation:** full calendar+interval ledger; include `0035`, defer `0035b` | **Business: UNSIGNED** | **Required** | P1/P7 |
| D13 | Database constraints | Audit existing data, then add CHECKs; no strict owner check | Conditional | Required | P9 |
| A1 | Artifact paths and publication | Attempt-scoped local/S3 + guarded DB pointer | Conditional | Required | P1/P4/P8 |
| A2 | Cleanup and deletion ownership | Never delete active/published/rollup-needed/checkpoint-needed; orphan scan | Conditional | Required | P4/P7/P8 |
| P0 | Test foundation | Complete as validation; one failure changes D9 | Informational | Done | P0 |

### 2.1 Decisions explicitly **not** approved

- D9 soft/hard runtime limits (23 h/24 h are proposals only).
- D9 production Redis eviction/persistence/capacity settings.
- D11 full-vs-reduced ledger scope.
- D10 partial-result product/UI behavior.
- Any production migration execution.
- P1 implementation itself.

### 2.2 Final P1 closure decisions

These are **recommendations for approval**, not silent approvals. The business
items still require the user's explicit decision.

| Decision | Final recommendation | Must be final before | Notes |
|---|---|---|---|
| D11 ledger | **Full calendar+interval ledger.** Include `0035` (table + `jobs` window columns) and defer `0035b` jobs indexes to P7. | **P1** (business) | Avoids reduced-scope interval duplicate/loss risk and avoids a later revision-graph rewrite. |
| D3 checkpoint | **Strict matrix.** Resume only on validated identity/lineage/fingerprint/artifact/store/no-gap; `completed_chunks=0` always restarts. | **P1** (contract) | P0-12 evidence; implementation in P4. |
| D8 timing | **600/60/60/3600/60 provisional defaults only.** Not production-approved. | **P1** (accept as provisional) | Final values before P2 enforcement, from measurement. |
| `ix_jobs_retry_of` | **Do not create in P1.** Add partial concurrent index when retry query exists (P2/P9). | **P1** (deferral approval) | Full all-NULL index is waste. |
| `ix_jobs_schedule_window_id` | **Do not create in P1.** Add partial concurrent index in P7. | **P1** (deferral approval) | Full all-NULL index is waste. |
| `ix_jobs_s3_uploading` | **Do not create in P1.** Add partial concurrent index in P8. | **P1** (deferral approval) | No P1 query. |
| `0035` / `0036` graph | **Include `0035`; `0036.down_revision = "0035"`.** If D11 REDUCED, exclude both `0035` and `0036`. | **P1** | No broken chain. |
| P1 vs P2 | **P1 is inert schema only.** P2 owns claim/fence/heartbeat/control enforcement. | **P1** | No API/worker/UI read of new state in P1. |

**Status: UNSIGNED.** See
[`RELEASE_1_D11_BUSINESS_APPROVAL_RECORD.md`](./RELEASE_1_D11_BUSINESS_APPROVAL_RECORD.md).
`0035`/`0036` are not authorized until the business owner signs FULL or REDUCED.

#### 2.2.1 Must be finalized before P1

- D11 full-vs-reduced ledger scope.
- D3 strict contract acceptance.
- D8 provisional defaults acceptance and measurement plan.
- Deferral of the three indexes.
- `0035` inclusion and `0036` dependency.
- P1/P2 boundary and no-behavior rule.
- Migration execution requirements (TPM, split revisions, timeouts).
- Fresh verified backup and restore rehearsal.
- Production-sized copy measurement.
- Explicit P1 authorization.

#### 2.2.2 Safe to finalize before P2 or later

- Final lease/heartbeat/progress values (D8) — before P2 enforcement.
- Final runtime hard/soft limits (D9) — before P2/P6 or production.
- Production Redis eviction/persistence tuning — before production activation.
- D10 partial-result UI/product behavior — before P3 or production activation.
- D13 CHECK constraints — P9.
- `0035b` schedule unique indexes — P7.
- `ix_jobs_retry_of` — P2/P9.
- `ix_jobs_schedule_window_id` — P7.
- `ix_jobs_s3_uploading` — P8.
- Bounded execution units / external watchdog — future.
- Real S3 provider and canonical consumer evidence — P4/P8/production.
- Full lifecycle/API/frontend suite — production activation.

## 3. Phase map

| Phase | Scope | Decisions activated |
|---|---|---|
| P0 | Test harness and primitive validation | done |
| P1 | Additive schema/state primitives only | D1/D2 fields, D3 fields, D8 columns, D10 fields, A1 pointers, D11 tables, D9 support columns |
| P2 | Claim, fencing, heartbeat, guarded writes, control phases | D1/D2 enforcement, D3 validation, D8 renewal, D9 claim/fence |
| P3 | Completion classification + group/report/UI | D10 derivation/UI, D1/D2 phase display |
| P4 | Attempt artifacts, store, checkpoint validation | A1 attempt paths, A2 cleanup rules, D3 execution |
| P5 | Rollup lifecycle | A1 source/destination paths, A2 ownership |
| P6 | Outbox + dispatcher + lease-expiry reconciler | D9 recovery, D8 progress timeout |
| P7 | Schedule ledger + beat singleton | D11, A2 ledger cleanup |
| P8 | S3 attempt publication | A1 S3 pointers, A2 S3 cleanup |
| P9 | Retry lineage, constraints, hardening | D13, D9 runtime limits, A2 orphan scan |

## 4. Decision detail

### D1/D2 - Cancellation and pause semantics

| Field | Detail |
|---|---|
| Recommended decision | Keep immediate `paused`/`canceled` statuses for API compatibility. Add `pause_requested_at` and `cancel_requested_at`. Add derived `phase` (`claiming`/`running`/`pausing`/`canceling`/`finalizing`) and `is_finalizing`. Withhold download while finalizing. Internal guards use `owner_id` + `lease_token`, never status alone. |
| Evidence | `api/app/routers/jobs.py:829-865` writes pause/cancel status immediately; `_DOWNLOADABLE` includes paused/canceled; group cancel writes canceled directly. No request timestamps exist today. P0-06 (cancel dominance) and P0-07 (pause/resume fence) passed at the SQL level. |
| Assumptions | API consumers tolerate the same status vocabulary plus additive fields. UI can derive phase. A paused job may still have a live worker finishing the current chunk. |
| Risks | A status-only consumer assumes no writer. Downloading a partially written file. Report/group counts treat paused as final. Old worker overwrites a new status without a token guard. |
| Dependencies | P1 columns; P2 guarded terminal writes; P3 UI derivation. |
| Approval required | Yes: confirm additive request fields + derived phase, not new statuses. |
| Phase | P1 (fields), P2 (enforcement), P3 (display). |
| Readiness | Conditional. |

### D3 - Checkpoint recovery

| Field | Detail |
|---|---|
| Recommended decision | Resume only when all hold: supported checkpoint version, `completed_chunks > 0`, job/lineage match, fingerprint match, artifact exists and is not a zip, file size >= offset, store marker >= `completed_chunks - 1`, no skipped-batch gap, offsets in range. Otherwise restart. Manual fail on unknown schema, path escape, or unrecoverable IO. |
| Evidence | P0-12 passed the full crash matrix after correcting one ambiguity: a checkpoint row with `completed_chunks=0` must **restart**. Resume worked after DB commit and after store-ahead; restart worked before/after fsync, missing artifact, checkpoint-newer-than-artifact, fingerprint mismatch, and partial gap. All final cases produced exactly 9 rows and store `[9,9]`. |
| Assumptions | Source data in a completed prefix is immutable. The store marker is trustworthy. Chunk identity is stable. |
| Risks | Tail-only artifact. Duplicate or missing committed rows. Cross-job checkpoint adoption. Resume over mutable source data. Store-ahead can double-count if the marker is not validated. |
| Dependencies | P1 `spec_fingerprint`/`checkpoint_version`/`store_path`; P4 runner/store changes; P2 fencing. |
| Approval required | Yes: approve the strict matrix, especially zero-commit restart. |
| Phase | P1 (fields), P4 (enforcement). |
| Readiness | Conditional; contract updated with P0 evidence. |

### D8 - Lease and progress configuration

| Field | Detail |
|---|---|
| Recommended decision | Persist `lease_expires_at`, `heartbeat_at`, `progress_at`. Provisional values: lease 600 s, heartbeat 60 s, reclaim grace 60 s, progress timeout 3600 s, reaper grace 60 s. Renew the lease only when progress is observed. Treat all five values as **unapproved defaults** until measured. |
| Evidence | P0-03 passed healthy-vs-expired lease reclaim. P0-04 passed progress-gated renewal. P0-05 passed stale-only reaping. Current source has a 300 s heartbeat and 10 s status polling; Last9 chains can run ~18 min; no progress instrumentation exists. P0-13 shows a long task can be silent from the broker's point of view. |
| Assumptions | A legitimate job can be silent for less than the progress timeout. DB clock is authoritative. Writes are cheap enough for 60 s heartbeats. |
| Risks | A healthy worker is fenced during a long silent stage. A hung worker holds a slot. DB/Redis outage causes false expiry. Heartbeat writes add pool pressure at high concurrency. |
| Dependencies | P2 progress clock; P6 reconciler; production measurements. |
| Approval required | Yes: accept provisional values and the measurement plan. |
| Phase | P1 (columns), P2 (renewal), P6 (reconciler), P9 (tuning). |
| Readiness | Conditional; values **not** production-approved. |

### D9 - Celery/Redis and database recovery

| Field | Detail |
|---|---|
| Recommended decision | **Option C.** PostgreSQL is execution authority. Celery/Redis is transport. Make a **DB lease-expiry re-dispatch reconciler** a Release 1 requirement. Claim before execution. Fence every write with `lease_token`. Use the outbox for durable dispatch. Treat visibility timeout as a backstop only. Add a configurable soft/hard attempt limit after measurement. Use `ignore_result` or a result expiry longer than the maximum attempt. |
| Evidence | **P0-13 FAILED:** visibility 5 s did not redeliver a 10 s task while two solo workers were already running; Redis kept it unacked for 18 s. **P0-13b PASSED:** a new worker restored the unacked task and produced a duplicate start. P0-14 passed SIGKILL + new-worker redelivery. P0-15 passed `self.retry`/ETA. P0-16 passed a 3 s hard limit (child killed). P0-18 passed SIGTERM warm shutdown for a 5 s task. P0-AOF-01/02 passed key and queued-message persistence across restart. Kombu 5.4.2 `restore_visible` is poll/startup-triggered and runs every 10th call, not a wall-clock timer. |
| Assumptions | The reconciler can query expired leases reliably. The outbox is available before P2 enforcement. Duplicate starts are tolerable if fenced. A hard limit is acceptable for the longest legitimate job. |
| Risks | Duplicate starts consume slots. A stuck process can hold a slot indefinitely. Hard kill forces replay from checkpoint. Redis unacked growth under long jobs. Result expiry loses observability. Visibility-based recovery silently fails. |
| Dependencies | P0 evidence (done); P1 support columns/outbox table; P2 claim/fence; P6 outbox/reconciler; business runtime decision; production Redis/S3 measurements. |
| Approval required | Yes: approve Option C, the mandatory reconciler, and the runtime-limit policy (values may be deferred with accepted slot risk). |
| Phase | P1 (schema only), P2/P6 (behavior), P9 (limits/constraints). |
| Readiness | Conditional; **business decision required for limits and production Redis**. |

### D10 - Completion integrity and UI

| Field | Detail |
|---|---|
| Recommended decision | Persist `completion_state` (`unknown`/`complete`/`partial`), `gap_count`, `gap_reason`. Set them in the terminal guarded write. Derive partial in group/report/job responses and UI. Keep partial jobs downloadable with an explicit partial badge/header. Do not add a seventh status. |
| Evidence | `worker/app/runner.py:860-872` records skipped batches; `worker/app/rollup.py:212-241` skips sources; reports/groups ignore partial; web `Job` model lacks the fields. P0-12 produced exact committed rows but did not exercise UI/report derivation. |
| Assumptions | A partial job is still useful and should remain downloadable. Group/report status can be derived from jobs. |
| Risks | Partial data presented as clean. Customer decisions on incomplete data. UI inconsistency between job/group/report. A seventh status would break consumers. |
| Dependencies | P1 columns; P2 terminal writes; P3 derivation/UI. |
| Approval required | Yes: approve minimum fields and partial UI behavior. |
| Phase | P1 (fields), P2 (writes), P3 (UI/report). |
| Readiness | Conditional; **product/UI behavior needs approval**. |

### D11 - Calendar and interval schedule ledger

| Field | Detail |
|---|---|
| Recommended decision | Use one `schedule_windows` ledger for both calendar and interval schedules. Stable identity: `day:YYYY-MM-DD` for calendar, `slot:<epoch>` for interval. Store `scheduled_for`, start/end, status, completion, attempts/backoff, `current_job_id`, and `config_snapshot`. Enforce one window per `(schedule_id, window_key)` and one active job per window. |
| Evidence | P0-09 passed the DB primitives: two concurrent scans produced one window insert, Redis scan lock had one winner, duplicate dispatch produced one winner, failed-to-pending retry worked, one active job per window held, config snapshot stayed at v1 after a schedule update, and delete/cancel worked. It did **not** test the production scheduler, reports, or rollup. Current source: `_early_extracted` is status-blind; `last_run_at` is written before dispatch; interval start is rolling; no timezone field; model IST drift; reports key by `created_at`. |
| Assumptions | Calendar and interval can share one ledger shape. A stable slot key is acceptable. `config_snapshot` captures everything needed to reproduce a window. |
| Risks | Lost days. Duplicate extraction. Duplicate reports/rollups. Mixed ledger + legacy truth. Timezone drift. Reduced scope leaves interval duplicate/loss risk. |
| Dependencies | P1 tables; P4 config snapshot/artifacts; P6 outbox; P7 scheduler/report/rollup integration. |
| Approval required | **Yes: business scope decision (full vs reduced).** |
| Phase | P1 (tables), P7 (behavior). |
| Readiness | **Business decision required.** |

### D13 - Database constraints

| Field | Detail |
|---|---|
| Recommended decision | Audit existing `jobs.status`, `completion_state`, and `schedule_windows.status` values first. Then add CHECK constraints in P9. Do not add a strict `status='running' => owner_id IS NOT NULL` check during the mixed-version period. |
| Evidence | No CHECK constraints exist today. Six-status vocabulary. Legacy/manual rows may contain unexpected values. Tests mostly use SQLite, which behaves differently from Postgres. |
| Assumptions | A preflight audit finds no invalid production values, or they can be corrected. |
| Risks | Migration failure on invalid data. Mixed-version writers violate a new constraint. Rollback needs constraint drops. |
| Dependencies | P9; production preflight query; all writers on the new version. |
| Approval required | Yes: accept audit-then-CHECK and deferral to P9. |
| Phase | P9. |
| Readiness | Conditional. |

### A1 - Artifact paths and publication

| Field | Detail |
|---|---|
| Recommended decision | Write local artifacts to attempt-scoped paths (`job_<id>.a<token>.*`). Set the DB pointer only through a guarded update. Add `jobs.store_path`. Use attempt-scoped S3 prefixes and a published-attempt pointer. Never rename a shared canonical file into place. |
| Evidence | P0-10 passed byte isolation for two attempts. P0-11 passed unique-key/pointer/cleanup logic on a **P0 HTTP S3 stub**. Current code uses canonical paths in `worker/app/runner.py:151-180`, `rollup.py:285`, `scheduler.py:322`, `api/app/routers/customers.py:73-86`, and shared S3 keys in `worker/app/s3.py:97-179`. |
| Assumptions | External consumers read paths from the DB or can be migrated. Attempt files are safe to orphan. Disk capacity covers retained attempts. |
| Risks | Concurrent CSV/store corruption. Orphan leaks. External canonical-path consumers break. S3 provider behavior differs from the stub. |
| Dependencies | P2 fencing; P4 paths/checkpoint; P5 rollup; P8 S3; P1 columns. |
| Approval required | Yes: approve attempt-scoped migration and pointer publication. |
| Phase | P1 (columns), P4 (local), P5 (rollup), P8 (S3). |
| Readiness | Conditional; **real S3 provider unverified**. |

### A2 - Cleanup and deletion ownership

| Field | Detail |
|---|---|
| Recommended decision | Never delete active attempts, published artifacts, rollup-needed stores, or checkpoint-needed files. Delete only unreferenced attempt files after retention/grace. Coordinate S3 deletion with `s3_uploading_at`/published attempt. Null all path columns on customer delete. Clean ledger/outbox rows deliberately. |
| Evidence | P0-17 passed the ownership-selection model. `delete_job_files` races S3 retries; customer delete has no ledger coordination; low-disk cleanup misses unmatched files; canonical cleanup exists in `scheduler.py`. P0-11 showed cleanup preserving the current attempt on the stub. |
| Assumptions | An orphan scan is affordable. Retention/grace is configurable. Published S3 objects are never auto-deleted. |
| Risks | Data loss, broken downloads, dangling paths, disk leaks, ledger references to deleted files. |
| Dependencies | P4 attempt paths; P7 ledger; P8 S3. |
| Approval required | Yes: approve ownership rules and orphan-scan approach. |
| Phase | P4/P7/P8 (P9 orphan scan). |
| Readiness | Conditional. |

### P0 - Test foundation

| Field | Detail |
|---|---|
| Recommended decision | Accept P0 as complete validation evidence, with one failed test and one blocked area. Do not treat it as production approval. |
| Evidence | 19 harness tests: 18 pass, 1 fail (`P0-13`). 2 manual AOF passes. Real S3 blocked. Artifacts under `p0/results/`. |
| Assumptions | P0's scratch tables/models faithfully represent the proposed SQL shapes. |
| Risks | Scratch models differ from production ORM/session behavior. Visibility failure is environment-specific (though consistent with Kombu source). Stub S3 hides provider behavior. |
| Dependencies | None. |
| Approval required | Informational; the consequence is the D9 change. |
| Phase | P0 (done). |
| Readiness | Complete as validation, not clean. |

## 5. Critical blockers

1. D9's mandatory DB re-dispatch reconciler is accepted in design but **not
   approved for implementation**.
2. D9 runtime limits are **unmeasured** and **unapproved**.
3. D11 ledger scope is a **business decision**.
4. Real S3-compatible provider behavior is **unverified**.
5. Production timing, Redis capacity, Postgres isolation, stop grace, and
   canonical-path consumers are **unmeasured**.
6. P1 is **not authorized**.

## 6. Evidence still required

### Before P1

- Additive migrations `0032`–`0036` apply and downgrade on a Postgres 16 copy.
- No API/worker read/write behavior changes after migration.
- Rollback rehearsal.
- No CHECK constraints or runtime flags introduced.

### Before P2

- Real S3-compatible provider, or an approved equivalent, for multipart,
  conditional writes, IAM, versioning, and listing.
- Production-like Postgres claim/fence/lease concurrency.
- Runtime distribution baseline and longest legitimate silent stage.

### Before production

- Final soft/hard limits and progress timeout.
- Redis AOF/eviction/memory headroom and unacked growth.
- Worker slot occupancy and stuck-slot operational cost.
- Docker stop grace for long tasks.
- Canonical-path external consumer inventory/migration.
- Schedule/report/rollup winner-selection integration.
- Full T1–T24 lifecycle/API/frontend suite.

## 7. Acceptance criteria

- Exactly one worker claims a job; stale tokens write 0 rows and abort before
  side effects.
- Cancel dominates completion; pause/resume cannot create two writers.
- Every resumable checkpoint satisfies the full D3 matrix; `completed_chunks=0`
  restarts.
- Partial results are visible everywhere and never displayed as clean.
- One window per key; failed/missing/partial windows are handled; no duplicate
  winner; reports select one winner.
- Outbox is durable; duplicate messages execute once at the DB gate.
- One published S3 attempt per job; cleanup never deletes it.
- Reconciler re-dispatches expired running jobs with capped attempts/backoff.
- A worker killed at any stage recovers without missing or duplicate committed
  chunks.
- Migrations and rollback are rehearsed on Postgres; old/new worker gates are
  followed.
- Alerts cover leases, progress, outbox, schedules, checkpoints, S3, cleanup,
  beat lock, and duplicate delivery.

## 8. Stop condition

This register stops at documentation. P1 must not begin until the user
explicitly authorizes it. No production migration may be executed without a
separate approval.
