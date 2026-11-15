# Release 1 P1 Migration Safety Preflight

Status: **preflight report only.** No migration was created, modified, or
executed. No application source, schema, API, frontend, dependency, or
deployment configuration was changed. P1 and P2 remain unauthorized.

**Historical audit note:** this preflight retains its original audit content.
For current D11 scope and Gate A IDs, use
`RELEASE_1_GATE_A_CANONICAL_REGISTER.md` and the signed D11 record.

**Follow-up:** the execution redesign is in
[`RELEASE_1_P1_MIGRATION_EXECUTION_STRATEGY.md`](./RELEASE_1_P1_MIGRATION_EXECUTION_STRATEGY.md),
with the final verdict in
[`RELEASE_1_P1_FINAL_GO_NO_GO.md`](./RELEASE_1_P1_FINAL_GO_NO_GO.md). This
preflight remains the evidence for why the one-shot bundle was rejected.

Scope: proposed P1 migrations `0032`–`0036` and the P1 boundary in
[`RELEASE_1_P1_SCOPE_AND_MIGRATION.md`](./RELEASE_1_P1_SCOPE_AND_MIGRATION.md).

Method: source/config inspection plus **read-only** queries against the running
compose stack. At preflight time, `0032`–`0036` are **specified but not present**
in `api/migrations/versions`; the review evaluates the specified DDL against the
actual execution environment. The observed environment is reported separately
from the production target because the two may not be the same size.

## 1. Executive verdict

**P1 is NOT approved for implementation by this preflight.**

P1 can proceed only after the blockers in section 12 are resolved. The decisive
finding is not the additive columns themselves; it is the execution model:

- `api/migrations/env.py` wraps all migrations in **one outer transaction**
  (`context.begin_transaction()` around `context.run_migrations()`).
- `deploy.sh` runs `alembic upgrade head` while the old API and worker are still
  serving.
- Therefore `0032`–`0036` would run in **one transaction**, and the
  `ACCESS EXCLUSIVE` lock taken by the first `ALTER TABLE jobs` is held until the
  final commit.
- That blocks **reads and writes** on `jobs` for the whole bundle, not just for
  each short DDL statement.
- `CREATE INDEX CONCURRENTLY` cannot run inside that transaction. The current
  plan's concurrent-index option would fail unless `env.py` or the execution
  procedure changes.

In the observed 25 MB database this is likely seconds. In a larger production
database it is an unbounded operational outage risk. "Additive" is not the same
as "non-blocking."

**Overall classification: HIGH risk as currently specified.**
**Conditional path exists:** per-revision execution, lock timeouts, measured
copy, verified backup, and either a maintenance window or a concurrent-index
procedure. That path still requires explicit approval.

## 2. Observed environment (read-only)

| Item | Observation |
|---|---|
| PostgreSQL | 16.14, x86_64 Alpine |
| Database | `logvault`, 25 MB |
| Alembic revision | `0031` |
| `jobs` rows | 829 live, 115 dead (exact count 829) |
| `jobs` status sample | completed 686, canceled 109, failed 34; no queued/running/paused at sample time |
| `jobs` size | 1.2 MB heap, 368 kB indexes, 11 MB total including TOAST |
| `job_events` | 22,801 rows, 4.1 MB total |
| `schedules` | 0 rows |
| `extraction_groups` | 0 rows |
| Existing `jobs` indexes | 8; no proposed index name is already in use |
| `job_dispatch_outbox` | Does not exist |
| `schedule_windows` | Does not exist |
| `max_connections` | 100 |
| `shared_buffers` | 128 MB |
| `work_mem` | 4 MB |
| `maintenance_work_mem` | 64 MB |
| `lock_timeout` | 0 (disabled) |
| `statement_timeout` | 0 (disabled) |
| `idle_in_transaction_session_timeout` | 0 (disabled) |
| Isolation | read committed |
| Long transactions at sample | none; 0 idle-in-transaction, 1 active |
| Disk free in container | ~936 GB |
| Write activity since last stats reset | 149 inserts, 2,350 updates, 33 deletes on `jobs` |
| Backup | daily `pg_dump -Fc`, 14-day retention, same host disk |

**Interpretation:** the observed database is small. The 829-row count makes the
DDL itself cheap. It does **not** prove production size, production lock
duration, or production traffic. If the production target is larger, every
duration below must be re-measured.

## 3. Critical execution facts

### 3.1 One transaction, all revisions

`api/migrations/env.py:45-48`:

```python
with connectable.connect() as connection:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()
```

Alembic is 1.14.0. `transaction_per_migration` is not set in `alembic.ini` or
`env.py`. PostgreSQL supports transactional DDL. Therefore a single
`alembic upgrade head` runs `0032`–`0036` in one transaction.

Consequences:

- `ALTER TABLE jobs ... ADD COLUMN` takes `ACCESS EXCLUSIVE` and holds it until
  the outer commit.
- Every later migration and index build runs while that lock is held.
- Other sessions cannot `SELECT`, `INSERT`, `UPDATE`, or `DELETE` on `jobs`.
- API list/detail/status requests, worker progress writes, and job creation all
  block behind the migration.
- A failure rolls back the whole bundle, which is good for schema atomicity but
  does not shorten the lock window.

### 3.2 Deployment path

`deploy.sh:21-27`:

```bash
"$COMPOSE" run --rm --no-deps api alembic upgrade head
"$COMPOSE" up -d --no-deps "$SERVICES"
```

The migration runs against the live database **before** the new API/worker are
redeployed. Old code is serving during the entire lock window. P1's additive
compatibility makes that safe from a schema perspective, but not from a
latency/availability perspective.

`install-prod.sh:291-293` also runs `alembic upgrade head` in one invocation.

### 3.3 Concurrent index incompatibility

`CREATE INDEX CONCURRENTLY` cannot run inside a transaction block. It will fail
under the current `env.py`. Using it requires one of:

1. `transaction_per_migration=True` plus
   `op.get_context().autocommit_block()` around the concurrent statement;
2. a separate operational step outside Alembic;
3. a migration environment change approved as part of P1.

That is an infrastructure change, not an additive schema change. It must be
explicitly authorized and tested.

### 3.4 Lock timeouts are disabled

`lock_timeout=0` and `statement_timeout=0`. A migration waiting for
`ACCESS EXCLUSIVE` can wait indefinitely behind a long-running transaction. While
it waits, new queries queue behind it. This is how a brief DDL becomes a full
outage without any statement actually being slow.

P1 must set a bounded `lock_timeout` (and preferably a conservative
`statement_timeout`) for the migration session, then retry in a controlled
window.

## 4. Cross-cutting risk assessment

| Concern | Assessment |
|---|---|
| Table rewrite | **None expected.** PG 11+ stores a constant `ADD COLUMN ... DEFAULT` in the catalog. `NOT NULL DEFAULT` with a constant is also metadata-only. No type changes, no volatile defaults, no backfill. |
| `ACCESS EXCLUSIVE` | Taken by every `ALTER TABLE jobs`. Brief per statement, but held to transaction end. This is the primary risk. |
| `CREATE INDEX` (normal) | Takes `SHARE`; blocks writes, allows reads. In the current bundle it is dominated by the already-held `ACCESS EXCLUSIVE`. |
| `CREATE INDEX CONCURRENTLY` | Takes `SHARE UPDATE EXCLUSIVE`; allows reads/writes but cannot run in the current transaction. Can leave an invalid index on failure. |
| New tables | `CREATE TABLE` locks only the new table. No existing traffic. |
| Unique indexes | Safe in P1 because all new key columns are NULL. They can reject future duplicate writes in P2+, which is intended. |
| Application behavior | No runtime code reads the new columns/tables. Latent effects: planner may choose new indexes; unique constraints apply to future writes; model declarations can add defaulted columns to inserts. |
| Partial failure | Single transaction: all-or-nothing. Split revisions/concurrent indexes: partial state and invalid indexes are possible. |
| Backup | Latest dump is more than 24 hours old and valid; a zero-byte dump exists. No WAL/PITR. Restore is dump-only. |

### 4.1 Expected duration and operational impact

No migration was executed, so durations are estimates from object size, not
measurements.

| Phase | Observed 25 MB environment | Larger production |
|---|---|---|
| `ADD COLUMN` metadata updates | Sub-second total | Milliseconds per statement; lock wait dominates |
| Index builds on 829 rows | Likely sub-second each | O(rows); can be seconds to minutes |
| New empty tables/indexes | Sub-second | Sub-second |
| Whole P1 via `upgrade head` | Likely a few seconds | Unknown; bounded only by table size and lock wait |

Operational impact while the `ACCESS EXCLUSIVE` lock is held:

- `GET /jobs`, job detail, status polling, and job creation block.
- Worker checkpoint/progress updates block.
- Cancel/pause/resume writes block.
- Celery tasks may appear hung, exceed client timeouts, or be retried.
- The embedded beat scheduler (`celery worker -B`) may block on its 60 s scan
  and delay scheduled dispatch.
- Reaper, cleanup, and health tasks that read `jobs` may block or log timeout
  errors; this is not data corruption, but it can look like a worker outage.
- No data is lost by blocking, but an unbounded lock wait looks like an outage.

With per-revision execution and concurrent indexes, the `ADD COLUMN` locks are
brief and index builds do not block writes. The migration still needs a
low-traffic window because `jobs` is on every request path.

### 4.2 Can P1 run while normal traffic continues?

**Not as currently specified.** `alembic upgrade head` + one transaction +
`ACCESS EXCLUSIVE` on `jobs` is a stop-the-world operation for that table.

**Conditionally yes**, after:

- per-revision or autocommit execution;
- concurrent index creation, or an accepted measured maintenance window;
- bounded `lock_timeout`;
- verified fresh backup and rollback rehearsal;
- a production-sized copy measurement.

Even then, brief `ACCESS EXCLUSIVE` locks remain for `ADD COLUMN`; "concurrent
indexes" does not make column addition lock-free.


## 5. Migration 0032 — job ownership and completion

### 5.1 Exact objects affected

On `jobs`:

| Column | Type | Null/default |
|---|---|---|
| `owner_id` | `varchar(128)` | NULL |
| `lease_token` | `bigint` | NOT NULL DEFAULT 0 |
| `lease_expires_at` | `timestamptz` | NULL |
| `heartbeat_at` | `timestamptz` | NULL |
| `progress_at` | `timestamptz` | NULL |
| `pause_requested_at` | `timestamptz` | NULL |
| `cancel_requested_at` | `timestamptz` | NULL |
| `completion_state` | `varchar(16)` | NOT NULL DEFAULT `'unknown'` |
| `gap_count` | `integer` | NOT NULL DEFAULT 0 |
| `gap_reason` | `text` | NULL |
| `retry_of` | `integer` | NULL |

Indexes:

- `ix_jobs_lease (status, lease_expires_at)`
- `ix_jobs_owner (owner_id) WHERE owner_id IS NOT NULL`
- `ix_jobs_progress (status, progress_at)`
- `ix_jobs_retry_of (retry_of)`

No foreign keys. No CHECK constraints (deferred to `0037`).

### 5.2 Risk classification

**HIGH as currently executed; MEDIUM if split and controlled.**

The columns are metadata-only. The risk is the lock lifetime across eleven
`ALTER TABLE` statements plus four index builds in one transaction. Two of the
indexes (`ix_jobs_retry_of`, and initially `ix_jobs_progress`) have no useful
non-null keys in existing rows yet still create entries. `ix_jobs_retry_of`
should be partial (`WHERE retry_of IS NOT NULL`); `ix_jobs_progress` and
`ix_jobs_lease` should be considered partial as well if terminal rows clear the
lease.

### 5.3 Locking implications

- Each `ADD COLUMN` requests `ACCESS EXCLUSIVE` on `jobs`.
- All four `CREATE INDEX` statements request `SHARE` on `jobs`.
- Because they share one transaction, the `ACCESS EXCLUSIVE` lock is held until
  the final commit of the bundle.
- During that time, all reads and writes to `jobs` block. This includes API
  polling, job creation, worker checkpoint/progress writes, and cancel/pause.
- Lock acquisition can also queue behind a long transaction; with
  `lock_timeout=0`, the queue can grow without bound.

### 5.4 Compatibility assessment

**Schema-compatible with old API/worker.** Both use explicit column lists;
no `SELECT *` on `jobs` was found. Old inserts omit the new columns and receive
DB defaults. Old reads ignore them. `JobOut` is unchanged, so responses are
unchanged. The worker Core mirror in `worker/app/db.py` does not know the new
columns and does not need them for P1.

Latent compatibility notes:

- `completion_state='unknown'` is assigned to every existing and newly inserted
  row. No current code reads it.
- New indexes may change existing query plans. That is a performance risk, not a
  correctness change.
- If P1 also adds model declarations, inserts include the defaulted columns;
  values match DB defaults. Do not add any router/schema field yet.

### 5.5 Failure scenarios

| Failure | Effect | Recovery |
|---|---|---|
| Lock wait exceeds control / long transaction | All `jobs` access queues; API/worker stall | Set `lock_timeout`; identify blockers with `pg_blocking_pids`; retry in window |
| Migration timeout / cancellation | Transaction rolls back; revision stays 0031 | Fix and re-run; verify no columns/indexes remain |
| Disk full during index build | Transaction rolls back | Free space; re-run |
| Container killed | Connection closes; PostgreSQL rolls back | Verify `alembic_version=0031`; re-run |
| Concurrent index used incorrectly | `CREATE INDEX CONCURRENTLY cannot run inside a transaction block` | Change execution model; do not retry blindly |
| Duplicate index/column after manual partial work | Migration fails on existing object | Audit `pg_attribute`/`pg_index`; remove only confirmed P1 objects; re-run |
| Unexpected non-null data in a new indexed column | Index build behavior differs from expectation | Audit the new columns (should be all NULL); do not force |

### 5.6 Recovery procedure

1. Confirm the transaction rolled back: `alembic_version` is still `0031`; no new
   `jobs` columns/indexes exist.
2. Check for blocked sessions and locks before retrying:
   `pg_stat_activity`, `pg_locks`, `pg_blocking_pids`.
3. If a manual/concurrent path left an invalid index, inspect
   `pg_index.indisvalid`; `DROP INDEX CONCURRENTLY` and recreate.
4. Never `alembic stamp` over unknown state. Audit first.
5. Re-run only after the lock-timeout and window controls are in place.

### 5.7 Required pre-production tests

- Apply to a restored production copy with the **same row count and index set**.
- Capture lock waits, total duration, and `pg_stat_activity` during the run.
- Run concurrent API-like reads/writes and a worker-like update stream.
- Verify all columns/defaults and `pg_index.indisvalid`.
- Verify old API/worker image against the migrated copy.
- Repeat with `lock_timeout` set and with an injected long transaction.
- Kill the migration container mid-run and verify clean rollback.
- Downgrade and re-upgrade.
- Confirm no API response or task behavior changed.

### 5.8 Go/no-go

**NO-GO as specified for live traffic.** Conditional GO only after the bundle is
split or the execution model is changed, `lock_timeout` is set, index
definitions are reviewed (prefer partial indexes), and duration is measured on a
production-sized copy.

## 6. Migration 0033 — job artifact and checkpoint pointers

### 6.1 Exact objects affected

On `jobs`:

- `store_path text NULL`
- `spec_fingerprint varchar(64) NULL`
- `checkpoint_version integer NOT NULL DEFAULT 1`

No indexes. No constraints.

### 6.2 Risk classification

**LOW.** Three metadata-only `ADD COLUMN` statements, no rewrite, no backfill, no
index build.

### 6.3 Locking implications

Each `ADD COLUMN` takes a brief `ACCESS EXCLUSIVE` on `jobs`. Under the current
single transaction, that lock is held until the end of the whole bundle; in
isolation, it is short. No table rewrite.

### 6.4 Compatibility assessment

Fully additive and invisible to old code. `checkpoint_version=1` is assigned to
existing rows; no current code reads it. `spec_fingerprint` and `store_path` stay
NULL. No API schema change. No worker mirror change is required for P1.

### 6.5 Failure scenarios

- Lock wait or timeout: same as 0032.
- Duplicate column if applied outside Alembic: migration fails; audit and
  re-run.
- Disk full: unlikely; rollback.

### 6.6 Recovery procedure

Transaction rollback is sufficient. If applied separately and a column exists
but the revision did not stamp, inspect `information_schema.columns`; do not drop
unless confirmed P1-only.

### 6.7 Required pre-production tests

- Upgrade/downgrade on a copy.
- Verify defaults and nullability.
- Verify old API/worker smoke.
- Confirm no reads of the new columns.

### 6.8 Go/no-go

**GO with controls**, provided 0032's transaction/lock strategy is resolved and
the same `lock_timeout`/window applies.

## 7. Migration 0034 — dispatch outbox

### 7.1 Exact objects affected

New table `job_dispatch_outbox`:

- `id bigserial` PK
- `job_id integer NOT NULL`
- `task_name varchar(80) NOT NULL DEFAULT 'logvault.run_job'`
- `payload json NOT NULL DEFAULT '{}'`
- `status varchar(16) NOT NULL DEFAULT 'pending'`
- `attempts integer NOT NULL DEFAULT 0`
- `next_attempt_at timestamptz NOT NULL DEFAULT now()`
- `locked_by varchar(128) NULL`
- `locked_until timestamptz NULL`
- `last_error text NULL`
- `created_at timestamptz NOT NULL DEFAULT now()`
- `published_at timestamptz NULL`

Constraints/indexes:

- `UNIQUE (job_id, task_name)`
- `ix_job_dispatch_due (status, next_attempt_at)`
- `ix_job_dispatch_locked (locked_until) WHERE locked_until IS NOT NULL`

No foreign key. No CHECK constraints in P1. **No rows are inserted.**

### 7.2 Risk classification

**LOW.** New empty table and indexes; no existing table is altered.

### 7.3 Locking implications

`CREATE TABLE` and its indexes affect only the new table. Existing traffic is
unaffected. The table is invisible to other sessions until commit.

### 7.4 Compatibility assessment

No behavior change. No code reads or writes the table in P1. Old API/worker
unaffected. No API schema change. `json` (not JSONB) keeps SQLite tests
portable.

### 7.5 Failure scenarios

- Table/sequence/index name conflict: migration fails; audit and re-run.
- Disk full: rollback.
- Accidental backfill by a later phase before P6: outbox rows exist but no
  dispatcher; this is a P6 sequencing rule, not a P1 failure.
- If a foreign key were added later, job deletion could fail; P1's no-FK choice
  avoids that.

### 7.6 Recovery procedure

Transaction rollback removes the table and sequence. If applied separately,
`DROP TABLE` is safe only while no rows exist and no code reads it. Confirm the
revision stamp before dropping.

### 7.7 Required pre-production tests

- Create/drop on a copy.
- Verify unique constraint and index definitions.
- Verify 0 rows after migration.
- Verify old and new code paths neither read nor write it.

### 7.8 Go/no-go

**GO.** Low risk, provided no P1 code inserts rows and no dispatcher is enabled.

## 8. Migration 0035 — schedule windows

### 8.1 Exact objects affected

New table `schedule_windows`:

- `id bigserial` PK
- `schedule_id integer NOT NULL`
- `window_key varchar(80) NOT NULL`
- `scheduled_for timestamptz NOT NULL`
- `start_epoch bigint NOT NULL`
- `end_epoch bigint NOT NULL`
- `status varchar(16) NOT NULL DEFAULT 'pending'`
- `completion_state varchar(16) NOT NULL DEFAULT 'unknown'`
- `attempts integer NOT NULL DEFAULT 0`
- `max_attempts integer NOT NULL DEFAULT 3`
- `current_job_id integer NULL`
- `next_attempt_at timestamptz NULL`
- `last_error text NULL`
- `config_snapshot json NULL`
- `created_at timestamptz NOT NULL DEFAULT now()`
- `updated_at timestamptz NOT NULL DEFAULT now()`

On `jobs`:

- `schedule_window_id integer NULL`
- `attempt_no integer NOT NULL DEFAULT 1`

Constraints/indexes:

- `UNIQUE (schedule_id, window_key)`
- `ix_schedule_windows_due (status, scheduled_for)`
- `ix_schedule_windows_schedule (schedule_id, scheduled_for)`
- `ix_jobs_schedule_window_id (schedule_window_id)`
- `uq_jobs_schedule_attempt (schedule_window_id, attempt_no) WHERE schedule_window_id IS NOT NULL`
- `uq_jobs_schedule_active (schedule_window_id) WHERE schedule_window_id IS NOT NULL AND status IN ('queued','running','paused')`

No foreign keys. No CHECK constraints in P1. **No rows are inserted.**

### 8.2 Risk classification

**MEDIUM.** Adds a new table plus two columns, three indexes on `jobs` (one
full, two partial unique), and two indexes on the new table. The unique indexes
are safe while `schedule_window_id` is NULL, but `ix_jobs_schedule_window_id` is
a full index over an all-NULL column and should be partial.

### 8.3 Locking implications

- New table/indexes: new-table locks only.
- `jobs.schedule_window_id` and `jobs.attempt_no`: `ACCESS EXCLUSIVE` on `jobs`,
  held until transaction end under the current model.
- The two unique indexes scan `jobs`; all existing rows are NULL and excluded by
  the partial predicates, so no duplicate failure is expected. The full
  `ix_jobs_schedule_window_id` indexes every NULL row and should be avoided.
- Unique index creation can fail if P2+ writes duplicates before the index is
  valid; P1 creates it while the column is still unwritten, so that risk is
  deferred.

### 8.4 Compatibility assessment

Invisible to old API/worker. `attempt_no=1` on existing rows; `schedule_window_id`
NULL. No scheduler uses the table in P1. Reports/rollups do not read it. No API
change.

Latent effects: the unique indexes will constrain future writers; that is
intended but must not be enabled before P7 behavior is ready.

### 8.5 Failure scenarios

- Unique index build fails on unexpected non-null duplicates: audit; do not
  force.
- Lock wait/timeout on `jobs`: same as 0032.
- Name conflict on table/index: migration fails; audit.
- D11 reduced scope: if `0035` is omitted, `0036` must revise `0034`, or `0035`
  must still exist as an empty revision. The migration graph must be fixed
  before authorization.
- Seeding ledger rows in P1 would be a behavior change and is forbidden.

### 8.6 Recovery procedure

If the transaction rolls back, nothing remains. If applied separately and the
table is empty, dropping it is safe. If rows exist, do not drop without a P7
decision. If a unique index is invalid from a concurrent attempt, drop and
recreate.

### 8.7 Required pre-production tests

- Create/drop on a copy.
- Verify both unique indexes and the active-window predicate.
- Verify all existing `jobs` rows remain `schedule_window_id=NULL`.
- Verify 0 rows in `schedule_windows`.
- Simulate a duplicate `(schedule_id, window_key)` insert and confirm rejection.
- Verify no scheduler/report/rollup behavior change.

### 8.8 Go/no-go

**CONDITIONAL GO.** Requires D11 scope confirmation, a partial
`ix_jobs_schedule_window_id`, and the same transaction/lock controls as 0032.
If D11 reduced scope is chosen, adjust the revision graph rather than leaving a
broken chain.

## 9. Migration 0036 — S3 attempt publication

### 9.1 Exact objects affected

On `jobs`:

- `s3_attempt_token bigint NOT NULL DEFAULT 0`
- `s3_uploading_at timestamptz NULL`
- `s3_published_attempt bigint NULL`
- `s3_manifest_uri text NULL`

Index:

- `ix_jobs_s3_uploading (s3_uploading_at) WHERE s3_uploading_at IS NOT NULL`

No constraints in P1.

### 9.2 Risk classification

**LOW.** Four metadata-only columns and one partial index. No S3 behavior is
enabled.

### 9.3 Locking implications

`ADD COLUMN` takes `ACCESS EXCLUSIVE` on `jobs`; the partial index takes
`SHARE`. Under the single transaction, the lock is held until bundle commit.
Otherwise short. No table rewrite.

### 9.4 Compatibility assessment

Old code ignores the columns. `s3_attempt_token=0` and
`s3_published_attempt=NULL` on existing rows. No S3 upload path reads them in
P1. No API response change.

### 9.5 Failure scenarios

- Lock wait/timeout: same as 0032.
- Index name conflict: migration fails.
- Accidental P1 S3 publication would be a behavior change and is forbidden.
- A future `s3_published_attempt <= s3_attempt_token` CHECK is deferred to 0037.

### 9.6 Recovery procedure

Transaction rollback is sufficient. If applied separately, dropping the columns
is safe only while no S3 attempt state has been written. Never drop after P8
starts.

### 9.7 Required pre-production tests

- Upgrade/downgrade on a copy.
- Verify defaults, index partial predicate, and 0 non-null attempt tokens.
- Verify old worker S3 path still reads legacy `s3_uri` columns.
- Confirm no S3 upload is triggered.

### 9.8 Go/no-go

**GO with controls**, once the overall lock/transaction strategy is resolved.

## 10. Migration ordering, partial failure, and recovery

### 10.1 Ordering

Proposed linear chain:

`0031 -> 0032 -> 0033 -> 0034 -> 0035 -> 0036`

Rules:

- Apply in order; do not skip a revision in the middle.
- If D11 reduced scope omits `0035`, either:
  - keep `0035` as an empty revision, or
  - change `0036.down_revision` to `0034`.
  Do not leave `0036` pointing at a revision that does not exist.
- Do not run `upgrade head` for P1 until the transaction strategy is approved.

### 10.2 Current single-transaction behavior

- Success: all six revisions commit atomically; `alembic_version=0036`.
- Failure: all DDL rolls back; `alembic_version=0031`.
- Container kill: connection closes; PostgreSQL rolls back.
- Lock timeout: migration fails; rollback; retry later.
- This is the safest schema-atomicity model, but the worst lock-duration model.

### 10.3 Split-revision behavior

If each revision is applied by a separate `alembic upgrade 0032`, `0033`, etc.:

- Each invocation has its own transaction.
- Completed revisions remain.
- Failure leaves `alembic_version` at the last successful revision.
- Recovery is "fix and continue", not "roll back everything".
- `0032` still holds `ACCESS EXCLUSIVE` across its own columns/indexes.

### 10.4 Concurrent-index behavior

- `CREATE INDEX CONCURRENTLY` requires an autocommit block or an external step.
- Failure can leave `pg_index.indisvalid=false`.
- `IF NOT EXISTS` can silently accept an invalid index; always validate.
- Recovery: `DROP INDEX CONCURRENTLY <name>;` then recreate, then verify
  `indisvalid`.
- Do not advance the Alembic revision until the index is valid.

### 10.5 Failure injection to rehearse

- Kill the migration container after 0032 columns but before indexes.
- Force a lock timeout with a long `SELECT`/transaction on `jobs`.
- Force disk exhaustion on a scratch copy.
- Force a duplicate insert into `schedule_windows` to see the unique error.
- Force an invalid concurrent index and recover it.
- Restore the pre-migration dump and run the old stack.

## 11. Backup, restore, and recovery requirements

Observed:

- Backup service runs `pg_dump -Fc` daily and on start; 14-day retention.
- Latest dump: `logvault-20261113-091535.dump`, 2.8 MB, `pg_restore --list`
  exits 0. It is more than 24 hours old at preflight.
- A zero-byte `logvault-20261104-134352.dump` exists; `pg_restore --list` exits
  1. Do not treat "a file exists" as a valid backup.
- Backups are on the same host disk as the database.
- No WAL archiving or PITR is configured (`archive_mode=off`,
  `archive_command=disabled`; `wal_level=replica`).
- `LAST9_ENCRYPTION_KEY` must match the dump or credentials restore as
  undecryptable.

Required before P1:

1. Take a **fresh** `pg_dump -Fc` immediately before the migration window.
2. Verify it with `pg_restore --list`; record size and checksum.
3. Restore it into a scratch database and run the old stack smoke test.
4. Copy the dump off-host or to independent storage.
5. Confirm the encryption key is available outside the backup.
6. Document the restore procedure and the data-loss window (up to the dump
   time; no PITR).
7. Do not rely on the zero-byte dump or the previous night's dump as the only
   recovery point.

## 12. Unresolved blockers

1. **Single-transaction lock amplification.** `env.py` runs `0032`–`0036` in one
   transaction; `ACCESS EXCLUSIVE` on `jobs` is held for the entire bundle.
   Resolve by per-revision execution, `transaction_per_migration=True`, or an
   approved maintenance-window procedure.
2. **Concurrent index incompatibility.** `CREATE INDEX CONCURRENTLY` cannot run
   under the current transaction. Decide between a maintenance window,
   `autocommit_block`, or an external concurrent-index step.
3. **Index definitions.** `ix_jobs_retry_of` and `ix_jobs_schedule_window_id`
   are full indexes over all-NULL columns. Make them partial
   (`WHERE ... IS NOT NULL`); review `ix_jobs_lease`/`ix_jobs_progress` for the
   same reason.
4. **No lock timeout.** `lock_timeout=0`; a waiting `ALTER TABLE` can queue all
   `jobs` traffic indefinitely. Set and test a bounded timeout.
5. **Production size/traffic unverified.** The observed 25 MB/829-job database
   is not proof of production duration or lock impact. Measure a production
   copy.
6. **Backup freshness/integrity/PITR.** Latest dump is more than 24 hours old, a
   zero-byte dump exists, backups are on the same disk, and there is no PITR.
   Produce and verify a fresh off-host dump.
7. **D11 graph decision.** If `0035` is omitted, `0036` must revise `0034`, or
   `0035` must remain as an empty revision.
8. **No measured lock window.** Expected duration in the observed environment is
   likely seconds; production duration is unknown. Do not authorize on an
   estimate.
9. **P1 model/mirror completeness.** If P1 adds model declarations, both
   `api/app/models.py` and `worker/app/db.py` must match the migrations; if P1
   does not add them, Alembic autogenerate drift is expected. Decide explicitly.
10. **Operational ownership.** No named migration owner, change window, or
    rollback rehearsal record exists yet.

## 13. Required pre-production test matrix

| ID | Test | Pass criteria |
|---|---|---|
| PF-01 | Restore production copy | Row counts, indexes, and revision match |
| PF-02 | Measure sizes/blockers | `jobs` rows, table/index size, no long transactions |
| PF-03 | Apply P1 with `lock_timeout` | Completes within approved window; no lock queue |
| PF-04 | Concurrent read/write load | API reads/writes and worker updates behave |
| PF-05 | Old API/worker smoke | No response/task change |
| PF-06 | Schema diff | Only the P1 objects; defaults/nullability exact |
| PF-07 | Index validity | `indisvalid=true` for every index |
| PF-08 | Downgrade/re-upgrade | Clean; no orphan objects |
| PF-09 | Kill-mid-migration | Clean rollback or documented resume |
| PF-10 | Lock-timeout injection | Bounded failure; no outage pileup |
| PF-11 | Backup restore | Restored DB serves old stack |
| PF-12 | No behavior change | No P2 flags, no new reads/writes, no API field change |

## 14. Final P1 authorization checklist

Do not authorize P1 until every item is checked and recorded.

### Architecture and scope

- [ ] D1/D2, D3, D8, D10, A1 approved for inert P1 shape.
- [ ] D11 decided; `0035` included or revision graph adjusted.
- [ ] D9 runtime limits and production Redis remain separately unapproved.
- [ ] P1 scope confirms no runtime reads/writes, no P2 behavior, no CHECKs.

### Migration execution

- [ ] Transaction strategy decided: single maintenance window, per-revision,
      or `transaction_per_migration`/`autocommit_block`.
- [ ] `CREATE INDEX CONCURRENTLY` strategy decided and tested.
- [ ] `lock_timeout` and `statement_timeout` set for the migration session.
- [ ] Partial-index changes approved (`retry_of`, `schedule_window_id`,
      optionally lease/progress).
- [ ] Exact revision graph is linear and `0036`'s `down_revision` is correct.
- [ ] Migration owner, window, and communication plan named.

### Evidence on a production copy

- [ ] PF-01 through PF-12 pass.
- [ ] Lock duration and total duration recorded.
- [ ] No long-running transactions or lock queue during the run.
- [ ] Old API/worker compatibility verified.
- [ ] Downgrade/re-upgrade and kill-mid-migration rehearsed.

### Backup and rollback

- [ ] Fresh `pg_dump -Fc` taken and verified with `pg_restore --list`.
- [ ] Restore tested into a scratch database.
- [ ] Dump copied off-host; checksum recorded.
- [ ] Encryption key available outside the backup.
- [ ] Data-loss window documented (no PITR).
- [ ] Rollback decision tree and owner documented.

### Production readiness

- [ ] Production size/row count/traffic confirmed, not inferred from the 25 MB
      sample.
- [ ] Monitoring covers locks, connections, API errors, worker stalls.
- [ ] No P2 feature flag is enabled.
- [ ] Explicit user authorization recorded.

## 15. Verdict by migration

Per-migration verdicts below assume the execution model is fixed. In the current
bundled `upgrade head`, `0033`-`0036` inherit `0032`'s lock risk.

| Migration | Risk | Go/no-go |
|---|---|---|
| `0032` ownership/completion | **HIGH as bundled; MEDIUM if split/controlled** | **NO-GO as specified** |
| `0033` artifact/checkpoint pointers | **LOW** | **GO with controls** |
| `0034` dispatch outbox | **LOW** | **GO** |
| `0035` schedule windows | **MEDIUM** | **CONDITIONAL GO** |
| `0036` S3 attempt publication | **LOW** | **GO with controls** |
| **P1 bundle via `upgrade head`** | **HIGH** | **NO-GO for live traffic** |

## 16. Stop condition

This report is the complete preflight output. No migration file was created or
modified, no migration was executed, and no application behavior changed.
**P1 remains unauthorized.** Await explicit authorization after the blockers in
section 12 and the checklist in section 14 are resolved.
