# Release 1 P1 Final Go/No-Go

Status: **decision document.** No migration was created or executed. No code,
schema, API, frontend, dependency, or deployment configuration was changed.
**P1 remains unauthorized.**

**Historical decision note:** this document is superseded for current
authorization by `RELEASE_1_P1_FINAL_GO_NO_GO_CHECKLIST.md` and
`RELEASE_1_GATE_A_CANONICAL_REGISTER.md`. Its original content is retained.

**Rehearsal update:** the isolated execution rehearsal passed 11/11 tests. It
confirmed per-revision commit behavior, concurrent-index failure/retry, process
termination, lock timeout, and statement timeout. It also found that
`autocommit_block` commits preceding revisions when
`transaction_per_migration=False`; TPM must be enabled before any autocommit
index revision. See
[`RELEASE_1_P1_MIGRATION_REHEARSAL_REPORT.md`](./RELEASE_1_P1_MIGRATION_REHEARSAL_REPORT.md).

**Final closure:** the authorization package is in
[`RELEASE_1_FINAL_P1_AUTHORIZATION_CHECKLIST.md`](./RELEASE_1_FINAL_P1_AUTHORIZATION_CHECKLIST.md),
with gate classifications in
[`RELEASE_1_RELEASE_GATE_MATRIX.md`](./RELEASE_1_RELEASE_GATE_MATRIX.md) and
recovery readiness in
[`RELEASE_1_PRODUCTION_RECOVERY_READINESS.md`](./RELEASE_1_PRODUCTION_RECOVERY_READINESS.md).

Inputs:

- [`RELEASE_1_P1_MIGRATION_EXECUTION_STRATEGY.md`](./RELEASE_1_P1_MIGRATION_EXECUTION_STRATEGY.md)
- [`RELEASE_1_P1_LOCK_AND_INDEX_STRATEGY.md`](./RELEASE_1_P1_LOCK_AND_INDEX_STRATEGY.md)
- [`RELEASE_1_P1_MIGRATION_SEQUENCE.md`](./RELEASE_1_P1_MIGRATION_SEQUENCE.md)
- [`RELEASE_1_P1_BACKUP_AND_RECOVERY_PLAN.md`](./RELEASE_1_P1_BACKUP_AND_RECOVERY_PLAN.md)
- [`RELEASE_1_P1_MIGRATION_SAFETY_PREFLIGHT.md`](./RELEASE_1_P1_MIGRATION_SAFETY_PREFLIGHT.md)

## 1. Consolidated verdict

**NO-GO for the current one-shot `alembic upgrade head` P1 bundle.**

**CONDITIONAL GO for the redesigned P1**, after:

- per-revision transactions and execution;
- split schema/index revisions;
- concurrent indexes for existing-table indexes;
- bounded lock/statement timeouts;
- fresh verified backup and restore test;
- production-sized copy measurement;
- explicit D11 decision and P1 authorization.

This is a **migration-mechanism** verdict. It is **not** a production-readiness
claim. Production readiness still requires the evidence in
[`RELEASE_1_PRODUCTION_EVIDENCE_PLAN.md`](./RELEASE_1_PRODUCTION_EVIDENCE_PLAN.md).

## 2. Verdict by migration

| Revision | Contents | Risk after redesign | Verdict |
|---|---|---|---|
| `0032` | ownership/completion columns only | Medium (brief `ACCESS EXCLUSIVE`) | **CONDITIONAL GO** |
| `0032b` | lease/owner/progress concurrent indexes | Low-Medium (index build) | **CONDITIONAL GO** |
| `0033` | artifact/checkpoint columns | Low | **GO** |
| `0034` | outbox table + new-table indexes | Low | **GO** |
| `0035` | schedule table + jobs window columns + new-table indexes | Medium (brief `ACCESS EXCLUSIVE`) | **CONDITIONAL GO only if D11 FULL** |
| `0035b` | schedule unique/partial indexes | Low-Medium | **DEFER to P7** |
| `0036` | S3 attempt columns | Low | **CONDITIONAL GO only if D11 FULL; excluded if REDUCED** |
| `0036b` | S3 partial index | Low | **DEFER to P8 or optional** |
| `ix_jobs_retry_of` | full index over all-NULL column | Avoidable | **DO NOT CREATE in P1** |
| `ix_jobs_schedule_window_id` | full index over all-NULL column | Avoidable | **DO NOT CREATE in P1** |

### 2.1 Why `0032` remains conditional

The columns are metadata-only, but `ALTER TABLE` still takes `ACCESS
EXCLUSIVE`. It is safe only if:

- `0032` contains **no indexes**;
- it runs in its own transaction;
- `lock_timeout` is bounded;
- a production-sized copy has been measured;
- old API/worker compatibility is confirmed.

### 2.2 Why `0032b` remains conditional

`CREATE INDEX CONCURRENTLY` avoids write blocking but:

- requires `autocommit_block` or an external step;
- can leave an invalid index;
- can wait on long transactions;
- can exceed the statement timeout.

It is safe only with catalog validation and a tested retry procedure.

### 2.3 Why `0035` is conditional

It adds two columns to `jobs` and a new table. It is safe if D11 includes the
ledger, the revision contains no jobs indexes, and the same lock controls apply.
If D11 REDUCED, exclude both `0035` and `0036`; graph becomes
`0031 -> 0032 -> 0032b -> 0033 -> 0034`.

### 2.4 Why the schedule indexes are deferred

`ix_jobs_schedule_window_id` is a full index over an all-NULL column with no P1
query. `uq_jobs_schedule_attempt` and `uq_jobs_schedule_active` enforce future
P7 behavior but are not read in P1. Build them in P7 (concurrently) unless the
P1 contract explicitly requires the uniqueness now.

## 3. Production compatibility

### 3.1 API

- `JobOut` and all response schemas remain unchanged in P1.
- No router reads or writes the new columns/tables.
- SQLAlchemy selects explicit model columns; no `SELECT *` on `jobs` was found.
- Old API processes ignore the new columns and receive DB defaults.

### 3.2 Worker

- `worker/app/db.py` uses explicit column lists.
- Old workers insert/update only known columns; new columns receive defaults.
- No task reads the new tables or columns in P1.
- If P1 adds model declarations, the worker Core mirror must match; behavior
  must remain inert.

### 3.3 Scheduler and beat

- The embedded beat (`celery worker -B`) scans `schedules` and `jobs`; it does
  not read `schedule_windows` or the new columns in P1.
- Schedule behavior is unchanged; no rows are inserted into the new tables.
- During `ALTER TABLE`, scheduler scans may block briefly; this is why the
  window and lock timeout matter.

### 3.4 Background jobs

- Reaper, cleanup, health, and S3 retry paths do not read the new fields/tables
  in P1.
- New indexes may change plans for existing queries; monitor, but no correctness
  change.
- Unique indexes are safe while the new key columns are NULL.

### 3.5 What must not happen in P1

- No API field exposure.
- No worker task reads the new columns.
- No outbox row creation or dispatch.
- No schedule scanning or window creation.
- No attempt-path selection.
- No S3 attempt publication.
- No feature flag enabled.
- No P2 behavior.

## 4. Remaining blockers

### 4.1 Mandatory before P1 authorization

1. **Execution model change approved.** `transaction_per_migration=True` and/or
   per-revision invocation; no `upgrade head`.
2. **Revision split approved.** `0032` columns only; `0032b` indexes; optional
   `0035b`/`0036b`.
3. **Index decisions approved.** Partial lease/progress/owner; defer
   `retry_of`, `schedule_window_id`, S3 index.
4. **Lock/timeout policy approved.** Initial test values and measurement plan.
5. **D11 decided.** Include `0035` or adjust `0036.down_revision`.
6. **Fresh backup + restore test.** Verified, off-host, encryption key.
7. **Production-sized copy measurement.** Lock wait, duration, index validity.
8. **Old API/worker compatibility test.** Against the migrated copy.
9. **Rollback rehearsal.** P1-only downgrade and index recovery.
10. **Explicit P1 authorization.** P1 is still not authorized.

### 4.2 Required before production rollout

- Final `lock_timeout`/`statement_timeout` from measurement.
- Production runtime/lease/progress values (D8/D9).
- Real S3 provider evidence (P8).
- Redis capacity/eviction evidence.
- Canonical-path consumer inventory.
- Schedule/report/rollup integration.
- Full lifecycle/API/frontend suite.

These do not block P1 schema, but they block production behavior.

## 5. Authorization checklist

### Scope

- [ ] P1 schema-only boundary approved.
- [ ] D11 decision recorded.
- [ ] Index deferrals approved.
- [ ] No P2 behavior in the P1 deployment.

### Execution

- [ ] `transaction_per_migration=True` approved (future env.py change).
- [ ] Per-revision invocation procedure approved.
- [ ] `0032` split into columns and indexes.
- [ ] Concurrent index revisions approved with `autocommit_block` or external
      step.
- [ ] `lock_timeout`, `statement_timeout`, retry/abort policy approved.
- [ ] Do not use `upgrade head` in the P1 window.

### Evidence

- [ ] Production-sized copy measured.
- [ ] Lock wait/duration recorded per revision.
- [ ] `pg_index.indisvalid=true` for all indexes.
- [ ] Old API/worker smoke passes.
- [ ] No API/task behavior change.

### Backup and recovery

- [ ] Fresh dump verified with `pg_restore --list`.
- [ ] Restore to scratch tested.
- [ ] Dump off-host; checksum recorded.
- [ ] Encryption key available.
- [ ] Restore duration measured.
- [ ] Forward-fix/downgrade/restore decision tree approved.
- [ ] Backup sidecar paused during the window.

### Operations

- [ ] Migration owner and window named.
- [ ] Monitoring for locks, connections, API errors, worker health.
- [ ] Rollback rehearsal recorded.
- [ ] Explicit user authorization recorded.

## 6. Final decision

| Question | Answer |
|---|---|
| Is the current P1 bundle safe? | **No.** One transaction holds `ACCESS EXCLUSIVE` on `jobs` for the bundle. |
| Is redesigned P1 safe to authorize? | **Conditionally yes**, after the checklist and measurements. |
| Does P1 change application behavior? | **No**, if the schema-only boundary is respected. |
| Does P1 require a production-sized test? | **Yes.** The 25 MB sample is not sufficient. |
| Does P1 require PITR? | Not for schema safety, but dump-only RPO must be accepted or PITR enabled. |
| Can P1 start now? | **No.** P1 authorization has not been granted. |

## 7. Stop condition

This is the final P1 strategy decision document. No migration, index, schema,
code, or configuration change was made. **P1 remains unauthorized.** Await
explicit authorization.
