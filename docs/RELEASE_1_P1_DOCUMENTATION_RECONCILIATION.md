# Release 1 P1 Documentation Reconciliation

Status: **documentation reconciliation only.** No migration, `env.py`,
`deploy.sh`, application source, schema, API, frontend, dependency, deployment,
or production setting was changed. P1 remains unauthorized.

Source of truth:

- [`RELEASE_1_P1_IMPLEMENTATION_SPECIFICATION.md`](./RELEASE_1_P1_IMPLEMENTATION_SPECIFICATION.md)
- [`RELEASE_1_P1_FINAL_OPERATOR_RUNBOOK.md`](./RELEASE_1_P1_FINAL_OPERATOR_RUNBOOK.md)
- Final graph: `0031 -> 0032 -> 0032b -> 0033 -> 0034 -> 0035 -> 0036`

## 1. Result

**17/17 documentation discrepancies resolved.**

| Metric | Value |
|---|---|
| Discrepancies found | 17 |
| Resolved in documentation | 17 |
| Remaining documentation inconsistencies | 0 known |
| P1 implementation | NOT STARTED |
| P1 authorization | NOT GRANTED |

Resolving documentation does not close implementation blockers. G-10, G-11,
G-19, and the production/backup gates remain open.

## 2. Resolution table

| ID | Original discrepancy | Resolution | Affected documents | Verification evidence |
|---|---|---|---|---|
| D-01 | `0032` listed jobs indexes | `0032` is columns only; lease/owner/progress indexes are in `0032b` | `RELEASE_1_P1_SCOPE_AND_MIGRATION.md`, `RELEASE_1_IMPLEMENTATION_BLUEPRINT.md`, `RELEASE_1_MIGRATION_PLAN.md` | `0032` section now states "creates no indexes"; `2A` defines `0032b` |
| D-02 | `ix_jobs_retry_of` remained in P1 | Removed from P1; deferred to P2/P9 as a partial concurrent index | P1 scope, blueprint, migration plan | `ix_jobs_retry_of` appears only as deferred |
| D-03 | `0035` listed jobs indexes | Jobs indexes removed; moved to future `0035b`/P7 | P1 scope, blueprint, migration plan | `0035` table lists only new-table indexes; `0035b` marked P7 |
| D-04 | `0036` listed `ix_jobs_s3_uploading` | Removed from P1; deferred to P8 | P1 scope, blueprint, migration plan | `0036` section says "None in `0036`"; index marked P8 |
| D-05 | P1 inventory said `0032`–`0036` | Updated to `0032`, `0032b`, `0033`, `0034`, `0035`, `0036` | P1 scope, blueprint | Inventory table and top note match final graph |
| D-06 | P1 procedure said `upgrade 0031:0036` | Replaced with individual revision sequence; no `upgrade head` | P1 scope, runbook, blueprint | Procedure lists `0032`, `0032b`, `0033`, `0034`, `0035`, `0036` |
| D-07 | `0035` omission vs `0036.down_revision=0035` | Full ledger is the final recommendation: include `0035`, `0036.down_revision=0035`; reduced-scope exception documented | P1 scope, decision register, checklist | D11 decision and D11 exception both explicit |
| D-08 | Acceptance tests used `upgrade 0031:0036` | Tests now apply each revision and check `0032b` separately | P1 scope | P1-T01/T08/T13 updated |
| D-09 | Blueprint said `0032` includes indexes | Blueprint P1 now says columns only; `0032b` indexes | Blueprint | P1 functionality list |
| D-10 | Blueprint said `0036` includes index | Blueprint now says S3 columns only | Blueprint | P1 functionality list |
| D-11 | Blueprint placed `retry_of` in `0033` | Corrected: `retry_of` is in `0032` | Blueprint | M2 database changes |
| D-12 | Blueprint `0035` included unique/active indexes | Moved to `0035b`/P7 | Blueprint | M5 functionality list |
| D-13 | Migration plan `0032` listed indexes | Index column now says `0032b` or deferred | Migration plan §3 | Field table |
| D-14 | Migration plan `0035` listed jobs indexes | Jobs indexes moved to deferred `0035b`/P7 block | Migration plan §6 | New-table-only index block + deferred block |
| D-15 | Deployment phases did not mention `0032b` | Added note that the final runbook supersedes the phase list | Deployment doc | Phase 1 note |
| D-16 | Earlier operator runbook could be mistaken for current | Marked superseded; final runbook is authoritative | Old runbook | Top status |
| D-17 | P1 scope did not state TPM-before-autocommit | Added to top, index strategy, and procedure | P1 scope | TPM ordering text |

## 3. Final responsibility map

| Revision | Responsibility | Transaction |
|---|---|---|
| `0032` | 11 `jobs` ownership/completion columns | One short transaction |
| `0032b` | `ix_jobs_lease`, `ix_jobs_owner`, `ix_jobs_progress` | `autocommit_block`, concurrent |
| `0033` | `store_path`, `spec_fingerprint`, `checkpoint_version` | One short transaction |
| `0034` | `job_dispatch_outbox` + new-table indexes | One short transaction |
| `0035` | `schedule_windows` + `jobs.schedule_window_id`/`attempt_no` + new-table indexes | One short transaction |
| `0036` | S3 attempt columns only | One short transaction |

Deferred and absent from P1:

- `0035b` — schedule jobs indexes; P7.
- `0036b` — S3 index; P8.
- `ix_jobs_retry_of` — P2/P9.
- `ix_jobs_schedule_window_id` — P7.
- `ix_jobs_s3_uploading` — P8.

## 4. Verification checklist

- [x] `0032` contains no indexes.
- [x] `0032b` contains only lease/owner/progress partial concurrent indexes.
- [x] `0033` contains store/spec/checkpoint columns.
- [x] `0034` contains the outbox table and new-table indexes.
- [x] `0035` contains the windows table, two `jobs` columns, and new-table indexes.
- [x] `0036` contains S3 columns and no index.
- [x] `0036.down_revision="0035"`.
- [x] No P1 document recommends `upgrade head`.
- [x] `retry_of` is assigned to `0032`, not `0033`.
- [x] `0035b`/`0036b` are not part of P1.
- [x] TPM is required before any autocommit block.
- [x] P1/P2 boundary remains inert-schema-only.

## 5. Remaining implementation work

Documentation is reconciled, but these are still open:

- G-10: implement `transaction_per_migration=True`.
- G-11: create the six revision files.
- G-19: add inert API/worker model declarations.
- G-12/G-14/G-15: prove TPM ordering and index recovery on the actual revisions.
- G-17/G-21..G-25/G-29: production-sized measurement and recovery evidence.
- G-26/G-28: RPO/PITR decisions.
- G-09: authorization.

## 6. Stop condition

This report is documentation only. Do not create migration files, modify
`env.py`/`deploy.sh`, execute migrations, or change production settings. P1
remains unauthorized.
