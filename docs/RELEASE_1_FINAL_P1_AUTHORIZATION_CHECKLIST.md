# Release 1 Final P1 Authorization Checklist

Status: **authorization package only.** P1 is **not authorized** by this
document. No migration, schema, API, frontend, dependency, deployment, or
production configuration was changed.

Current verdict: **HOLD — not authorization-ready.** The isolated rehearsal
passed 11/11 tests, but authorization is blocked until every MUST CLOSE BEFORE
P1 item in [`RELEASE_1_RELEASE_GATE_MATRIX.md`](./RELEASE_1_RELEASE_GATE_MATRIX.md)
is closed.

Documentation update: all 17 discrepancies are reconciled in
[`RELEASE_1_P1_DOCUMENTATION_RECONCILIATION.md`](./RELEASE_1_P1_DOCUMENTATION_RECONCILIATION.md).
The authoritative schema is in
[`RELEASE_1_P1_IMPLEMENTATION_SPECIFICATION.md`](./RELEASE_1_P1_IMPLEMENTATION_SPECIFICATION.md),
and the test plan is in
[`RELEASE_1_P1_IMPLEMENTATION_TEST_SPEC.md`](./RELEASE_1_P1_IMPLEMENTATION_TEST_SPEC.md).

Authorization model:

- **Gate A — engineering implementation:** isolated branch/test only, defined in
  [`RELEASE_1_P1_ENGINEERING_AUTHORIZATION.md`](./RELEASE_1_P1_ENGINEERING_AUTHORIZATION.md).
- **Gate B — production migration:** separately approved, defined in
  [`RELEASE_1_P1_PRODUCTION_AUTHORIZATION.md`](./RELEASE_1_P1_PRODUCTION_AUTHORIZATION.md).

## 1. Decisions for P1 closure

These are the final recommendations. Items marked "business" require the user's
explicit approval; none is silently approved.

| ID | Final recommendation | Approval | Closes before |
|---|---|---|---|
| D11 | **Full calendar+interval schedule ledger.** Include `0035` table and `jobs` window columns; defer `0035b` indexes to P7. | **Business: UNSIGNED** | P1 |
| D3 | **Strict checkpoint recovery.** Resume only on validated identity/lineage/fingerprint/artifact/store/no-gap; `completed_chunks=0` always restarts. | Technical: required | P1 (contract); P4 (code) |
| D8 | **600/60/60/3600/60 provisional defaults only.** Persist `progress_at`; final values measured before P2 enforcement. | Technical: required | P1 (accept provisional); P2 (final) |
| `ix_jobs_retry_of` | **Defer.** No P1 query; add a partial concurrent index when retry lineage is queried (P2/P9). | Technical: required | P1 |
| `ix_jobs_schedule_window_id` | **Defer.** No P1 query; add a partial concurrent index in P7. | Technical: required | P1 |
| `ix_jobs_s3_uploading` | **Defer.** No P1 query; add a partial concurrent index in P8. | Technical: required | P1 |
| `0035` / `0036` | **Only if D11 FULL:** include `0035`; set `0036.down_revision = "0035"`. If D11 REDUCED, exclude both. | **Blocked by D11** | P1 |
| P1/P2 boundary | **P1 is inert schema only.** P2 owns claim, fencing, heartbeat, progress, control phases, and all behavior. | Technical: required | P1 |

### 1.1 Why these decisions

- **D11 full ledger:** P0-09 validated the DB primitives. Reduced scope leaves
  interval schedules with duplicate/loss risk. The table is empty in P1, so
  inclusion is low-risk.
- **D3 strict:** P0-12 showed zero-committed checkpoints must restart; resuming
  them risks uncommitted bytes and duplicate/missing rows.
- **D8 provisional:** There is no production measurement of silent stages or
  maximum runtime. The numbers are defaults, not promises.
- **Index deferrals:** All three would be full indexes over mostly/all-NULL
  columns with no P1 query. Building them now adds cost and no P1 benefit.
- **0035 inclusion:** Keeps the revision graph linear and avoids a later
  dependency rewrite. `0035b` is deferred because no P1 code enforces windows.
- **P1/P2 split:** P1 must be deployable while old API/worker/scheduler versions
  run; any read or enforcement in P1 would break that compatibility.

## 2. Migration execution prerequisites

- [ ] `transaction_per_migration=True` implemented and approved.
- [ ] Exact revision graph approved:
      `0031 -> 0032 -> 0032b -> 0033 -> 0034 -> 0035 -> 0036`.
      `0035b` and `0036b` are deferred/optional.
- [ ] `0032` contains columns only; no indexes.
- [ ] `0032b` contains only the concurrent lease/owner/progress indexes.
- [ ] `0033`, `0034`, `0035`, `0036` are transactional schema revisions.
- [ ] `0035` contains no jobs indexes; `0035b` deferred to P7.
- [ ] No `CREATE INDEX CONCURRENTLY` runs before `transaction_per_migration=True`
      is active.
- [ ] Individual revision execution approved; no `upgrade head` in the P1 window.
- [ ] Concurrent-index validation and invalid-index recovery procedure tested.
- [ ] `lock_timeout` and `statement_timeout` initial values approved:
      3 s / 60 s metadata; 5 s / 900 s index (test values, not production).
- [ ] Production-sized copy measurement plan approved.
- [ ] Operator stop conditions approved.
- [ ] P1 migration files do not yet exist; this checklist is not implementation
      authorization.

## 3. Backup and recovery prerequisites

- [ ] Fresh production `pg_dump -Fc` taken immediately before the window.
- [ ] Dump non-zero and `pg_restore --list` exit 0.
- [ ] SHA-256 recorded.
- [ ] Dump copied off-host.
- [ ] Isolated restore rehearsal passed with measured duration.
- [ ] `LAST9_ENCRYPTION_KEY` available outside the backup.
- [ ] RPO accepted (dump-age) or PITR enabled.
- [ ] RTO target accepted, or explicitly waived for the P1 schema-only path.
- [ ] PITR decision recorded.
- [ ] Rollback/forward-fix/restore decision tree approved.
- [ ] Backup sidecar paused during the migration window.

See [`RELEASE_1_PRODUCTION_RECOVERY_READINESS.md`](./RELEASE_1_PRODUCTION_RECOVERY_READINESS.md).

## 4. Production compatibility prerequisites

- [ ] Old API/worker image tested against the migrated copy.
- [ ] No API response schema change.
- [ ] No worker task reads the new columns/tables.
- [ ] Scheduler/beat does not read `schedule_windows` or new columns.
- [ ] Background reaper/cleanup/S3 paths do not read new state.
- [ ] New tables remain empty.
- [ ] No P2 feature flag or behavior enabled in the P1 deployment.
- [ ] Planner changes from new indexes monitored.

## 5. Final authorization gate

| Item | Status |
|---|---|
| Architecture decisions | Recommended; awaiting approval |
| Migration mechanism | Rehearsed 11/11 |
| P1 revision split | Proposed; not implemented |
| Production-sized measurement | **Not done** |
| Production backup/restore | **Not done** |
| RPO/PITR decision | **Not approved** |
| P1 authorization | **Not granted** |
| P2 authorization | **Not granted** |

**Authorization rule:** P1 may begin only when every MUST CLOSE BEFORE P1 item in
[`RELEASE_1_RELEASE_GATE_MATRIX.md`](./RELEASE_1_RELEASE_GATE_MATRIX.md) is
closed and the user records explicit authorization below.

## 6. Authorization record

| Field | Value |
|---|---|
| Authorized phase | _none_ |
| Authorized by | _pending_ |
| Date | _pending_ |
| Scope | _none_ |
| Migration window | _pending_ |
| Migration owner | _pending_ |
| Evidence reference | _pending_ |

Until this table is completed by the user, P1 remains unauthorized.

## 7. Stop condition

This checklist is documentation only. Do not create migrations, modify `env.py`
or `deploy.sh`, execute migrations, or begin P1/P2.
