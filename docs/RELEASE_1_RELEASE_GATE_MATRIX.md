# Release 1 Release Gate Matrix

Status: **gate definition only.** P1 and P2 remain unauthorized. No code,
migration, schema, API, frontend, dependency, deployment, or production setting
was changed.

Action/evidence IDs and the A-01..A-14 mapping are authoritative in
`RELEASE_1_GATE_A_CANONICAL_REGISTER.md`.

This matrix classifies every outstanding item. A gate is closed only when the
named evidence exists and is approved.

Legend:

- **P1** — MUST CLOSE BEFORE P1.
- **P2** — MUST CLOSE BEFORE P2.
- **PROD** — MUST CLOSE BEFORE PRODUCTION ACTIVATION.
- **DEFER** — SAFE TO DEFER to the named phase.

## 1. P1 decisions and scope

| ID | Item | Class | Evidence required | Owner/decision |
|---|---|---|---|---|
| G-01 | D11 full ledger vs reduced | **P1** | Explicit business decision; if full, `0035` included and `0036.down_revision="0035"` | User |
| G-02 | D3 strict checkpoint contract | **P1** | Approval of strict matrix including zero-committed restart | User/architecture |
| G-03 | D8 provisional timing | **P1** | Approval of 600/60/60/3600/60 as provisional only + measurement plan | User/architecture |
| G-04 | Defer `ix_jobs_retry_of` | **P1** | Approval to defer to P2/P9 | User/architecture |
| G-05 | Defer `ix_jobs_schedule_window_id` | **P1** | Approval to defer to P7 | User/architecture |
| G-06 | Defer `ix_jobs_s3_uploading` | **P1** | Approval to defer to P8 | User/architecture |
| G-07 | `0035` inclusion and `0036` dependency | **P1** | Approved linear graph: `0031 -> 0032 -> 0032b -> 0033 -> 0034 -> 0035 -> 0036`; `0035b` deferred | User/architecture |
| G-08 | P1/P2 boundary | **P1** | Signed scope: P1 inert schema only; P2 behavior only | User |
| G-09 | P1 authorization | **P1** | Explicit authorization record | User |

## 2. Migration execution

| ID | Item | Class | Evidence required | Owner |
|---|---|---|---|---|
| G-10 | `transaction_per_migration=True` | **P1** | Implemented and reviewed; rehearsal T1/T2 pass with exact image | Engineering |
| G-11 | Revision split | **P1** | `0032` columns only; `0032b` indexes; `0033`, `0034`, `0035`, `0036` schema; no combined DDL/index revision | Engineering |
| G-12 | TPM before autocommit | **P1** | Code review + staging test showing per-revision commit before index block | Engineering |
| G-13 | Individual revision execution | **P1** | Operator runbook approved; no `upgrade head` in P1 window | Engineering/operations |
| G-14 | Concurrent index validation | **P1** | `pg_index.indisvalid=true` check in runbook; invalid-index drill passed | Engineering |
| G-15 | Invalid-index recovery | **P1** | Drop/recreate procedure tested (T7/T8) and documented | Engineering |
| G-16 | Lock/statement timeout policy | **P1** | Initial test values documented; final values measured before P2 | Engineering/operations |
| G-17 | Production-sized measurement | **P1** | Lock wait, revision duration, index build on production-sized copy | Operations |
| G-18 | Operator stop conditions | **P1** | Runbook includes stop conditions and recovery actions | Operations |
| G-19 | Model/mirror declarations | **P1** | API and worker mirrors match migrations; no runtime reads | Engineering |
| G-20 | Backup sidecar pause | **P1** | Window procedure pauses backup during DDL | Operations |

## 3. Backup and recovery

| ID | Item | Class | Evidence required | Owner |
|---|---|---|---|---|
| G-21 | Fresh production dump | **P1** | `pg_dump -Fc` immediately before window; non-zero | Operations |
| G-22 | Dump integrity | **P1** | `pg_restore --list` exit 0; SHA-256 | Operations |
| G-23 | Off-host copy | **P1** | Copy on independent storage; checksum match | Operations |
| G-24 | Isolated restore rehearsal | **P1** | Restore to scratch; counts/version match; measured duration | Operations |
| G-25 | Encryption key availability | **P1** | Key outside backup; decrypt test in restored copy | Security/operations |
| G-26 | RPO approval | **P1** | Explicit dump-only RPO acceptance or PITR decision | User/business |
| G-27 | RTO approval | **PROD** | Measured restore + verification + start time within objective | User/operations |
| G-28 | PITR decision | **P1** decision, **PROD** enablement | Recorded decision; if enabled, PITR restore tested | User/operations |
| G-29 | P1 rollback/recovery rehearsal | **P1** | Forward-fix, downgrade, restore decision tree tested on copy | Engineering/operations |
| G-30 | Production recovery readiness | **PROD** | All REC-01..REC-09 evidence; no isolated-only claim | Operations |

## 4. Runtime and behavior

| ID | Item | Class | Evidence required | Owner |
|---|---|---|---|---|
| G-31 | Final D8 timing | **P2** | Production silent-stage/runtime measurement | Engineering |
| G-32 | D9 runtime limits | **P2** | Max runtime, chunk, finalization, slot occupancy; approved policy | User/business |
| G-33 | D9 reconciler | **P2** | Claim/fence + lease-expiry re-dispatch tests | Engineering |
| G-34 | Redis capacity/eviction | **PROD** | Memory/unacked/AOF/eviction evidence | Operations |
| G-35 | Real S3 provider | **PROD** | Multipart/conditional/IAM/versioning/listing tests | Engineering |
| G-36 | Canonical-path consumers | **P2** | Inventory and migration/exemption evidence | Engineering |
| G-37 | Schedule/report/rollup integration | **PROD** | One winner, no double count, window/retry tests | Engineering |
| G-38 | D10 partial UI | **PROD** | Job/group/report UI partial behavior approved and tested | Product/engineering |
| G-39 | Full lifecycle/API/frontend suite | **PROD** | T1–T24 or approved equivalent passes | Engineering |
| G-40 | D13 CHECK constraints | **DEFER** | P9 audit + constraint migration | Engineering |
| G-41 | `0035b` schedule indexes | **DEFER** | P7 concurrent build + validation | Engineering |
| G-42 | `ix_jobs_retry_of` | **DEFER** | P2/P9 partial concurrent index | Engineering |
| G-43 | `ix_jobs_schedule_window_id` | **DEFER** | P7 partial concurrent index | Engineering |
| G-44 | `ix_jobs_s3_uploading` | **DEFER** | P8 partial concurrent index | Engineering |
| G-45 | Bounded execution units | **DEFER** | Future design | Architecture |
| G-46 | External watchdog | **DEFER** | Future operations decision | Operations |

## 5. Gate summary

| Class | Count | Meaning |
|---|---|---|
| MUST CLOSE BEFORE P1 | 28 | P1 cannot start until closed |
| MUST CLOSE BEFORE P2 | 4 | P2 behavior cannot start until closed |
| MUST CLOSE BEFORE PRODUCTION ACTIVATION | 7 | Production rollout cannot start until closed |
| SAFE TO DEFER | 7 | Later phase |

Counts are a planning aid, not a substitute for the table. `G-28` has a P1
decision and a production enablement component; only the decision is counted
under P1.

## 6. Current gate status

| Gate | Status |
|---|---|
| P1 decisions | Recommended; awaiting approval |
| P1 migration mechanism | Rehearsed 11/11; not implemented |
| P1 revisions | Not created |
| P1 backup/recovery | Not production-verified |
| P1 authorization | **Not granted** |
| P2 authorization | **Not granted** |
| Production activation | **Not ready** |

## 7. Stop condition

This matrix is a gate definition. Do not implement P1/P2, modify `env.py` or
`deploy.sh`, create migrations, execute migrations, or change production
settings. P1 remains unauthorized.
