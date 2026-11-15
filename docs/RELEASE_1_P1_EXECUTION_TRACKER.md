# Release 1 P1 Execution Tracker

Status: **planning tracker only.** P1 is not authorized. No migration, code,
schema, API, frontend, dependency, deployment, or production setting was changed.

This is the **G-* blocker tracker**, not the stakeholder action tracker.
Stakeholder action and evidence IDs are authoritative in
`RELEASE_1_GATE_A_CANONICAL_REGISTER.md`.

Sources audited:

- [`RELEASE_1_FINAL_P1_AUTHORIZATION_CHECKLIST.md`](./RELEASE_1_FINAL_P1_AUTHORIZATION_CHECKLIST.md)
- [`RELEASE_1_FINAL_DECISION_REGISTER.md`](./RELEASE_1_FINAL_DECISION_REGISTER.md)
- [`RELEASE_1_P1_FINAL_OPERATOR_RUNBOOK.md`](./RELEASE_1_P1_FINAL_OPERATOR_RUNBOOK.md)
- [`RELEASE_1_PRODUCTION_RECOVERY_READINESS.md`](./RELEASE_1_PRODUCTION_RECOVERY_READINESS.md)
- [`RELEASE_1_RELEASE_GATE_MATRIX.md`](./RELEASE_1_RELEASE_GATE_MATRIX.md)
- [`RELEASE_1_P1_MIGRATION_REHEARSAL_REPORT.md`](./RELEASE_1_P1_MIGRATION_REHEARSAL_REPORT.md)
- [`RELEASE_1_P1_MIGRATION_SAFETY_PREFLIGHT.md`](./RELEASE_1_P1_MIGRATION_SAFETY_PREFLIGHT.md)
- [`RELEASE_1_P1_CRITICAL_PATH.md`](./RELEASE_1_P1_CRITICAL_PATH.md)
- [`RELEASE_1_P1_MIGRATION_DISCREPANCY_REPORT.md`](./RELEASE_1_P1_MIGRATION_DISCREPANCY_REPORT.md)
- [`RELEASE_1_P1_PRODUCTION_EVIDENCE_COLLECTION.md`](./RELEASE_1_P1_PRODUCTION_EVIDENCE_COLLECTION.md)
- [`RELEASE_1_P1_FINAL_GO_NO_GO_CHECKLIST.md`](./RELEASE_1_P1_FINAL_GO_NO_GO_CHECKLIST.md)
- [`RELEASE_1_P1_ENGINEERING_AUTHORIZATION.md`](./RELEASE_1_P1_ENGINEERING_AUTHORIZATION.md)
- [`RELEASE_1_P1_PRODUCTION_AUTHORIZATION.md`](./RELEASE_1_P1_PRODUCTION_AUTHORIZATION.md)
- [`RELEASE_1_P1_ENGINEERING_EXECUTION_PLAN.md`](./RELEASE_1_P1_ENGINEERING_EXECUTION_PLAN.md)
- [`RELEASE_1_D11_BUSINESS_APPROVAL_RECORD.md`](./RELEASE_1_D11_BUSINESS_APPROVAL_RECORD.md)
- [`RELEASE_1_GATE_A_OWNERSHIP_RECORD.md`](./RELEASE_1_GATE_A_OWNERSHIP_RECORD.md)
- [`RELEASE_1_PRODUCTION_ISOLATION_CONFIRMATION.md`](./RELEASE_1_PRODUCTION_ISOLATION_CONFIRMATION.md)
- [`RELEASE_1_GATE_A_APPROVAL_RECORD.md`](./RELEASE_1_GATE_A_APPROVAL_RECORD.md)
- [`RELEASE_1_ADMINISTRATIVE_CLOSURE_RECONCILIATION.md`](./RELEASE_1_ADMINISTRATIVE_CLOSURE_RECONCILIATION.md)
- [`RELEASE_1_GATE_A_STAKEHOLDER_ACTION_PLAN.md`](./RELEASE_1_GATE_A_STAKEHOLDER_ACTION_PLAN.md)
- [`RELEASE_1_GATE_A_EVIDENCE_CHECKLIST.md`](./RELEASE_1_GATE_A_EVIDENCE_CHECKLIST.md)
- [`RELEASE_1_GATE_A_FINAL_AUTHORIZATION_CHECKLIST.md`](./RELEASE_1_GATE_A_FINAL_AUTHORIZATION_CHECKLIST.md)

**Closure rule:** an item is closed only when the named verification evidence
exists and is approved. Documentation alone does not close a blocker.

## 1. Status summary

Status vocabulary:

`NOT STARTED` / `IN PROGRESS` / `BLOCKED` / `EVIDENCE READY` / `VERIFIED` /
`APPROVED`

| ID | Requirement | Category | Status | Owner | Change type |
|---|---|---|---|---|---|
| G-01 | D11 full ledger decision | Architecture/business | **BLOCKED** | Business/architecture | Management |
| G-02 | D3 strict checkpoint contract | Architecture/business | **APPROVED** | Architecture | Management |
| G-03 | D8 provisional timing acceptance | Architecture/business | **APPROVED** | Architecture | Management |
| G-04 | Defer `ix_jobs_retry_of` | Architecture/business | **APPROVED** | Architecture | Management |
| G-05 | Defer `ix_jobs_schedule_window_id` | Architecture/business | **APPROVED** | Architecture | Management |
| G-06 | Defer `ix_jobs_s3_uploading` | Architecture/business | **APPROVED** | Architecture | Management |
| G-07 | Include `0035`; `0036` depends on `0035` | Architecture/business | **BLOCKED** | Architecture | Management |
| G-08 | P1/P2 boundary | Architecture/business | **APPROVED** | Architecture | Management |
| G-09 | P1 authorization | Change management | **BLOCKED** | User | Management |
| G-10 | `transaction_per_migration=True` | Migration engineering | **NOT STARTED** | Engineering | Application/migration infrastructure |
| G-11 | Revision split and files | Migration engineering | **NOT STARTED** | Engineering | Application/migration files |
| G-12 | TPM before any autocommit block | Migration engineering | **EVIDENCE READY** | Engineering | Application/migration ordering |
| G-13 | Individual revision execution | Operational readiness | **EVIDENCE READY** | Engineering/operations | Documentation/operations |
| G-14 | Concurrent-index validation | Migration engineering | **EVIDENCE READY** | Engineering/DBA | Engineering/DBA |
| G-15 | Invalid-index recovery | Migration engineering | **EVIDENCE READY** | Engineering/DBA | Engineering/DBA |
| G-16 | Lock/statement timeout policy | Migration engineering | **IN PROGRESS** | Engineering/operations | Engineering/operations |
| G-17 | Production-sized measurement | PostgreSQL/DBA | **BLOCKED** | DBA/operations | DBA/infrastructure |
| G-18 | Operator stop conditions | Operational readiness | **EVIDENCE READY** | Operations | Documentation/operations |
| G-19 | API/worker model/mirror declarations | Migration engineering | **NOT STARTED** | Engineering | Application |
| G-20 | Backup sidecar pause in window | Backup/recovery | **NOT STARTED** | Operations | Operations |
| G-21 | Fresh production dump | Backup/recovery | **BLOCKED** | DBA/operations | DBA/operations |
| G-22 | Dump integrity | Backup/recovery | **BLOCKED** | DBA/operations | DBA/operations |
| G-23 | Off-host backup copy | Backup/recovery | **BLOCKED** | Infrastructure/operations | Infrastructure |
| G-24 | Isolated restore rehearsal (production-sized) | PostgreSQL/DBA | **EVIDENCE READY** | DBA/operations | DBA |
| G-25 | Encryption-key availability | Backup/recovery | **EVIDENCE READY** | Security/operations | Security/operations |
| G-26 | RPO approval | Backup/recovery | **NOT STARTED** | Business/operations | Management |
| G-28 | PITR decision | Backup/recovery | **NOT STARTED** | Business/infrastructure | Management/infrastructure |
| G-29 | P1 rollback/recovery rehearsal | PostgreSQL/DBA | **EVIDENCE READY** | DBA/operations | DBA/operations |

**Note:** G-01 is **BLOCKED** until a signed D11 business record exists. G-07 is
**BLOCKED** because it depends on G-01. G-02..G-06 and G-08 remain approved.
Do not treat the prior “Architecture decisions: CLOSED” status statement as a
signed D11 record.

### 1.1 Counts

| Status | Count |
|---|---|
| APPROVED | 6 |
| EVIDENCE READY | 8 |
| IN PROGRESS | 1 |
| NOT STARTED | 6 |
| BLOCKED | 7 |
| VERIFIED | 0 |

Only APPROVED and VERIFIED count as closed. Current closed count: **6/28**.

### 1.2 Gate tracks

| Track | IDs | Count | Closed now |
|---|---|---|---|
| Engineering implementation | G-01..G-08, G-10, G-11, G-19 | 11 | 6/11 |
| Engineering validation | G-12, G-13, G-14, G-15, G-16, G-18 | 6 | 0/6 |
| Production migration | G-09, G-17, G-20..G-26, G-28, G-29 | 11 | 0/11 |

Notes:

- Engineering implementation blockers must close before Gate A.
- Engineering validation blockers must close before Gate A exit.
- Production migration blockers must close before Gate B.
- G-16 has an initial engineering component (timeout policy) and a production
  component (final measured values). It is counted under engineering validation;
  final values remain a Gate B dependency.
- No item is VERIFIED unless its actual evidence exists.

### 1.3 Gate authorization notes

- **Gate A authorization** is a separate approval record in
  [`RELEASE_1_P1_ENGINEERING_AUTHORIZATION.md`](./RELEASE_1_P1_ENGINEERING_AUTHORIZATION.md).
  It is granted before G-10/G-11/G-19 implementation starts, after G-01..G-08
  and the Gate A preconditions are recorded.
- **G-10, G-11, G-19** are Gate A implementation work.
- **G-12..G-16, G-18** are Gate A validation work.
- **G-09** is the final Gate B production migration authorization, not Gate A.
- **G-17, G-20..G-26, G-28, G-29** are Gate B production evidence.
- Gate A success produces evidence for Gate B; it does not grant Gate B.

## 2. Architecture and business approvals

| ID | Requirement | Why necessary | Current evidence | Missing evidence | Action required | Dependencies | Verification | Closure criterion | Change type |
|---|---|---|---|---|---|---|---|---|---|
| G-01 | D11: full calendar+interval ledger | Determines `0035` inclusion, graph, and P7 scope | Final recommendation only; decision register still lists D11 as not approved; no signed record | Signed D11 record with FULL or REDUCED selection and owner signature | Record approval in `RELEASE_1_D11_BUSINESS_APPROVAL_RECORD.md` | None | Signed record matches graph/scope | D11 signed; G-01 closes | Management |
| G-02 | D3 strict checkpoint contract | Prevents tail-only/duplicate resume | P0-12 matrix; checkpoint contract; final recommendation | Explicit acceptance record | Approve strict matrix, including zero-committed restart | None | Contract review | Recorded approval | Management |
| G-03 | D8 provisional timing | Sets lease/heartbeat defaults | P0-03/04/05; register provisional values | Acceptance as provisional; measurement plan | Approve provisional defaults | G-17 for final values | Decision record | Recorded approval; final values later | Management |
| G-04 | Defer `ix_jobs_retry_of` | Avoids full all-NULL index with no P1 query | Strategy, rehearsal, query audit | Deferral approval; P1 scope removal | Approve deferral to P2/P9 | G-01..G-03 | P1 migration review | No index in P1; later partial concurrent index | Management |
| G-05 | Defer `ix_jobs_schedule_window_id` | Avoids full all-NULL index | Strategy, query audit | Deferral approval; P1 scope removal | Approve deferral to P7 | G-01..G-03 | P1 migration review | No index in P1; P7 partial concurrent index | Management |
| G-06 | Defer `ix_jobs_s3_uploading` | No P1 query; partial later | Strategy, query audit | Deferral approval; P1 scope removal | Approve deferral to P8 | G-01..G-03 | P1 migration review | No index in P1; P8 partial concurrent index | Management |
| G-07 | Include `0035`; `0036` depends on `0035` | Keeps graph linear; avoids rewrite | Runs only if D11 FULL; D11 currently unsigned | Signed D11 FULL record and graph approval | Record graph after D11 signature | G-01 | `alembic history` after files exist | Linear graph; no missing revision | Management/engineering |
| G-08 | P1/P2 boundary | Protects old versions and prevents behavior leak | P1 scope, checklist, runbook | Signed scope statement | Approve inert-schema-only P1 | G-01..G-07 | Code review: no new reads/flags | No P1 runtime dependency | Management |

## 3. Migration engineering

| ID | Requirement | Why necessary | Current evidence | Missing evidence | Action required | Dependencies | Verification | Closure criterion | Change type |
|---|---|---|---|---|---|---|---|---|---|
| G-10 | `transaction_per_migration=True` | Per-revision commit; avoids bundle lock | Implementation spec, rehearsal T1/T2, strategy | Implemented env.py change and review | Implement later; not now | G-01..G-08 | Code review + staging T1/T2 with P1 revisions | TPM present; test passes | Application/migration infrastructure |
| G-11 | Revision split | Keeps transactions short | Implementation spec, test spec, strategy, runbook, rehearsal | `0032`, `0032b`, `0033`, `0034`, `0035`, `0036` files | Create later; not now | G-10, G-01..G-08 | `alembic history`; file review | Files exist; `0032` has no indexes; `0035` has no jobs indexes | Application/migration files |
| G-12 | TPM before autocommit | T11 proved autocommit commits prior revisions without TPM | Rehearsal T11 | Code review and P1-specific staging test | Enforce ordering; test | G-10, G-11 | T11-like test with actual revisions | Per-revision txids before index block | Engineering |
| G-13 | Individual revision execution | Controls lock window and stop points | Runbook | Operator approval; tabletop | Approve runbook | G-10..G-12 | Runbook review/tabletop | Approved no-`upgrade head` procedure | Documentation/operations |
| G-14 | Concurrent-index validation | Avoids invalid index after failure | T5-T8; runbook SQL | P1-specific index test | Add validation to runbook; test | G-11 | `indisvalid=true` after each index | Evidence for P1 indexes | Engineering/DBA |
| G-15 | Invalid-index recovery | Recovers without rebuild ambiguity | T7/T8; runbook | P1-specific operator drill | Drill drop/rebuild | G-14 | Drop/rebuild test | Drill passed; runbook approved | Engineering/DBA |
| G-16 | Lock/statement timeout policy | Bounds acquisition and execution | Initial values; T9/T10 | Final measured values; approval | Measure on copy | G-17 | Timed runs | Approved values with margins | Engineering/operations |
| G-19 | API/worker model/mirror | Keeps ORM/Core schema consistent | Current code lacks P1 fields; no reads | P1 declarations and contract test | Implement later | G-11 | Migration/model diff; tests | Reviewed; no runtime use | Application |

## 4. PostgreSQL and DBA validation

| ID | Requirement | Why necessary | Current evidence | Missing evidence | Action required | Dependencies | Verification | Closure criterion | Change type |
|---|---|---|---|---|---|---|---|---|---|
| G-17 | Production-sized measurement | Sets timeouts/window; 25 MB is not enough | Isolated 25 MB only | Production-sized row counts, timings, lock waits | DBA copy run | G-10..G-16 | Timed per-revision run | Acceptable duration/locks; final values | DBA/infrastructure |
| G-24 | Production-sized isolated restore | Proves RTO and schema recovery | Isolated 39 KB/10k-row restore (0.363 s) | Production-sized restore, counts, version, duration | Restore rehearsal | G-21..G-23 | Timed restore + checks | Meets RTO; evidence recorded | DBA |
| G-29 | P1 rollback/recovery rehearsal | Proves forward-fix/downgrade/restore | Isolated T6-T8 | Production-sized downgrade/restore drill | Rehearse all paths | G-21..G-25 | Timed drill | All paths pass; owner known | DBA/operations |

## 5. Backup and recovery

| ID | Requirement | Why necessary | Current evidence | Missing evidence | Action required | Dependencies | Verification | Closure criterion | Change type |
|---|---|---|---|---|---|---|---|---|---|
| G-20 | Backup sidecar pause | Avoids `pg_dump`/DDL lock contention | Plan/runbook | Window procedure/owner | Add to change plan | G-21 | Dry run | Procedure approved | Operations |
| G-21 | Fresh production dump | Recovery point | Latest >24 h old; isolated dump only | Fresh dump at window | Take dump | Production access/change window | Size/time | Non-zero fresh dump | DBA/operations |
| G-22 | Dump integrity | Avoids invalid recovery | Isolated dump `pg_restore --list` pass; production not | Production dump integrity | Verify | G-21 | `pg_restore --list` exit 0 | Verified + SHA-256 | DBA/operations |
| G-23 | Off-host copy | Covers disk/host loss | None; same-disk production | Off-host copy/checksum | Copy | G-21 | Checksum match | Off-host verified | Infrastructure/operations |
| G-24 | Production-sized restore | RTO proof | Isolated 0.363 s | Production-sized restore | Restore | G-21..G-23 | Timed restore | Within approved RTO | DBA |
| G-25 | Encryption key availability | Credentials must decrypt | Key present in `.env` | Custody/off-backup verification; decrypt test | Verify | G-21/G-24 | Decrypt check | Key available/off-backup | Security/operations |
| G-26 | RPO approval | Data-loss tolerance | None | Business approval or PITR | Decide | G-28 | Approval record | Recorded RPO | Management |
| G-28 | PITR decision | Recovery capability | `archive_mode=off` | Decision; if enabled, restore test | Decide/test | Infrastructure | PITR restore test if chosen | Recorded decision | Management/infrastructure |

## 6. Operational readiness and change management

| ID | Requirement | Why necessary | Current evidence | Missing evidence | Action required | Dependencies | Verification | Closure criterion | Change type |
|---|---|---|---|---|---|---|---|---|---|
| G-13 | Individual revision execution | Controls window | Runbook | Approval/tabletop | Approve | G-10..G-12 | Review | Approved | Documentation/operations |
| G-18 | Operator stop conditions | Safe abort | Runbook | Approval | Approve | G-13 | Review | Approved | Documentation/operations |
| G-09 | P1 authorization | Legal/change gate | None | All P1 evidence + explicit approval | Authorize only after closure | All P1 items | Authorization record | Explicit approval | Management |

## 7. Immediate work that can start

These do not require application code changes:

- Sign or record G-01..G-08 decisions.
- Approve G-13/G-18 runbook and stop conditions.
- Define G-16 initial values and measurement method.
- Request DBA/infrastructure access for G-17, G-21..G-25, G-29.
- Verify the reconciled documentation in
  [`RELEASE_1_P1_DOCUMENTATION_RECONCILIATION.md`](./RELEASE_1_P1_DOCUMENTATION_RECONCILIATION.md).
- Approve the evidence collection plan in
  [`RELEASE_1_P1_PRODUCTION_EVIDENCE_COLLECTION.md`](./RELEASE_1_P1_PRODUCTION_EVIDENCE_COLLECTION.md).

## 8. What cannot start yet

- G-10/G-11/G-19 implementation: no P1 authorization and no migration files.
- G-12/G-14/G-15 P1-specific tests: require G-10/G-11.
- G-17 production-sized measurement: requires DBA access and G-11.
- G-21..G-25: require production access and change approval; must not be
  performed under this planning task.
- G-09 authorization: requires all other P1 items closed.

## 9. Documentation reconciliation

**17/17 discrepancies resolved** in
[`RELEASE_1_P1_DOCUMENTATION_RECONCILIATION.md`](./RELEASE_1_P1_DOCUMENTATION_RECONCILIATION.md).

| Discrepancy | Status | Verification |
|---|---|---|
| D-01 `0032` indexes | **RESOLVED (documentation)** | `0032` columns only; `0032b` defined |
| D-02 `ix_jobs_retry_of` | **RESOLVED (documentation)** | Deferred to P2/P9 |
| D-03 `0035` jobs indexes | **RESOLVED (documentation)** | Deferred to `0035b`/P7 |
| D-04 `0036` S3 index | **RESOLVED (documentation)** | Deferred to P8 |
| D-05 P1 inventory | **RESOLVED (documentation)** | Six-revision inventory |
| D-06 procedure `upgrade 0031:0036` | **RESOLVED (documentation)** | Individual revisions |
| D-07 `0035`/`0036` graph | **RESOLVED (documentation)** | Include `0035`; reduced exception documented |
| D-08 acceptance tests | **RESOLVED (documentation)** | Per-revision tests |
| D-09 blueprint `0032` indexes | **RESOLVED (documentation)** | Blueprint aligned |
| D-10 blueprint `0036` index | **RESOLVED (documentation)** | S3 columns only |
| D-11 blueprint `retry_of` | **RESOLVED (documentation)** | `retry_of` in `0032` |
| D-12 blueprint M5 indexes | **RESOLVED (documentation)** | Deferred `0035b` |
| D-13 migration plan §3 | **RESOLVED (documentation)** | Indexes moved/deferred |
| D-14 migration plan §6 | **RESOLVED (documentation)** | Jobs indexes deferred |
| D-15 deployment phases | **RESOLVED (documentation)** | Final runbook supersedes |
| D-16 old runbook | **RESOLVED (documentation)** | Marked superseded |
| D-17 TPM ordering | **RESOLVED (documentation)** | TPM-before-autocommit documented |

Documentation resolution does not change blocker status. G-10/G-11/G-19 remain
NOT STARTED because the migration files and code have not been created.

## 10. Stop condition

This tracker is documentation. Do not implement P1/P2, create migrations, modify
`env.py` or `deploy.sh`, execute migrations, or change production settings.
P1 remains unauthorized.
