# Release 1 P1 Engineering Authorization

Status: **authorization design only.** Gate A is **not granted** by this document.
No migration, `env.py`, `deploy.sh`, application source, schema, API, frontend,
dependency, deployment, or production setting was changed.

Canonical action/evidence source: `RELEASE_1_GATE_A_CANONICAL_REGISTER.md`.
S-00 must pass before E-03/E-04; S-01 verifies the actual environment.

## 1. Purpose

Separate **engineering implementation authorization** from **production migration
authorization**.

- **Gate A** allows controlled implementation in an isolated development branch
  and test environment.
- **Gate B** allows the P1 migration against production. Gate B is defined in
  [`RELEASE_1_P1_PRODUCTION_AUTHORIZATION.md`](./RELEASE_1_P1_PRODUCTION_AUTHORIZATION.md).

Gate A does not authorize production access, production schema changes, or
runtime behavior.

## 2. Gate A scope

### 2.1 Permitted

- Implement `transaction_per_migration=True` in `api/migrations/env.py` on an
  isolated engineering branch.
- Create P1 migrations:
  - `0032_job_ownership_and_completion.py`
  - `0032b_jobs_lease_indexes.py`
  - `0033_job_artifact_paths.py`
  - `0034_job_dispatch_outbox.py`
  - `0035_schedule_windows.py`
  - `0036_s3_attempt_publication.py`
- Add inert SQLAlchemy model declarations in `api/app/models.py`.
- Add inert Core mirror declarations in `worker/app/db.py`.
- Add migration test harness and fixtures under a test-only path.
- Run PostgreSQL 16 integration tests in an isolated database/container.
- Run failure-injection, rollback, and recovery tests in isolation.

### 2.2 Prohibited

- Production database migration or connection.
- Production schema change.
- Production deployment or configuration change.
- Enabling fencing, re-dispatch, outbox publishing, schedule scanning, attempt
  paths, S3 publication, or any P2 behavior.
- P2 implementation.
- API response or frontend changes.
- Dependency changes.
- Production Redis/S3/Celery changes.
- Merging the engineering branch to the production branch without Gate B.

### 2.3 Isolation requirements

- Dedicated branch/worktree; no production credentials.
- Disposable PostgreSQL 16 database/container.
- Test-only data and fixtures.
- No connection to the production database.
- No use of production backup/restore credentials.
- Test artifacts clearly labeled P1 engineering.

## 3. Preconditions

| Precondition | Evidence |
|---|---|
| P1 implementation specification approved | [`RELEASE_1_P1_IMPLEMENTATION_SPECIFICATION.md`](./RELEASE_1_P1_IMPLEMENTATION_SPECIFICATION.md) |
| P1 test specification approved | [`RELEASE_1_P1_IMPLEMENTATION_TEST_SPEC.md`](./RELEASE_1_P1_IMPLEMENTATION_TEST_SPEC.md) |
| D11 business record signed | Full ledger; include `0035`; `0036.down_revision="0035"` |
| P1/P2 boundary approved | Inert schema only; no runtime reads |
| Index deferrals approved | No `ix_jobs_retry_of`, `ix_jobs_schedule_window_id`, `ix_jobs_s3_uploading` in P1 |
| Engineering owner named | Name/role in approval record |
| Isolated environment available | PostgreSQL 16, API image, Alembic 1.14.0 |
| No production access | Confirmed in writing |

If D11 is not signed, Gate A may cover only `0032`, `0032b`, `0033`, and `0034`;
`0035`/`0036` remain blocked. Do not invent a ledger decision.

## 4. Technical decisions for engineering

These are recommendations; business/DBA items remain subject to approval.

| Question | Recommendation | Approval status |
|---|---|---|
| `0032b` filename | `0032b_jobs_lease_indexes.py`; revision `0032b`; down revision `0032` | Engineering decision |
| Inert model declarations in P1 | **Yes.** Add only P1 columns/tables to API ORM and worker Core mirror; no queries or behavior | Engineering, with review |
| `sa.JSON` vs JSONB | **`sa.JSON`** for portability and consistency with existing models; no JSONB-only query in P1 | Engineering/DBA review |
| Schema/model mirror scope | Assert P1 columns only; do not fix unrelated historical mirror drift | Engineering |
| Defaults causing rewrites | Constant defaults are metadata-only on PG 11+; no rewrite. `ADD COLUMN` still takes `ACCESS EXCLUSIVE`. Measure lock, not rewrite | DBA verification |
| `completion_state` default | `'unknown'` constant | Engineering |
| `lease_token` default | `0` constant | Engineering |
| `checkpoint_version` default | `1` constant | Engineering |
| `attempt_no` default | `1` constant | Engineering |
| `s3_attempt_token` default | `0` constant | Engineering |
| New-table `now()` defaults | Only on new empty tables; no existing-table rewrite | Engineering/DBA |

### 4.1 Defaults and locking

Constant `DEFAULT` values on existing `jobs` columns are metadata-only on
PostgreSQL 11+; they do **not** rewrite the table. They still require an
`ACCESS EXCLUSIVE` lock for the `ALTER TABLE` statement. The engineering tests
must prove:

- `pg_attribute.atthasmissing` / catalog default behavior;
- no table rewrite (`relfilenode` unchanged for `jobs`);
- lock mode and hold time;
- no volatile default on an existing `jobs` column.

Do not use `DEFAULT now()` on an existing `jobs` column in P1. `now()` appears
only on new empty tables.

## 5. Gate A exit evidence

Gate A is complete only when:

- TPM is implemented and reviewed.
- All six revision files exist and the graph is linear.
- `0032` has no indexes.
- `0032b` has only lease/owner/progress partial concurrent indexes.
- Deferred indexes are absent.
- `0035` has no jobs indexes.
- `0036` has no S3 index.
- Model/mirror declarations exist and are inert.
- T-P1-001..T-P1-014 pass, or failures are explicitly waived by the engineering
  owner with rationale.
- No runtime behavior is activated.
- Evidence package is complete and reviewed.
- No production access or production change occurred.

Gate A exit does **not** authorize Gate B. It produces the evidence Gate B
requires.

## 6. Gate A approval record

| Field | Value |
|---|---|
| Gate | A — P1 engineering implementation |
| Authorized by | _pending_ |
| Date | _pending_ |
| Branch/worktree | _pending_ |
| Allowed revisions | `0032`, `0032b`, `0033`, `0034`, `0035`, `0036` (or first four if D11 unsigned) |
| Engineering owner | _pending_ |
| Test environment | _pending_ |
| Production access | **prohibited** |
| Runtime behavior | **prohibited** |
| P2 | **prohibited** |

Until this record is completed, Gate A is not granted.

## 7. Stop conditions

Stop engineering work if:

- production credentials are required;
- a test needs production data without an approved sanitized copy;
- D11 is unresolved for `0035`/`0036`;
- TPM cannot be enabled before autocommit;
- a migration would need a runtime read to pass;
- an index cannot be validated;
- a failure requires changing application behavior;
- the branch would need dependency or deployment changes.

## 8. Stop condition

This is an authorization design. Do not create migrations, modify `env.py` or
`deploy.sh`, or begin P1/P2 until Gate A is explicitly granted.
