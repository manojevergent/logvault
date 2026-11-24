# Release 1 P1 Migration Execution Strategy

Status: **design only.** No code, migration, deployment, or schema change was
made. P1 remains unauthorized.

Supersedes the execution assumptions in
[`RELEASE_1_P1_SCOPE_AND_MIGRATION.md`](./RELEASE_1_P1_SCOPE_AND_MIGRATION.md)
and answers the NO-GO in
[`RELEASE_1_P1_MIGRATION_SAFETY_PREFLIGHT.md`](./RELEASE_1_P1_MIGRATION_SAFETY_PREFLIGHT.md).

Companion documents:

- [`RELEASE_1_P1_LOCK_AND_INDEX_STRATEGY.md`](./RELEASE_1_P1_LOCK_AND_INDEX_STRATEGY.md)
- [`RELEASE_1_P1_MIGRATION_SEQUENCE.md`](./RELEASE_1_P1_MIGRATION_SEQUENCE.md)
- [`RELEASE_1_P1_BACKUP_AND_RECOVERY_PLAN.md`](./RELEASE_1_P1_BACKUP_AND_RECOVERY_PLAN.md)
- [`RELEASE_1_P1_FINAL_GO_NO_GO.md`](./RELEASE_1_P1_FINAL_GO_NO_GO.md)

## 1. Current behavior

### 1.1 What the code does

`api/migrations/env.py:39-48`:

```python
def run_migrations_online() -> None:
    connectable = engine_from_config(..., poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
```

Alembic is **1.14.0**. `transaction_per_migration` is not set in `env.py` or
`alembic.ini`. PostgreSQL supports transactional DDL, so the default is:

- `transactional_ddl=True`
- `transaction_per_migration=False`

`context.begin_transaction()` with `_per_migration=False` starts one real
transaction around `context.run_migrations()`. Inside `run_migrations()`, each
revision asks for `begin_transaction(_per_migration=True)`, but because
`transaction_per_migration` is false, that call returns a no-op context. All
revisions therefore run in the **one outer transaction**.

### 1.2 Why that is dangerous here

`deploy.sh` runs:

```bash
"$COMPOSE" run --rm --no-deps api alembic upgrade head
"$COMPOSE" up -d --no-deps "$SERVICES"
```

The migration runs while the old API and worker are still serving. Because
`0032` starts with `ALTER TABLE jobs`, the first `ACCESS EXCLUSIVE` lock is held
until the final commit of `0036`. That means:

- all reads and writes on `jobs` block for the whole bundle;
- worker progress/checkpoints block;
- scheduler scans and job creation block;
- a failure rolls back everything (good atomicity, but the lock is still held
  until rollback);
- `CREATE INDEX CONCURRENTLY` cannot run at all.

### 1.3 What this document changes

This document separates three concerns that were previously conflated:

1. **Transaction boundary** — each revision must commit independently.
2. **Revision granularity** — one revision must not combine many `ALTER TABLE`
   statements with index builds.
3. **Non-transactional operations** — concurrent indexes must run outside a
   transaction, with their own failure/retry model.

Changing only `transaction_per_migration` solves (1), not (2) or (3).

## 2. Target architecture

### 2.1 Per-revision transactions

**Decision:** configure Alembic with:

```python
context.configure(
    connection=connection,
    target_metadata=target_metadata,
    transactional_ddl=True,
    transaction_per_migration=True,
)
```

This is a **future P1 infrastructure change**. It is not made by this document.

Why it works with the existing wrapper:

- The outer `context.begin_transaction()` is called with
  `_per_migration=False`.
- With `transaction_per_migration=True`, that outer call returns a no-op.
- Each revision's `begin_transaction(_per_migration=True)` now starts a real
  transaction.
- The revision's DDL and its `alembic_version` update commit together at the end
  of that revision.

This is the correct use of Alembic's model. Do not set
`transactional_ddl=False`; PostgreSQL supports transactional DDL, and turning
it off would weaken atomicity and make failure recovery harder.

### 2.2 Per-revision invocation

Even with `transaction_per_migration=True`, the P1 window should **not** use
`alembic upgrade head`. The operator should apply one revision at a time:

```text
alembic upgrade 0032
alembic upgrade 0032b
alembic upgrade 0033
...
```

Reasons:

- Each command has an explicit stopping point and verification gate.
- A failure is localized to one revision.
- The operator can measure lock waits and duration per revision.
- A revision can be retried without re-running earlier work.
- The change window can be aborted between revisions.

`upgrade head` remains acceptable for ordinary development, not for the P1
production window until the split and index strategy are proven.

### 2.3 Revision granularity

**Decision:** split P1 into schema revisions and index revisions.

| Revision | Contents | Transaction |
|---|---|---|
| `0032` | `jobs` ownership/completion columns only | One short transaction |
| `0032b` | `jobs` lease/owner/progress partial indexes (concurrent) | Autocommit block(s) |
| `0033` | `jobs` artifact/checkpoint columns | One short transaction |
| `0034` | `job_dispatch_outbox` table + new-table indexes | One short transaction |
| `0035` | `schedule_windows` table + `jobs` window columns + new-table indexes | One short transaction |
| `0036` | `jobs` S3 attempt columns | One short transaction |

`0035b` (schedule jobs indexes) and `0036b` (S3 index) are **not part of P1**.
They are future P7/P8 revisions. `ix_jobs_retry_of`,
`ix_jobs_schedule_window_id`, and `ix_jobs_s3_uploading` are also deferred.

The exact index decisions are in
[`RELEASE_1_P1_LOCK_AND_INDEX_STRATEGY.md`](./RELEASE_1_P1_LOCK_AND_INDEX_STRATEGY.md).

No revision combines:

- many `ALTER TABLE` statements and index builds;
- transactional DDL and a concurrent index;
- two independently retryable concurrent indexes without explicit recovery.

### 2.4 Non-transactional operations

`CREATE INDEX CONCURRENTLY` cannot run inside a transaction block. Use one of:

**Option A — Alembic autocommit block (preferred if migrations remain the source
of truth):**

```python
def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_jobs_lease "
            "ON jobs (status, lease_expires_at) "
            "WHERE lease_expires_at IS NOT NULL"
        )
```

`autocommit_block()` **unconditionally commits** the transaction preceding the
block, switches the connection to AUTOCOMMIT, runs the statement, then starts a
new transaction for the rest of the revision. This is why it must be used with
`transaction_per_migration=True` and in a dedicated revision.

**Option B — external operational step:**

Run the concurrent index creation outside Alembic, verify it, then stamp a
marker revision. This avoids autocommit complexity but splits schema state
between Alembic and an operator script. It requires a written procedure and an
audit step.

**Recommendation:** Option A for P1 index revisions, with Option B as a fallback
if the Alembic version or driver behavior is not proven in staging.

Do **not** put `CREATE INDEX CONCURRENTLY` in a normal transactional revision
and hope it works. It will fail with
`CREATE INDEX CONCURRENTLY cannot run inside a transaction block`.

### 2.5 Revision-state consistency

Alembic updates `alembic_version` inside the revision's transaction. Therefore:

| Scenario | State |
|---|---|
| Transactional revision succeeds | Version advances; DDL committed |
| Transactional revision fails | Version stays at previous; DDL rolled back |
| Process killed during transactional revision | Connection closes; PostgreSQL rolls back; version stays previous |
| Autocommit index succeeds, then revision stamp commits | Version advances; index valid |
| Autocommit index succeeds, then later statement fails | Index remains; version may stay previous |
| Autocommit index fails | Invalid index may remain; version stays previous |

The last two are the dangerous cases. The retry procedure must inspect the
catalog, not trust `alembic_version` alone.

### 2.6 Failure and retry model

**Transactional revision failure:**

1. Stop the sequence.
2. Confirm `alembic current` is the previous revision.
3. Confirm no new columns/tables/indexes from the failed revision remain.
4. Fix the cause (lock timeout, disk, bad DDL).
5. Re-run that revision.

**Autocommit index failure:**

1. Stop.
2. Check `pg_index.indisvalid` for the index name.
3. If invalid, `DROP INDEX CONCURRENTLY <name>`.
4. Recreate the index concurrently.
5. Verify `indisvalid=true`.
6. Only then stamp/continue.

`CREATE INDEX CONCURRENTLY IF NOT EXISTS` is not enough on its own: an invalid
index still "exists," so `IF NOT EXISTS` can silently skip the rebuild. Always
validate.

**Deployment failure after migration but before app redeploy:**

P1 is additive and old code ignores the new objects. Fix the deployment; do not
roll back the schema just because the new image did not start.

**Version says head but objects are missing:**

Do not `alembic stamp` over it. Audit `information_schema.columns`,
`pg_tables`, and `pg_indexes`. Repair the actual state first.

### 2.7 Why not just change one setting?

`transaction_per_migration=True` alone would:

- commit each revision independently (good);
- still run all eleven `ALTER TABLE` statements and four index builds of `0032`
  in one transaction (bad);
- still fail on `CREATE INDEX CONCURRENTLY` (bad);
- still leave `deploy.sh` using `upgrade head` (operationally blind);
- still leave `lock_timeout=0` (unbounded wait).

The complete strategy needs all four changes: per-revision transactions, split
revisions, autocommit/concurrent indexes, and bounded lock waits.

### 2.8 Rehearsal evidence

The isolated rehearsal in
[`RELEASE_1_P1_MIGRATION_REHEARSAL_REPORT.md`](./RELEASE_1_P1_MIGRATION_REHEARSAL_REPORT.md)
confirms:

- with `transaction_per_migration=False`, revision 1 rolls back when revision 2
  fails;
- with `transaction_per_migration=True`, revision 1 remains committed and
  `alembic_version` stays at revision 1;
- the outer `context.begin_transaction()` is active when the flag is false and a
  no-op when true;
- concurrent indexes work in `autocommit_block`;
- an invalid concurrent index remains after failure and can be dropped/rebuilt;
- process termination during an index build leaves an invalid index;
- `lock_timeout` and `statement_timeout` abort only the current revision.

**Critical nuance:** `autocommit_block` commits all preceding revisions even when
`transaction_per_migration=False`. The rehearsal observed revisions 1–3 sharing
one txid and revision 4 (autocommit index) in a new txid. Therefore
`transaction_per_migration=True` must be enabled **before** any autocommit index
revision; otherwise a later concurrent-index revision silently commits earlier
schema work.

## 3. Deployment procedure design

This is the future P1 procedure; it is not executed now.

### 3.1 Preconditions

- P1 scope and index decisions approved.
- Fresh verified backup and restore test complete.
- Production-sized copy measurement complete.
- Old API/worker compatibility test complete.
- Change window approved; migration owner named.
- Backup service paused for the window, or its dump confirmed finished.
- No long-running transactions on `jobs`.

### 3.2 Session guards

Before each Alembic invocation, set:

```sql
SET lock_timeout = '<tested value>';
SET statement_timeout = '<tested value>';
SET idle_in_transaction_session_timeout = '<tested value>';
```

Values are determined in
[`RELEASE_1_P1_LOCK_AND_INDEX_STRATEGY.md`](./RELEASE_1_P1_LOCK_AND_INDEX_STRATEGY.md).
They are not fixed here.

### 3.3 Execution

1. `alembic current` — confirm expected revision.
2. Apply one transactional schema revision.
3. Verify schema, locks, API health, worker heartbeat.
4. Apply the matching concurrent index revision, if any.
5. Verify `pg_index.indisvalid` and query plans.
6. Repeat for the next revision.
7. Do not apply P2 behavior in the same deployment.

### 3.4 Stop conditions

Abort the sequence and do not continue if:

- a lock timeout occurs;
- a revision fails;
- an index is invalid;
- API error rate or worker heartbeat degrades;
- a long transaction appears on `jobs`;
- disk or connection headroom is insufficient.

## 4. Decision summary

| Decision | Recommendation |
|---|---|
| Transaction model | `transaction_per_migration=True` plus per-revision invocation |
| Revision granularity | Split columns/tables from concurrent indexes |
| Concurrent indexes | Dedicated revisions with `autocommit_block` or external step |
| `upgrade head` in P1 | Do not use |
| Failure handling | Stop, inspect catalog, retry only after validation |
| Version trust | `alembic_version` plus catalog verification |
| Rollback | P1-only downgrade is safe before P2; after P2, roll back P2 first |

## 5. Stop condition

This is a design proposal. `env.py`, `deploy.sh`, migrations, source, schema,
API, frontend, dependencies, and deployment configuration remain unchanged.
P1 remains unauthorized.
