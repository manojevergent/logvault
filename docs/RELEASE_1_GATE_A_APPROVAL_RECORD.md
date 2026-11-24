# Release 1 Gate A Approval Record

Status: **NOT GRANTED.** No authorization is granted by this record.

Gate A permits isolated P1 engineering implementation only. Gate B is separate
and remains not granted.

## 1. Approval

| Field | Value |
|---|---|
| Gate | A — P1 engineering implementation |
| Status | **NOT GRANTED** |
| D11 record reference | ______________________________ |
| D11 selection (FULL / REDUCED) | ______________________________ |
| Authorized revision scope | ______________________________ |
| Authorized by | ______________________________ |
| Business owner (D11) | ______________________________ |
| Engineering owner | ______________________________ |
| Backup engineering owner | ______________________________ |
| Branch/worktree | ______________________________ |
| Isolated PostgreSQL 16 environment | ______________________________ |
| Approval date | ______________________________ |
| Engineering change/ticket (Gate A; not a production deployment record) | ______________________________ |

## 2. Authorized revision scope

Select the scope that matches the signed D11 record:

### D11 FULL

- `0032` — ownership/completion columns only.
- `0032b` — lease/owner/progress partial concurrent indexes.
- `0033` — artifact/checkpoint columns.
- `0034` — dispatch outbox table/indexes.
- `0035` — schedule_windows table + `jobs` window columns + new-table indexes.
- `0036` — S3 attempt columns; `down_revision="0035"`; no index.

### D11 REDUCED

- `0032` — ownership/completion columns only.
- `0032b` — lease/owner/progress partial concurrent indexes.
- `0033` — artifact/checkpoint columns.
- `0034` — dispatch outbox table/indexes.
- `0035` and `0036` are **excluded**.

## 3. Permitted work

- Implement `transaction_per_migration=True`.
- Create the authorized revision files.
- Add inert API/worker model declarations for the authorized revisions.
- Add migration test harness and fixtures.
- Run PostgreSQL 16 integration tests.
- Run failure-injection, rollback/recovery, and old-application compatibility
  tests in isolation.

## 4. Prohibited work

- Production database access or migration.
- Production schema change.
- Production deployment or configuration change.
- Runtime behavior or P2 implementation.
- API/frontend/response changes.
- Dependency changes.
- Redis/S3/Celery production changes.
- `alembic upgrade head` for P1 execution.
- Deferred indexes (`ix_jobs_retry_of`, `ix_jobs_schedule_window_id`,
  `ix_jobs_s3_uploading`) or `0035b`/`0036b`.

## 5. Preconditions

- [ ] D11 signed FULL or REDUCED.
- [ ] Primary and backup engineering owners named.
- [ ] Dedicated branch/worktree recorded.
- [ ] Isolated PostgreSQL 16 environment recorded.
- [ ] Production isolation confirmation signed.
- [ ] No production DB credentials.
- [ ] No production deployment permissions.
- [ ] P1 implementation specification and test spec approved per EV-SPEC-01.
- [ ] P-04 records propagation complete.
- [ ] A-14 approved with exact paths, commit/version, and individual SHA-256.

## 6. Evidence package required at Gate A exit

- TPM implementation review.
- Revision files and `alembic history`/`heads`.
- Schema/index/column evidence.
- TPM failure-boundary evidence.
- Concurrent-index validity/recovery evidence.
- Failure-injection transcripts.
- Old API/worker compatibility.
- Runtime behavior isolation scan.
- Engineering owner sign-off.

## 7. Status

**NOT GRANTED.**

Operator runbook acknowledgement is a Gate B requirement, not a Gate A
prerequisite. Gate B requires the current
`RELEASE_1_P1_FINAL_OPERATOR_RUNBOOK.md`, not the superseded
`RELEASE_1_P1_OPERATOR_RUNBOOK.md`.

Gate A must not be treated as granted until the project owner completes this
record, the D11 record, the ownership record, and the production isolation
confirmation.
