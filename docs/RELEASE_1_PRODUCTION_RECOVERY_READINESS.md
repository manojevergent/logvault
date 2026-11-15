# Release 1 Production Recovery Readiness

Status: **not production-ready.** The isolated rehearsal validated the recovery
procedure, but no production backup, restore, RPO/RTO, or PITR evidence exists.
P1 remains unauthorized.

Gate B production execution requires the current approved
`RELEASE_1_P1_FINAL_OPERATOR_RUNBOOK.md`; the superseded
`RELEASE_1_P1_OPERATOR_RUNBOOK.md` is not valid for Gate B.

Related:

- [`RELEASE_1_P1_BACKUP_AND_RECOVERY_PLAN.md`](./RELEASE_1_P1_BACKUP_AND_RECOVERY_PLAN.md)
- [`RELEASE_1_P1_MIGRATION_REHEARSAL_REPORT.md`](./RELEASE_1_P1_MIGRATION_REHEARSAL_REPORT.md)
- [`RELEASE_1_FINAL_P1_AUTHORIZATION_CHECKLIST.md`](./RELEASE_1_FINAL_P1_AUTHORIZATION_CHECKLIST.md)

## 1. Current state

| Item | Observed | Status |
|---|---|---|
| Backup method | `pg_dump -Fc` sidecar | Exists |
| Backup schedule | On start, then daily | Exists |
| Retention | 14 days | Exists |
| Latest production dump | More than 24 hours old at preflight | **Not fresh** |
| Zero-byte dump | `logvault-20261104-134352.dump` | **Invalid** |
| `pg_restore --list` on latest | Exit 0 | Valid file |
| Off-host copy | Production backup is on same host disk | **Not off-host** |
| WAL archiving | `archive_mode=off`, `archive_command=disabled` | **No PITR** |
| RPO | Time since last successful dump | **Unapproved** |
| RTO | Unmeasured | **Unapproved** |
| Encryption key | `LAST9_ENCRYPTION_KEY` present | Must be stored independently |
| Isolated rehearsal | Dump/restore/checksum passed on 39 KB test DB | Procedure only |
| Production-sized restore | Not performed | **Missing** |

**Do not claim production recovery readiness from the isolated test.**

## 2. Evidence required

### 2.1 Fresh production backup

| Field | Requirement |
|---|---|
| ID | REC-01 |
| Method | `pg_dump -Fc` against production immediately before the P1 window |
| Pass | Exit 0; non-zero size; start/end time recorded |
| Artifact | Dump file, command output, timestamp |
| Owner | Migration operator |

### 2.2 Backup integrity

| Field | Requirement |
|---|---|
| ID | REC-02 |
| Method | `pg_restore --list <dump>` |
| Pass | Exit 0; TOC readable |
| Artifact | Command output |
| Additional | SHA-256 recorded |

A file that exists but fails `pg_restore --list` is not a backup.

### 2.3 Off-host copy

| Field | Requirement |
|---|---|
| ID | REC-03 |
| Method | Copy the dump to independent storage (not the database host/volume) |
| Pass | Copy exists; SHA-256 matches source |
| Artifact | Destination path, checksum comparison |
| Owner | Operations |

### 2.4 Isolated restore rehearsal

| Field | Requirement |
|---|---|
| ID | REC-04 |
| Method | Restore the fresh dump into a disposable database/container, not production |
| Pass | `pg_restore` exit 0; table counts match; `alembic_version` matches; old API/worker smoke passes |
| Artifact | Restore log, count queries, duration |
| Critical | Measure restore duration on the production-sized dump |

### 2.5 Encryption key availability

| Field | Requirement |
|---|---|
| ID | REC-05 |
| Method | Confirm `LAST9_ENCRYPTION_KEY` is available outside the backup and matches the dump era |
| Pass | Stored credential decrypts in the restored copy; key not stored only with the dump |
| Artifact | Non-secret confirmation; key custody record |

Never print or commit the key.

### 2.6 RPO approval

| Field | Requirement |
|---|---|
| ID | REC-06 |
| Method | Business decision on acceptable data-loss window |
| Current | Dump-only: up to dump age, and longer if backup fails |
| Pass | Explicit approval of dump-only RPO, or PITR enabled |
| Artifact | Approval record |
| Owner | Business/operations |

### 2.7 RTO approval

| Field | Requirement |
|---|---|
| ID | REC-07 |
| Method | Measure stop, restore, verify, and start time on a production-sized copy |
| Pass | Measured RTO is within the approved recovery objective |
| Artifact | Timed runbook and measurement |
| Owner | Operations |

### 2.8 PITR decision

| Field | Requirement |
|---|---|
| ID | REC-08 |
| Options | (a) accept dump-only RPO; (b) enable WAL archiving/PITR and test a point-in-time restore |
| Current | `archive_mode=off`, no PITR |
| Pass | Decision recorded; if PITR chosen, restore test passes |
| Artifact | Configuration decision and restore evidence |
| Owner | Business/operations |

### 2.9 Production migration rollback/recovery

| Field | Requirement |
|---|---|
| ID | REC-09 |
| Method | Rehearse forward-fix, P1 downgrade, and last-resort restore on a production-sized copy |
| Pass | Each path completes; owners and stop conditions known |
| Artifact | Rehearsal log |
| Note | P1 is schema-only; forward-fix is preferred. Restore is last resort. |

## 3. Recovery strategy

### 3.1 Forward-fix (preferred)

Use when:

- a revision fails transactionally;
- a concurrent index is invalid;
- a lock/statement timeout aborts the current revision;
- app deployment fails after migration.

P1 performs no data changes, so forward-fix avoids the dump-age data loss.

### 3.2 P1 downgrade

Safe only while:

- no P2 behavior is active;
- outbox/window tables are empty or deliberately handled;
- no S3 attempt state was written;
- no new code reads the columns/tables.

Downgrade index revisions first, then columns/tables in reverse order.

### 3.3 Database restore (last resort)

Use only for:

- unrecoverable schema/data corruption;
- a bad manual operation;
- an inconsistent catalog that forward-fix cannot repair.

Procedure:

1. Stop API/worker.
2. Preserve the failed database if possible.
3. Drop/create the database.
4. Restore the verified fresh dump.
5. Verify `alembic_version`, counts, and key tables.
6. Start the old API/worker.
7. Re-run the approved sequence.

Consequence: data after the dump is lost; no PITR.

## 4. RPO/RTO implications

| Scenario | RPO | RTO |
|---|---|---|
| Transactional revision failure | None (rollback) | Minutes |
| Invalid concurrent index | None (no data) | Minutes |
| App deploy failure after migration | None (old app compatible) | Deployment time |
| Bad manual schema/data change | Since last dump | Restore + verification |
| Disk/host loss | Since last off-host dump | Restore + rebuild |

The current production RPO is **unapproved** and the RTO is **unmeasured**.

## 5. Recovery evidence record

| Field | Value |
|---|---|
| Dump ID/name | |
| Dump time | |
| Size | |
| SHA-256 | |
| `pg_restore --list` | pass/fail |
| Off-host destination | |
| Off-host checksum | |
| Restore target | |
| Restore start/end | |
| Restore duration | |
| Table count check | |
| `alembic_version` | |
| Old stack smoke | |
| Key availability | |
| RPO approved | |
| RTO approved | |
| PITR decision | |
| Rollback rehearsal | |
| Operator | |

## 6. Readiness verdict

**Production recovery is NOT READY.**

Reasons:

1. No fresh production dump at preflight.
2. A zero-byte dump exists.
3. Backups are not off-host.
4. No PITR.
5. Production restore duration is unmeasured.
6. RPO/RTO are unapproved.
7. Production-sized rollback/recovery rehearsal is not done.

The isolated rehearsal proves the **procedure**, not production recovery.

## 7. Stop condition

This is a readiness assessment. Do not take a production backup, restore,
migration, or configuration action until P1 is authorized and the evidence above
is produced.
