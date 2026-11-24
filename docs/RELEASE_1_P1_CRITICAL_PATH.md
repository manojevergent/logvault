# Release 1 P1 Critical Path and Dependency Analysis

Status: **planning only.** P1 is not authorized. No code, migration, schema, or
production change was made.

Related:

- [`RELEASE_1_P1_EXECUTION_TRACKER.md`](./RELEASE_1_P1_EXECUTION_TRACKER.md)
- [`RELEASE_1_P1_PRODUCTION_EVIDENCE_COLLECTION.md`](./RELEASE_1_P1_PRODUCTION_EVIDENCE_COLLECTION.md)
- [`RELEASE_1_P1_MIGRATION_DISCREPANCY_REPORT.md`](./RELEASE_1_P1_MIGRATION_DISCREPANCY_REPORT.md)

## 1. Critical path

```text
Record decisions G-01..G-08
        |
        v
Verify reconciled P1 documentation (17/17)
        |
        v
Implement G-10 TPM + G-11 revision split + G-19 model mirrors
        |
        v
Prove G-12 TPM-before-autocommit + G-14/G-15 index validation/recovery
        |
        v
Approve G-13/G-18 operator procedure
        |
        v
G-17 production-sized measurement  --->  finalize G-16 timeouts
        |
        v
G-20..G-25 backup, integrity, off-host, restore, key
        |
        v
G-26 RPO + G-28 PITR decisions
        |
        v
G-29 production-sized rollback/recovery rehearsal
        |
        v
G-09 explicit P1 authorization
```

The critical path ends at **G-09**. No later task can substitute for it.

## 2. Work that can start immediately

These do not require application code changes and can proceed in parallel:

| Work | Items | Notes |
|---|---|---|
| Record architecture approvals | G-01..G-08 | User states decisions are closed; still record the specific D11/`0035` decision |
| Approve runbook/stop conditions | G-13, G-18 | Review only |
| Define timeout measurement method | G-16 | Initial test values already documented |
| Verify documentation | Reconciliation report | P1 scope, blueprint, and runbook alignment confirmed |
| Request DBA/infrastructure access | G-17, G-21..G-25, G-29 | Access request only |
| Prepare evidence templates | G-21..G-25, G-29 | No production action |

## 3. Work requiring DBA or infrastructure

| Work | Items | Why |
|---|---|---|
| Production-sized measurement | G-17 | Row counts, lock waits, index build duration |
| Production dump/off-host/integrity | G-21, G-22, G-23 | Production access and backup storage |
| Production-sized restore | G-24 | Disposable environment and measured RTO |
| Key custody verification | G-25 | Security/operations |
| Rollback/restore rehearsal | G-29 | DBA/operations |
| PITR decision/implementation | G-28 | Infrastructure |
| Index inventory/disk/version | Evidence plan | DBA |

## 4. Work requiring business approval

| Work | Items | Decision |
|---|---|---|
| D11 ledger scope | G-01 | Full ledger vs reduced |
| RPO | G-26 | Dump-only vs PITR |
| PITR | G-28 | Enable or accept dump-only |
| P1 authorization | G-09 | Final GO |
| D9 runtime limits | Later (P2/production) | Not a P1 schema blocker |

## 5. Work requiring a production-sized environment

| Work | Items |
|---|---|
| Migration duration and lock measurement | G-17 |
| Final timeout values | G-16 (depends G-17) |
| Production-sized restore | G-24 |
| RTO measurement | G-24/G-29 |
| Rollback rehearsal | G-29 |
| Index inventory and plan validation | Evidence plan |

The 25 MB rehearsal database is not a substitute.

## 6. Work that can be done without application changes

- G-01..G-08 approval records.
- G-13/G-18 runbook approval.
- G-16 measurement method and initial values.
- G-20 backup-sidecar pause procedure.
- G-21..G-25 backup/recovery evidence.
- G-26/G-28 business decisions.
- G-29 recovery rehearsal on a copy.
- Documentation verification.

## 7. Work requiring application/migration changes

| Work | Items | Note |
|---|---|---|
| TPM | G-10 | `env.py` change; not now |
| Revision split | G-11 | New migration files; not now |
| Model/mirror | G-19 | Inert declarations; not now |
| TPM/index proof | G-12, G-14, G-15 | After G-10/G-11 |

## 8. Parallelizable work

| Stream A | Stream B | Stream C |
|---|---|---|
| G-01..G-08 approvals | G-17 DBA measurement | G-21..G-25 backup/restore |
| G-13/G-18 runbook review | G-10/G-11 migration engineering | Documentation verification |
| G-16 policy | G-14/G-15 index drills | G-26/G-28 business decisions |

Dependencies:

- G-10 must precede G-12.
- G-11 must precede G-12/G-14/G-15/G-19.
- G-17 must precede final G-16.
- G-21..G-23 must precede G-24.
- G-24 must precede G-29.
- G-26/G-28 can run in parallel with G-21..G-25.
- G-09 is last.

## 9. Bottlenecks

1. **Production access** for G-17/G-21..G-25/G-29.
2. **Business decisions** G-01/G-26/G-28.
3. **Migration engineering** G-10/G-11/G-19, which cannot start before P1
   authorization and the reconciled documentation.
4. **RPO/PITR** decision, because a dump-only RPO may be unacceptable.
5. **No production-sized measurements**; the current evidence is small-database
   only.

## 10. Dependency risks

| Risk | Effect | Mitigation |
|---|---|---|
| D11/`0035` ambiguity | Graph rewrite or wrong P1 scope | Record G-01 and G-07 before files |
| TPM not enabled before autocommit | Earlier revisions commit unexpectedly | G-12 gate before any index revision |
| Invalid index left behind | Revision cannot stamp; query degradation | G-14/G-15 drills |
| Production measurement reveals long lock | Window may be unsafe | Split revisions further or reschedule |
| Backup is stale/invalid | No recovery point | G-21..G-25 before window |
| RPO not accepted | Cannot proceed | G-26/G-28 |
| Docs disagree | Operator error | Reconciliation report |

## 11. Critical-path verdict

The project is **not on the critical path to P1 authorization yet**. Eight
decision items are approved, but migration engineering, production measurement,
backup/restore, and authorization remain open.

The shortest legitimate path is:

1. Record G-01..G-08 and verify the reconciled documentation.
2. Implement G-10/G-11/G-19 after P1 authorization.
3. Prove G-12/G-14/G-15.
4. Complete G-17 and finalize G-16.
5. Complete G-21..G-25 and G-29.
6. Approve G-26/G-28.
7. Approve G-13/G-18.
8. Authorize G-09.

## 12. Stop condition

This is a dependency analysis. Do not start P1/P2 or modify code, migrations, or
production settings.
