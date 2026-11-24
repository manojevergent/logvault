# Release 1 P1 Implementation Test Specification

Status: **test specification only.** P1 is not authorized. No test, migration,
code, schema, or production change was executed by this document.

**Approval status: HOLD — A14-01 not approved.** Approval evidence must record
both paths, commit/version, individual SHA-256 hashes, approver, reviewer, and
date as defined in `RELEASE_1_GATE_A_CANONICAL_REGISTER.md`.

These tests apply after P1 migration files are created and before P1
authorization for production execution. They are not a substitute for the
production evidence plan.

## 1. Test environment

| Item | Required |
|---|---|
| PostgreSQL | 16.x, same major as production |
| Python | 3.12.x (API image) |
| Alembic | 1.14.0 |
| SQLAlchemy | 2.0.36 |
| psycopg | 3.2.3 |
| Source data | Restored 0031 production-like copy |
| Isolated DB | Disposable database/container |
| Production | Never used for destructive tests |

Every test records: environment, versions, setup, command, expected, actual,
pass/fail, evidence, duration, and operator.

## 2. Test matrix

### T-P1-001 — Revision graph validation

| Field | Detail |
|---|---|
| Setup | P1 revision files present |
| Command | `alembic -c api/alembic.ini history`; `alembic heads` |
| Expected | Single linear chain: `0031 -> 0032 -> 0032b -> 0033 -> 0034 -> 0035 -> 0036`; no `0035b`/`0036b` |
| Pass | Exact chain; one head `0036`; no missing/duplicate revision |
| Fail | Any branch, gap, extra P1 revision, or wrong down_revision |
| Evidence | Command output |

### T-P1-002 — Fresh database migration

| Field | Detail |
|---|---|
| Setup | Empty Postgres 16 database; baseline migrations `0001`..`0031` available |
| Command | `alembic upgrade 0031`, then `0032`, `0032b`, `0033`, `0034`, `0035`, `0036` |
| Expected | Baseline reaches `0031`; each P1 revision succeeds; `alembic current=0036` |
| Pass | Exit 0 each; expected objects exist; no unexpected indexes/tables |
| Fail | Any error; any revision skipped; `upgrade head` used |
| Evidence | Per-command output, schema queries |

### T-P1-003 — Existing 0031 upgrade

| Field | Detail |
|---|---|
| Setup | Restored production-like DB at revision `0031` |
| Command | Individual P1 revisions |
| Expected | Upgrade succeeds; row counts/checksums unchanged except new columns |
| Pass | `jobs` counts unchanged; new columns defaulted; no data rewrite |
| Fail | Row count change, backfill, or data mutation |
| Evidence | Before/after counts and checksums |

### T-P1-004 — Per-revision transaction behavior

| Field | Detail |
|---|---|
| Setup | `transaction_per_migration=True`; test log table or txid capture |
| Command | Apply `0032`..`0036` with a controlled failure in a later revision |
| Expected | Prior revision stays committed; failing revision rolls back; version points to prior revision |
| Pass | Committed prior data exists; failing revision objects absent; version correct |
| Fail | Prior revision rolled back or failing revision partially persisted |
| Evidence | txids, version, schema state |

### T-P1-005 — Concurrent index validity

| Field | Detail |
|---|---|
| Setup | `0032` applied; TPM active |
| Command | Apply `0032b` |
| Expected | `ix_jobs_lease`, `ix_jobs_owner`, `ix_jobs_progress` exist; `indisvalid=true` |
| Pass | All three valid; partial predicates correct; `EXPLAIN` can use expected index |
| Fail | Missing/invalid index; wrong predicate; full index instead of partial |
| Evidence | `pg_index` output, `EXPLAIN` |

### T-P1-006 — Invalid-index recovery

| Field | Detail |
|---|---|
| Setup | Force a concurrent index failure (timeout or duplicate unique test fixture) |
| Command | Inspect `pg_index.indisvalid`; `DROP INDEX CONCURRENTLY`; recreate |
| Expected | Invalid index is removed; rebuild is valid; `alembic_version` advances only after success |
| Pass | Recovery steps complete; index valid; version correct |
| Fail | Invalid index remains; revision stamps over it |
| Evidence | Failure log, `pg_index`, recovery output |

### T-P1-007 — Migration interruption

| Field | Detail |
|---|---|
| Setup | `0032b` index build on a production-like table |
| Command | Kill the Alembic process during the concurrent build |
| Expected | Prior revision remains; no valid partial index is left; invalid index is detectable |
| Pass | `alembic current` prior revision; `indisvalid=false` or absent; recovery works |
| Fail | Version advances; valid index is assumed without validation |
| Evidence | Process exit, `pg_index`, version |

### T-P1-008 — Lock acquisition timeout

| Field | Detail |
|---|---|
| Setup | Hold `ACCESS EXCLUSIVE` on `jobs` in a separate session |
| Command | Apply `0032` with `PGOPTIONS='-c lock_timeout=1s'` |
| Expected | Revision fails with lock timeout; no columns; version previous |
| Pass | `LockNotAvailable`; no partial schema; retry after release succeeds |
| Fail | Migration waits indefinitely or partially applies |
| Evidence | Error text, version, schema |

### T-P1-009 — Statement timeout

| Field | Detail |
|---|---|
| Setup | Revision with a controlled `pg_sleep` or slow statement |
| Command | Apply with `PGOPTIONS='-c statement_timeout=1s'` |
| Expected | Revision fails; prior revision remains; no partial objects |
| Pass | `QueryCanceled`; version previous; retry works |
| Fail | Transaction commits partial state |
| Evidence | Error text, version |

### T-P1-010 — Old application compatibility

| Field | Detail |
|---|---|
| Setup | Migrated 0036 copy; old API and worker images |
| Command | Old API `/ready`, job list/detail; old worker create/complete a job |
| Expected | No response/schema errors; no new field required |
| Pass | Old API/worker operate normally; no new column read |
| Fail | Missing column error, response change, task failure |
| Evidence | API logs, worker logs, responses |

### T-P1-011 — Schema/model mirror consistency

| Field | Detail |
|---|---|
| Setup | API ORM and worker Core mirror declarations present |
| Command | Compare model metadata to migrated schema; run contract tests |
| Expected | Types/nullability/defaults match; no drift |
| Pass | No unexpected diff; tests pass |
| Fail | Missing/extra column, wrong default, worker mirror mismatch |
| Evidence | Diff output, tests |

### T-P1-012 — No runtime behavior activation

| Field | Detail |
|---|---|
| Setup | P1 deployment; no P2 flags |
| Command | Static scan for reads of new columns/tables; API/worker smoke; flag inventory |
| Expected | No runtime read/write; no outbox rows; no windows; no S3 behavior; no fencing |
| Pass | No new reads; new tables 0 rows; no behavior flags; responses unchanged |
| Fail | Any P1 read/enforcement or P2 behavior |
| Evidence | Grep/static scan, table counts, health checks |

### T-P1-013 — Deferred index absence

| Field | Detail |
|---|---|
| Setup | P1 revision files and migrated schema |
| Command | Query `pg_indexes`; review migration files |
| Expected | No `ix_jobs_retry_of`, `ix_jobs_schedule_window_id`, or `ix_jobs_s3_uploading`; no `0035b`/`0036b` |
| Pass | Absent everywhere; no P1 revision creates them |
| Fail | Any deferred index appears |
| Evidence | `pg_indexes`, file review |

### T-P1-014 — TPM-before-autocommit ordering

| Field | Detail |
|---|---|
| Setup | Actual P1 revisions |
| Command | Apply `0032`, then `0032b`; capture txids/version |
| Expected | `0032` commits before `0032b` index block; prior revision not rolled into index transaction |
| Pass | Distinct txids; version `0032` before `0032b`; index valid |
| Fail | Same transaction or prior revision committed by autocommit without TPM |
| Evidence | txids, version, logs |

## 3. Failure criteria

A P1 test run fails if any of these occurs:

- `upgrade head` is used.
- A deferred index appears in P1.
- `0032` contains indexes.
- `0035` contains jobs indexes.
- `0036` contains an index.
- TPM is false.
- A concurrent index is invalid.
- A failure leaves the version ahead of the actual schema.
- Old API/worker fails.
- Any API/worker behavior reads new state.
- Row counts or committed data change unexpectedly.

## 4. Evidence to retain

- Test ID, date, operator, environment versions.
- Exact commands and `PGOPTIONS`.
- `alembic current`/`history` output.
- `pg_indexes`/`pg_index` output.
- `information_schema.columns` output.
- Row counts/checksums.
- API/worker logs and health output.
- Failure stack and recovery transcript.
- Pass/fail statement.

## 5. Stop condition

This is a test specification. Do not create migrations or execute tests against
production. P1 remains unauthorized.
