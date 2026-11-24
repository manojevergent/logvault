# Release 1 P1 Migration Discrepancy Report

Status: **audit only.** No migration, `env.py`, `deploy.sh`, application source,
schema, or production setting was changed. P1 remains unauthorized.

**Resolution update:** all 17 discrepancies in this report have been reconciled
in [`RELEASE_1_P1_DOCUMENTATION_RECONCILIATION.md`](./RELEASE_1_P1_DOCUMENTATION_RECONCILIATION.md).
This report remains the original audit record.

Scope: proposed graph `0031 -> 0032 -> 0032b -> 0033 -> 0034 -> 0035 -> 0036`
and the operator runbook.

## 1. Executive summary

The runbook and execution strategy are internally coherent. The older P1 scope,
implementation blueprint, and migration plan still describe the pre-split
revision layout. If an operator followed those older documents, they would:

- build indexes in `0032` and `0035` instead of the concurrent index revisions;
- re-introduce the deferred full indexes;
- run a single `upgrade 0031:0036` rather than individual revisions;
- recreate the lock amplification the redesign removed.

**Material finding:** P1 is not ready for authorization until the P1 scope,
blueprint, and migration plan are corrected to match the final runbook. This is
a documentation correction, not an implementation.

## 2. Discrepancy table

| ID | Source | Discrepancy | Severity | Required correction | Blocks P1? |
|---|---|---|---|---|---|
| D-01 | `RELEASE_1_P1_SCOPE_AND_MIGRATION.md` §2.2 | `0032` lists `ix_jobs_lease`, `ix_jobs_owner`, `ix_jobs_progress`, `ix_jobs_retry_of`; runbook puts lease/owner/progress in `0032b` and defers retry_of | **High** | Move lease/owner/progress to `0032b`; remove retry_of from P1 | Yes |
| D-02 | P1 scope §2.2 | `ix_jobs_retry_of` is a full index in P1; runbook defers it | **High** | Remove from P1; document P2/P9 partial concurrent index | Yes |
| D-03 | P1 scope §5.3 | `0035` lists `ix_jobs_schedule_window_id`, `uq_jobs_schedule_attempt`, `uq_jobs_schedule_active`; runbook defers jobs indexes to `0035b`/P7 | **High** | Move jobs indexes out of `0035`; make `0035b` optional/P7 | Yes |
| D-04 | P1 scope §6.2 | `0036` lists `ix_jobs_s3_uploading`; runbook defers to P8 | **High** | Remove from `0036`; document P8 partial index | Yes |
| D-05 | P1 scope §1.1 | Says P1 adds `0032`–`0036`; execution strategy adds `0032b`, optional `0035b`/`0036b` | Medium | Update inventory to include split revisions | Yes |
| D-06 | P1 scope §11 | Says `alembic upgrade 0031:0036` and `downgrade 0036:0031`; runbook uses individual revisions | **High** | Replace with per-revision sequence and verification gates | Yes |
| D-07 | P1 scope §1.1 / §5 | Says `0035` can be omitted if D11 reduced, but `0036.down_revision="0035"` | Medium | If D11 full, state include; if reduced, set `0036.down_revision="0034"` explicitly | Yes |
| D-08 | P1 scope acceptance tests | `upgrade 0031:0036` does not test `0032b` separately | Medium | Add per-revision upgrade/downgrade tests | Yes |
| D-09 | `RELEASE_1_IMPLEMENTATION_BLUEPRINT.md` P1 | Says `0032` includes indexes | **High** | Align with `0032` columns only | Yes |
| D-10 | Blueprint P1 | Says `0036` includes an index | High | Remove index; defer to P8 | Yes |
| D-11 | Blueprint M2 | Says `retry_of` is in `0033` | Medium | Correct to `0032` | Yes |
| D-12 | Blueprint M5 | Says `0035` includes unique/active indexes | **High** | Move to optional `0035b`/P7 | Yes |
| D-13 | `RELEASE_1_MIGRATION_PLAN.md` §3 | `0032` field table still lists indexes for lease/progress/retry | **High** | Mark indexes as `0032b`/deferred | Yes |
| D-14 | Migration plan §6 | `0035` shows jobs indexes/unique guards | **High** | Mark as `0035b`/P7 optional | Yes |
| D-15 | `RELEASE_1_DEPLOYMENT.md` phases | Phase list does not mention `0032b`; phase 1 is “Schema 0032” | Low | Add a note that the final runbook is authoritative | No |
| D-16 | `RELEASE_1_P1_OPERATOR_RUNBOOK.md` | Earlier runbook may differ from final runbook | Low | Mark final runbook as superseding; do not use earlier | No |
| D-17 | P1 scope §10 | P1 boundary says “all revisions 0032–0036”; does not mention TPM ordering | Medium | Add TPM-before-autocommit and per-revision requirement | Yes |

## 3. Positive confirmations

| Check | Result |
|---|---|
| P1 has no runtime reads/writes | Confirmed in P1 scope, register, and runbook |
| Existing API/worker compatibility | Current `Job` model and worker Core mirror do not include P1 fields; no `SELECT *` on `jobs` found |
| No P1 migration files exist | `api/migrations/versions` has no `0032`–`0036` files |
| Current DB revision | `0031`; proposed graph cannot be verified by `alembic history` until files exist |
| TPM behavior proven | Rehearsal T1/T2/T11 |
| Concurrent-index failure/recovery proven | Rehearsal T5–T8 |
| Lock/statement timeout behavior proven | Rehearsal T9/T10 |
| Final runbook sequence is unambiguous | `0032 -> 0032b -> 0033 -> 0034 -> 0035 -> 0036` |
| Deferred indexes absent from final runbook | `ix_jobs_retry_of`, `ix_jobs_schedule_window_id`, `ix_jobs_s3_uploading` are deferred |
| Full ledger graph coherent | `0036.down_revision="0035"` matches the D11 full-ledger recommendation |

## 4. Revision responsibility audit

| Revision | Responsibility in final runbook | Conflict |
|---|---|---|
| `0032` | 11 `jobs` columns only | P1 scope/blueprint still say indexes |
| `0032b` | lease/owner/progress concurrent partial indexes | P1 scope does not assign indexes here |
| `0033` | `store_path`, `spec_fingerprint`, `checkpoint_version` | Blueprint M2 says `retry_of` here; actual is `0032` |
| `0034` | `job_dispatch_outbox` + new-table indexes | No material conflict |
| `0035` | `schedule_windows` + `jobs.schedule_window_id`/`attempt_no` + new-table indexes | P1 scope/migration plan still include jobs indexes |
| `0035b` | schedule unique/partial jobs indexes | Optional; P1 scope treats them as part of `0035` |
| `0036` | S3 attempt columns only | P1 scope/blueprint include `ix_jobs_s3_uploading` |
| `0036b` | S3 partial index | Optional; P1 scope includes it in `0036` |

## 5. TPM ordering audit

Final runbook requires:

1. `transaction_per_migration=True` present.
2. `0032` columns transaction commits.
3. `0032b` autocommit block creates indexes.
4. Continue per revision.

The rehearsal proved that without TPM, an autocommit block commits all preceding
revisions. The final runbook correctly states TPM must be enabled before any
autocommit block. The P1 scope and blueprint do not state this; D-17 must be
corrected.

## 6. Application behavior audit

| Check | Result |
|---|---|
| New columns read by API | No |
| New columns read by worker | No |
| New tables read by scheduler | No |
| New tables read by reports/rollup | No |
| Feature flags introduced | No |
| API response schema changed | No |
| Frontend changed | No |
| Dependencies changed | No |
| Deployment config changed | No |

P1 is intended to be inert. Any implementation that reads the new state in P1 is
a scope violation.

## 7. Required corrections before P1 authorization

1. Amend P1 scope to match the final runbook:
   - `0032` columns only;
   - `0032b` lease/owner/progress indexes;
   - `0035` table + jobs columns + new-table indexes;
   - `0035b` optional schedule jobs indexes/P7;
   - `0036` S3 columns only;
   - `0036b` optional S3 index/P8.
2. Remove `ix_jobs_retry_of`, `ix_jobs_schedule_window_id`, and
   `ix_jobs_s3_uploading` from P1.
3. Replace `upgrade 0031:0036` with the per-revision sequence.
4. Correct blueprint M2 (`retry_of` in `0032`).
5. Correct blueprint M5/M6 index ownership.
6. Correct migration plan sections 3 and 6.
7. Add TPM-before-autocommit to the P1 scope and checklist.
8. Mark the earlier runbook as superseded.

## 8. Discrepancy verdict

**P1 execution is blocked by documentation inconsistencies, not by a discovered
technical failure.**

The technical mechanism is validated, but the source documents still describe
the old index placement and bundle execution. Correcting those documents is a
MUST CLOSE BEFORE P1 item.

## 9. Stop condition

This report is documentation only. Do not create or modify migrations, `env.py`,
`deploy.sh`, application code, or production settings. P1 remains unauthorized.
