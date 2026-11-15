# Release 1 P1 Backup and Recovery Plan

Status: **plan only.** No backup, restore, migration, or configuration change was
made. P1 remains unauthorized.

Companion documents:

- [`RELEASE_1_P1_MIGRATION_EXECUTION_STRATEGY.md`](./RELEASE_1_P1_MIGRATION_EXECUTION_STRATEGY.md)
- [`RELEASE_1_P1_MIGRATION_SEQUENCE.md`](./RELEASE_1_P1_MIGRATION_SEQUENCE.md)
- [`RELEASE_1_P1_FINAL_GO_NO_GO.md`](./RELEASE_1_P1_FINAL_GO_NO_GO.md)

## 1. Current backup facts

| Fact | Observed |
|---|---|
| Backup method | `pg_dump -Fc` from a `postgres:16-alpine` sidecar |
| Schedule | On container start, then daily |
| Retention | 14 days |
| Location | Host bind mount, default `./backups`; same physical disk as the database |
| Latest dump | `logvault-20261113-091535.dump`, 2.8 MB |
| Latest dump integrity | `pg_restore --list` exits 0 |
| Bad dump present | `logvault-20261104-134352.dump` is 0 bytes; `pg_restore --list` exits 1 |
| WAL archiving | `archive_mode=off`, `archive_command=disabled`, `wal_level=replica` |
| PITR | Not configured |
| Encryption key | `LAST9_ENCRYPTION_KEY` must match the dump or credentials restore as undecryptable |
| Restore procedure | `RUNBOOK.md` documents `dropdb`/`createdb`/`pg_restore` |

An unverified dump is not a recovery mechanism. The 0-byte file proves that file
existence alone is insufficient.

## 2. RPO and RTO implications

### 2.1 Current RPO

With daily dumps and no WAL archiving:

- RPO is approximately the time since the last successful dump.
- At preflight, the latest dump was more than 24 hours old.
- A backup service failure can silently extend RPO while an old file remains.
- A restore loses all data written after the dump.

For P1, this is acceptable only if the business accepts that data-loss window.
P1 itself performs no DML, so a failed P1 migration should not need a restore.
The risk is an operator error or unexpected schema/data corruption during the
window.

### 2.2 Current RTO

RTO is unmeasured. It includes:

1. detect the failure;
2. stop API/worker;
3. drop/create the database;
4. `pg_restore`;
5. verify schema/data;
6. start API/worker;
7. validate health and traffic.

The observed dump is small, so restore is likely fast, but the production size
is unverified. Measure it on a copy.

### 2.3 If lower RPO is required

Enable WAL archiving and PITR before P1/P2, and test a point-in-time restore.
That is a production infrastructure decision, not a P1 schema change. Without it,
the only recovery point is the last verified dump.

## 3. Fresh backup requirements

Before the P1 window:

1. **Pause the backup sidecar** or confirm its current dump has completed. A
   `pg_dump` holds `ACCESS SHARE` on `jobs` for its duration and can block the
   P1 `ALTER TABLE`.
2. Take a fresh custom-format dump:

   ```bash
   pg_dump -Fc -f /backups/p1-preflight-<timestamp>.dump
   ```

3. Record:
   - file size;
   - SHA-256 checksum;
   - dump start/end time;
   - PostgreSQL version;
   - `alembic_version`;
   - row counts for `jobs`, `job_events`, `schedules`, `extraction_groups`.
4. Verify the archive:

   ```bash
   pg_restore --list /backups/p1-preflight-<timestamp>.dump
   ```

   A non-zero exit is a failed backup. Do not proceed.
5. Copy the dump off-host or to independent storage. A dump on the same disk as
   the database does not cover disk loss.
6. Confirm `LAST9_ENCRYPTION_KEY` is available outside the backup. Without it,
   restored credentials are undecryptable.

## 4. Isolated restore test

A dump is not valid until it has been restored.

### 4.1 Procedure

1. Create a scratch database on a separate Postgres instance or a disposable
   container. Do not restore over the production database.
2. Restore:

   ```bash
   pg_restore -U <user> -d <scratch> --no-owner <dump>
   ```

3. Verify:
   - `alembic_version` equals the expected revision (0031 before P1);
   - table counts match the pre-dump counts;
   - `jobs`, `job_events`, `schedules`, `extraction_groups` exist;
   - a sample of jobs and schedules is readable;
   - `LAST9_ENCRYPTION_KEY` decrypts a stored credential (read-only check);
   - the old API/worker image starts and passes smoke tests against the scratch
     database.
4. Measure restore duration and record it.
5. Drop the scratch database/container after the test.

### 4.2 Pass criteria

- `pg_restore` exits 0.
- No missing tables/indexes/sequences.
- Counts match.
- Old stack serves a health check and a read-only job list.
- Restore duration is recorded.

## 5. Migration-window backup sequence

| Step | Action | Stop if |
|---|---|---|
| 1 | Announce window; pause backup sidecar | Backup still running |
| 2 | Verify no long transactions on `jobs` | Any long transaction |
| 3 | Take fresh dump | `pg_dump` non-zero |
| 4 | `pg_restore --list` | Non-zero |
| 5 | Restore to scratch and smoke test | Restore/test fails |
| 6 | Copy dump off-host; record checksum | Copy fails |
| 7 | Apply P1 revisions one at a time | Any revision/index failure |
| 8 | Verify schema, indexes, API, worker | Any check fails |
| 9 | Resume backup sidecar | — |

The backup sidecar should remain paused until the migration window ends, because
a dump started during the window can contend with DDL.

## 6. Recovery strategy

### 6.1 Prefer forward-fix

For P1, **forward-fix is preferred** because P1 is additive and performs no data
changes.

Examples:

- A revision fails on `lock_timeout`: fix the blocker, retry the same revision.
- A concurrent index is invalid: drop and recreate it.
- A revision is partially applied: audit the catalog and complete or roll back
  only that revision.
- The app fails after migration: fix the deployment; the old app still works
  against the additive schema.

Forward-fix avoids losing data since the dump.

### 6.2 Downgrade

P1-only downgrade is safe while:

- no P2 behavior is active;
- no outbox/schedule rows exist;
- no S3 attempt state was written;
- no new code reads the columns/tables.

Downgrade order is reverse revision order, including index revisions before the
columns they reference.

After P2 starts, P1 downgrade is not standalone. Roll back P2 behavior first,
drain workers, and decide explicitly what to do with outbox/window state.

### 6.3 Database restore (last resort)

Use only if:

- the schema/data is corrupted in a way forward-fix cannot repair;
- a bad manual operation changed data;
- the migration cannot be made consistent.

Procedure:

1. Stop API and worker.
2. Preserve the failed database if possible (snapshot/volume copy).
3. Drop and recreate the database.
4. `pg_restore` the verified pre-migration dump.
5. Verify `alembic_version` and counts.
6. Start the old API/worker.
7. Re-run the approved migration sequence from the restored state.

Consequences:

- all data after the dump is lost;
- no PITR means the loss window is the dump age;
- the encryption key must match.

### 6.4 Decision tree

| Situation | Action |
|---|---|
| Transactional revision fails | Rollback; fix; retry |
| Lock timeout | Abort; find blocker; reschedule |
| Concurrent index invalid | Drop/recreate; validate |
| Version/object mismatch | Audit; repair; do not stamp blindly |
| App deploy fails after migration | Fix deploy; old app remains compatible |
| Data corruption or unrecoverable schema | Restore verified dump; accept RPO loss |

## 7. Recovery duration measurement

Measure on the production-sized copy:

1. time to stop services;
2. time to drop/create;
3. time for `pg_restore`;
4. time for verification queries;
5. time to start API/worker and pass `/ready` and `/health/ops`;
6. total RTO.

Record the result in the P1 evidence record. Do not claim an RTO from the 2.8 MB
test dump.

## 8. PITR assessment

Current state: **no PITR**.

| Option | RPO | Cost/complexity | Recommendation |
|---|---|---|---|
| Daily dump only | Up to 24 h (or longer if backup fails) | Low | Accept only with explicit business approval |
| Dump + WAL archiving/PITR | Minutes or seconds | Storage, config, restore testing | Required if RPO must be low |
| Replica + failover | Low for host loss | Infrastructure | Separate availability decision |

P1 does not require PITR to be safe if forward-fix works and the dump is fresh.
It does require the business to accept the dump-only RPO.

## 9. Backup checklist

- [ ] Fresh dump taken immediately before the window.
- [ ] `pg_restore --list` exits 0.
- [ ] SHA-256 recorded.
- [ ] Restore to scratch succeeds.
- [ ] Row counts and `alembic_version` match.
- [ ] Old API/worker smoke passes on the restored copy.
- [ ] Dump copied off-host.
- [ ] Encryption key available outside the backup.
- [ ] Restore duration measured.
- [ ] Backup sidecar paused during the window.
- [ ] RPO accepted or PITR enabled.
- [ ] Recovery decision tree and owner documented.

## 10. Stop condition

This is a plan only. No backup, restore, migration, or configuration change was
made. P1 remains unauthorized.
