# Release 1 P1 Engineering Execution Plan

Status: **plan only.** Gate A is not granted. No migration, `env.py`,
`deploy.sh`, application source, schema, or production setting was changed.

Gate definitions:

- [`RELEASE_1_P1_ENGINEERING_AUTHORIZATION.md`](./RELEASE_1_P1_ENGINEERING_AUTHORIZATION.md)
- [`RELEASE_1_P1_PRODUCTION_AUTHORIZATION.md`](./RELEASE_1_P1_PRODUCTION_AUTHORIZATION.md)

## 1. Engineering setup

- Create a dedicated branch/worktree from the approved base.
- Confirm no production credentials or production database URL.
- Provision an isolated PostgreSQL 16 database/container.
- Use the pinned runtime: Python 3.12, Alembic 1.14.0, SQLAlchemy 2.0.36,
  psycopg 3.2.3.
- Copy or create sanitized fixtures; do not use unmasked production data.
- Record the engineering owner, branch, container IDs, and test database.

**Stop:** if production access is required, stop and request a sanitized copy.

## 2. Implementation sequence

### Step 1 — Alembic transaction configuration

- Add `transaction_per_migration=True` to the Alembic environment.
- Keep `transactional_ddl=True`.
- Do not change deployment behavior in this step.
- Review that the outer `context.begin_transaction()` becomes a no-op.

**Depends on:** Gate A approval.

**Verify:** a controlled two-revision failure shows the earlier revision
committed and the failing revision rolled back.

**Stop:** if the outer transaction remains active or TPM is not effective.

### Step 2 — Create revisions in order

| Order | Revision | Contents |
|---|---|---|
| 2.1 | `0032` | 11 `jobs` columns only |
| 2.2 | `0032b` | lease/owner/progress partial concurrent indexes |
| 2.3 | `0033` | `store_path`, `spec_fingerprint`, `checkpoint_version` |
| 2.4 | `0034` | `job_dispatch_outbox` + new-table indexes |
| 2.5 | `0035` | `schedule_windows` + `jobs` window columns + new-table indexes |
| 2.6 | `0036` | S3 attempt columns only |

**Rules:**

- No `0035b`, `0036b`, `ix_jobs_retry_of`, `ix_jobs_schedule_window_id`, or
  `ix_jobs_s3_uploading` in P1.
- No CHECK constraints (0037/P9).
- No foreign keys.
- No backfill.
- `0036.down_revision="0035"`.

**Depends on:** Step 1.

**Stop:** if a revision needs an index from a deferred phase or a runtime read.

### Step 3 — Model and mirror declarations

- Add only P1 columns/tables to `api/app/models.py`.
- Add the same P1 columns to `worker/app/db.py`.
- Do not add queries, methods, routers, or task logic.
- Add a contract test for P1 column names/types/defaults.
- Do not fix unrelated historical mirror drift.

**Depends on:** Step 2.

**Stop:** if the model change requires behavior changes to compile or pass tests.

### Step 4 — Migration graph validation

- Run `alembic history` and `alembic heads`.
- Confirm one head `0036`.
- Confirm exact chain:
  `0031 -> 0032 -> 0032b -> 0033 -> 0034 -> 0035 -> 0036`.
- Confirm `0033.down_revision="0032b"`, `0036.down_revision="0035"`.

**Depends on:** Step 2.

**Stop:** any branch, gap, duplicate head, or missing revision.

### Step 5 — Fresh database test

- Create an empty Postgres 16 database.
- Apply baseline `0001`..`0031`.
- Apply P1 revisions individually.
- Verify schema, version, and no deferred objects.

**Depends on:** Step 2.

**Stop:** any migration error or unexpected object.

### Step 6 — Existing 0031 upgrade test

- Restore a sanitized 0031 database.
- Record row counts and checksums.
- Apply P1 revisions individually.
- Verify data unchanged except new columns.

**Depends on:** Step 2, Step 5.

**Stop:** row-count change, backfill, or data mutation.

### Step 7 — Concurrent index tests

- Apply `0032b`.
- Verify `indisvalid=true` for all three indexes.
- Verify partial predicates.
- Run `EXPLAIN` for lease/progress/owner queries.
- Force an invalid index and recover with `DROP INDEX CONCURRENTLY` + recreate.

**Depends on:** Step 1, Step 2.

**Stop:** invalid index, wrong predicate, or full all-NULL index.

### Step 8 — Failure injection

Run in isolation:

- failure during `0032`;
- failure during a later revision;
- failure after `0032b` index creation;
- process kill during index build;
- lock acquisition timeout;
- statement timeout;
- invalid-index retry;
- failure after one revision commits before the next starts.

**Depends on:** Steps 5–7.

**Stop:** version advances over invalid schema; prior revision rolls back
unexpectedly; retry cannot recover.

### Step 9 — Old application compatibility

- Run the old API/worker image against the migrated 0036 copy.
- Exercise `/ready`, job list/detail, job creation/completion.
- Confirm no new column/table read is required.
- Confirm no API response changes.

**Depends on:** Steps 5–6.

**Stop:** any schema error or behavior change.

### Step 10 — Runtime behavior isolation

- Static scan for reads of new columns/tables.
- Confirm new tables have 0 rows.
- Confirm no outbox rows, no windows, no S3 attempt state.
- Confirm no P2 flags or handlers.
- Confirm API response schema unchanged.

**Depends on:** Steps 3–9.

**Stop:** any runtime dependency on P1 state.

## 3. Engineering acceptance criteria by revision

| Revision | Acceptance |
|---|---|
| `0032` | 11 columns; no indexes; one transaction; no rewrite; defaults metadata-only |
| `0032b` | Three partial indexes; `indisvalid=true`; TPM active; invalid-index recovery works |
| `0033` | Three columns; no indexes; no behavior |
| `0034` | Outbox table/indexes; 0 rows; no dispatcher |
| `0035` | Windows table/indexes; two `jobs` columns; no jobs indexes; 0 rows |
| `0036` | S3 columns; no index; no S3 behavior |
| Full P1 | Linear graph; old app compatible; no runtime reads; no deferred indexes |

## 4. Evidence package

- Branch/worktree and commit.
- Test environment versions.
- `alembic history`/`heads`.
- Per-revision commands and output.
- Schema/column/index queries.
- Row counts/checksums.
- TPM txid/failure evidence.
- Concurrent-index validity/recovery logs.
- Failure-injection transcripts.
- Old API/worker smoke results.
- Static behavior-isolation scan.
- Engineering owner sign-off.

## 5. Stop conditions

Stop and escalate if:

- Gate A is not granted.
- D11 is unresolved for `0035`/`0036`.
- TPM cannot be made effective before autocommit.
- A revision needs runtime behavior or a deferred index.
- A test requires production data or credentials.
- A model change requires API/task/frontend changes.
- Old API/worker compatibility fails.
- A failure leaves a state that cannot be recovered in isolation.

## 6. Gate A exit

Gate A exits only when:

- all six revisions exist;
- T-P1-001..T-P1-014 pass or are explicitly waived;
- acceptance criteria above pass;
- evidence package is reviewed;
- no production change occurred.

Gate A exit produces the evidence needed to apply for Gate B. It does not grant
Gate B.

## 7. Stop condition

This is an execution plan. Do not create migrations, modify `env.py`/`deploy.sh`,
or begin P1/P2 until Gate A is explicitly granted.
