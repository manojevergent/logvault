# Release 1 P1 Final GO/NO-GO Checklist

Status: **decision checklist only.** P1 is not authorized. No code, migration,
schema, API, frontend, dependency, deployment, or production setting was changed.

Gate A A-14 and canonical action/evidence IDs are defined in
`RELEASE_1_GATE_A_CANONICAL_REGISTER.md`. A-14 is inside the A-01..A-14
blocking range.

Decision rule: P1 may be recommended for authorization only when **every**
mandatory item below is VERIFIED or APPROVED with objective evidence. A checked
box based only on documentation is not sufficient.

## 1. Current verdict

**NO-GO for P1 authorization.**

Reason: 6 of 28 P1 blockers are approved; none of the migration-engineering,
production-measurement, backup/restore, or authorization gates is closed.

| Status | Count |
|---|---|
| APPROVED | 6 |
| EVIDENCE READY | 8 |
| IN PROGRESS | 1 |
| NOT STARTED | 6 |
| BLOCKED | 7 |
| VERIFIED | 0 |
| **Closed (APPROVED + VERIFIED)** | **6/28** |

Source: [`RELEASE_1_P1_EXECUTION_TRACKER.md`](./RELEASE_1_P1_EXECUTION_TRACKER.md).

## 2. Mandatory GO criteria

### A. Decisions and scope

- [ ] G-01 D11 full ledger recorded, including `0035` inclusion.
- [ ] G-02 D3 strict checkpoint contract accepted, including zero-commit restart.
- [ ] G-03 D8 provisional timing accepted with a measurement plan.
- [ ] G-04/G-05/G-06 index deferrals approved.
- [ ] G-07 graph finalized: `0031 -> 0032 -> 0032b -> 0033 -> 0034 -> 0035 -> 0036`.
- [ ] G-08 P1/P2 boundary signed: P1 inert schema only.

### B. Migration engineering

- [ ] G-10 `transaction_per_migration=True` implemented and reviewed.
- [ ] G-11 revisions created with the exact responsibilities:
      `0032` columns; `0032b` indexes; `0033` columns; `0034` outbox;
      `0035` ledger + columns; `0036` S3 columns.
- [ ] G-12 TPM-before-autocommit proven on the actual revisions.
- [ ] G-14 concurrent indexes validate `indisvalid=true`.
- [ ] G-15 invalid-index drop/rebuild drill passed.
- [ ] G-19 API and worker mirrors match; no runtime reads.
- [ ] G-13 individual revision execution approved; no `upgrade head`.
- [ ] G-18 stop conditions approved.
- [ ] G-16 initial and measured timeout values approved.

### C. Production-sized measurement

- [ ] G-17 production-sized row counts, table/index sizes, and TOAST recorded.
- [ ] G-17 baseline transaction/lock behavior recorded.
- [ ] G-17 per-revision duration and lock wait measured.
- [ ] G-17 index build duration and validity measured.
- [ ] G-17 API/worker impact measured.
- [ ] G-16 final `lock_timeout` and `statement_timeout` derived from evidence.
- [ ] Measurement fits the approved change window.

### D. Backup and recovery

- [ ] G-20 backup sidecar pause procedure approved.
- [ ] G-21 fresh production dump taken; non-zero size.
- [ ] G-22 `pg_restore --list` exit 0; SHA-256 recorded.
- [ ] G-23 off-host copy exists; checksum matches.
- [ ] G-24 production-sized isolated restore passed; duration measured.
- [ ] G-25 encryption key available outside the backup; decrypt check passed.
- [ ] G-26 RPO approved.
- [ ] RTO target approved, or explicitly waived for the P1 schema-only path.
- [ ] G-28 PITR decision recorded; if enabled, restore tested.
- [ ] G-29 P1 forward-fix/downgrade/restore rehearsal passed on a production-sized copy.

### E. Operational readiness

- [ ] G-13 final operator runbook approved.
- [ ] G-18 stop/recovery actions approved.
- [ ] Named migration owner and DBA/operations contacts recorded.
- [ ] Change window approved.
- [ ] Monitoring for locks, connections, API errors, and worker health ready.
- [ ] Rollback owner and decision authority named.

### F. Authorization

- [ ] G-09 explicit P1 authorization recorded.
- [ ] No P2 behavior is enabled in the P1 deployment.
- [ ] The authorization record names scope, window, owner, and evidence.

## 3. Mandatory NO-GO conditions

P1 is automatically NO-GO if any of these is true:

- `transaction_per_migration=True` is absent.
- `0032` or `0035` still contains indexes; `0036` still contains the S3 index.
- `ix_jobs_retry_of`, `ix_jobs_schedule_window_id`, or
  `ix_jobs_s3_uploading` remains in P1.
- The runbook still uses `upgrade head`.
- A P1 index is invalid after creation.
- Production-sized measurement is absent.
- The fresh dump is missing, zero-byte, or fails `pg_restore --list`.
- RPO/RTO/PITR decisions are unrecorded.
- The backup is not off-host.
- Migration owner or change window is unnamed.
- Any P2 behavior is enabled in P1.
- Documentation discrepancies in
  [`RELEASE_1_P1_DOCUMENTATION_RECONCILIATION.md`](./RELEASE_1_P1_DOCUMENTATION_RECONCILIATION.md)
  reappear or a new contradiction is found.

## 4. Current blocker snapshot

| Area | Status | Blocking items |
|---|---|---|
| Architecture/business | D11 blocked; other decisions approved | G-01, G-07 |
| Migration engineering | Not started/evidence ready | G-10, G-11, G-12, G-14, G-15, G-19 |
| Production measurement | Blocked | G-16, G-17 |
| Backup/recovery | Blocked/evidence ready | G-20..G-26, G-28, G-29 |
| Operational | Evidence ready | G-13, G-18 |
| Authorization | Blocked | G-09 |
| Documentation | Reconciled 17/17 | D-01..D-17 resolved |

## 5. Evidence required to change the verdict

Minimum evidence package:

1. Recorded D11 decision and corrected P1 scope/blueprint.
2. `env.py` TPM review and staging test with actual revisions.
3. Actual revision files and `alembic history` output.
4. TPM-before-autocommit txid evidence on actual revisions.
5. Concurrent-index validity and invalid-index recovery evidence.
6. Production-sized measurement report with timings and lock waits.
7. Fresh production dump metadata, checksum, `pg_restore --list`, off-host
   checksum.
8. Production-sized restore report with measured duration.
9. RPO/RTO approval and PITR decision.
10. Production-sized rollback/recovery rehearsal.
11. Approved operator runbook and stop conditions.
12. Named migration owner/window and explicit P1 authorization.

## 6. Final decision

| Decision | Result |
|---|---|
| P1 migration mechanism | **VERIFIED** in isolation (11/11) |
| P1 implementation | **NOT STARTED** |
| P1 documentation consistency | **RESOLVED** (17/17 reconciled) |
| P1 production measurement | **NOT READY** |
| P1 backup/recovery | **NOT READY** |
| P1 authorization | **NO-GO** |

**P1 remains unauthorized.** P2 and production activation remain unauthorized.

## 7. Stop condition

This is a planning and verification checklist. Do not create or modify migrations,
`env.py`, `deploy.sh`, application source, schema, API, frontend, dependencies,
or production settings. Do not execute migrations. Await explicit P1
authorization.
