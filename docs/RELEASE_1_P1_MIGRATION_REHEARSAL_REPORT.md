# Release 1 P1 Migration Execution Rehearsal Report

Status: **evidence report only.** No application source, migration, `env.py`,
`deploy.sh`, schema, API, frontend, dependency, or production configuration was
changed. No P1 or P2 implementation was started. P1 remains unauthorized.

Test environment: isolated PostgreSQL 16.14 container, API image runtime
(Python 3.12.16, Alembic 1.14.0, SQLAlchemy 2.0.36, psycopg 3.2.3), synthetic
test revisions under `p1_rehearsal/`. The synthetic revisions are **not** Release
1 migrations and are not imported by the application.

Evidence:

- `p1_rehearsal/results/rehearsal_results.json` — 11 tests, 11 passed.
- `p1_rehearsal/run_rehearsal.py` — harness.
- `p1_rehearsal/env.py` — test copy of `api/migrations/env.py`; only difference
  is the `REHEARSAL_TPM` switch and transaction-state logging.
- `p1_rehearsal/versions/*.py` — synthetic revisions.
- `p1_rehearsal/actual_run/` — unmodified copy of `api/migrations/env.py` used
  for the baseline test.

## 1. Alembic verification

### 1.1 Installed behavior

Verified against Alembic **1.14.0** and a copy of the current
`api/migrations/env.py`:

| Observation | Result |
|---|---|
| `transaction_per_migration` default | `False` |
| Outer `context.begin_transaction()` with default | Active; `connection.in_transaction()=True` inside the wrapper |
| All revisions in one outer transaction | Confirmed: failure in revision 2 rolled back revision 1 |
| `transaction_per_migration=True` | Per-revision transactions; revision 1 committed when revision 2 failed |
| Outer wrapper with `transaction_per_migration=True` | Becomes a no-op; `connection.in_transaction()=False` inside the wrapper |
| Revision version stamp | Committed with the revision transaction |
| `autocommit_block` with `transaction_per_migration=False` | **Commits all preceding revisions** before the block |
| `autocommit_block` with `transaction_per_migration=True` | Commits only the current revision's preceding work, then runs the non-transactional statement |

### 1.2 Actual `env.py` baseline

The unmodified `api/migrations/env.py` was copied to `actual_run/` and run
against the synthetic revisions. Injecting a failure in revision 2 produced:

- `rehearsal_jobs` absent
- `alembic_version` absent
- no log rows

This independently confirms that the current project configuration rolls back
revision 1 when revision 2 fails.

### 1.3 Transaction-boundary proof

With test revisions 0001–0004:

| Mode | Observed txids | Meaning |
|---|---|---|
| `transaction_per_migration=True` | `1054, 1055, 1056, 1060` | Four distinct transactions |
| `transaction_per_migration=False` | `1074, 1074, 1074, 1078` | 0001–0003 share one transaction; 0004 gets a new one because of its `autocommit_block` |

**Finding:** an autocommit block in a later revision commits all preceding
revisions even without `transaction_per_migration`. This is why the proposed
strategy must enable `transaction_per_migration=True` **before** any concurrent
index revision. Otherwise a concurrent index revision silently changes the
atomicity of the preceding schema work.

## 2. Test results

| ID | Test | Expected | Actual | Result |
|---|---|---|---|---|
| T1 | `tpm=false`, 0002 fails | 0001 rolls back | table absent, version absent, log empty, `inside_outer in_tx=True` | **PASS** |
| T2 | `tpm=true`, 0002 fails | 0001 stays committed | table present, version `0001`, log `0001`, txid 1004 | **PASS** |
| T3 | Separate invocations, 0001 then failing 0002 | 0001 committed | version `0001`, log `0001` | **PASS** |
| T4 | Failure during column revision 0003 | Only 0003 rolls back | version `0002`, no columns, log `0001,0002` | **PASS** |
| T5 | Concurrent index revision succeeds | Valid index, version `0004` | `indisvalid=true`, version `0004` | **PASS** |
| T6 | Failure after concurrent index block | Index survives; revision not stamped; retry stamps | index valid, version `0003`; retry version `0004` | **PASS** |
| T7 | Unique concurrent index over duplicates | Invalid index left; drop/rebuild works | `indisvalid=false`; after cleanup retry valid, version `0005` | **PASS** |
| T8 | Process termination during concurrent index | No valid index; version unchanged | killed process; `indisvalid=false`, version `0002` | **PASS** |
| T9 | Lock acquisition timeout | Abort current revision; previous committed; retry works | lock timeout; version `0002`; retry version `0007` | **PASS** |
| T10 | Statement timeout | Abort current revision; previous committed; retry works | statement timeout; version `0002`; retry version `0008` | **PASS** |
| T11 | Transaction boundaries | Four txids with TPM; shared txid without TPM until autocommit | 4 txids vs 3+1 txids | **PASS** |

**Summary: 11 executed, 11 passed, 0 failed.**

### 2.1 Failure-injection mapping to P1

| Synthetic test | P1 equivalent |
|---|---|
| T1/T2/T3 | 0032 failure; committed prior revision |
| T4 | 0032 columns failure |
| T5/T6 | 0032b concurrent index success/failure |
| T7 | Invalid unique index left behind and retry |
| T8 | Process termination during 0032b |
| T9 | Lock acquisition timeout on 0032/0035 |
| T10 | Statement timeout |
| T11 | Transaction boundaries and autocommit interaction |

## 3. Backup and restore verification

Performed against the isolated PostgreSQL container.

| Check | Result |
|---|---|
| Fresh dump | `pg_dump -Fc` completed |
| Dump duration | 0.517 s |
| Dump size | 39,170 bytes (non-zero) |
| Dump SHA-256 | `28143be4a76094817fe4b5b5dcc6ccbf9777f589ce4ff4006261a95ececede0d` |
| `pg_restore --list` | exit 0 |
| Off-host copy | copied to temp path outside the container/database volume |
| Off-host SHA-256 | `28143BE4A76094817FE4B5B5DCC6CCBF9777F589CE4FF4006261A95ECECEDE0D` (matches) |
| Isolated restore | restored to `p1_restore` |
| Restore duration | 0.363 s |
| Restored rows | 10,000 of 10,000 |
| Encryption key | `LAST9_ENCRYPTION_KEY` present and non-empty in `.env` (value not recorded) |

These numbers validate the **procedure** on a small test database, not production
RTO/RPO.

### 3.1 Remaining recovery limitations

- Production latest dump was more than 24 hours old at preflight.
- A zero-byte dump exists; file existence is not integrity.
- Production backups are on the same disk as the database.
- `archive_mode=off`; no WAL/PITR. RPO is dump-age.
- Production dump size/restore duration are unmeasured.
- The encryption key is present in `.env`; it must be stored independently of
  the backup.

## 4. Production compatibility

The P1 schema changes remain invisible to the currently deployed processes if the
P1 boundary is respected:

- API `JobOut` and response schemas are unchanged.
- No API router reads the new columns/tables.
- Worker Core tables use explicit columns; old workers receive DB defaults.
- Scheduler/beat does not read `schedule_windows` or the new columns.
- Background reaper/cleanup/S3 paths do not read the new state.
- New tables are empty and unwritten.
- Unique indexes are safe while new key columns are NULL.
- Planner changes from new indexes must be monitored but do not change
  correctness.

No process may start depending on the new fields/tables during P1. No P2 flag or
behavior may be enabled.

## 5. Operator runbook

The exact future operator procedure is in
[`RELEASE_1_P1_OPERATOR_RUNBOOK.md`](./RELEASE_1_P1_OPERATOR_RUNBOOK.md).

It uses the actual project entrypoint shape
(`docker compose ... run --rm --no-deps api alembic ...`), the actual current
revision `0031`, and the proposed revision IDs `0032`, `0032b`, `0033`, `0034`,
`0035`, optional `0035b`, `0036`, optional `0036b`.

The P1 migration files do not exist yet, so the runbook is a future procedure,
not an executable current command sequence.

## 6. Final decision

**READY WITH CONDITIONS.**

The transaction-per-revision and autocommit mechanisms are technically validated.
The migration strategy is safe only after the conditions below are met.

### 6.1 Per-migration verdicts

| Revision | Verdict | Condition |
|---|---|---|
| `0032` | READY WITH CONDITIONS | Columns only; no indexes; `lock_timeout`; production-sized measurement |
| `0032b` | READY WITH CONDITIONS | `transaction_per_migration=True` before autocommit; concurrent indexes; invalid-index recovery |
| `0033` | READY | Column-only revision; standard guards |
| `0034` | READY | New empty table; no P1 writers |
| `0035` | READY WITH CONDITIONS | D11 includes ledger; columns only; no jobs indexes |
| `0035b` | DEFER / READY WITH CONDITIONS | Optional; P7 is the natural home |
| `0036` | READY | Column-only revision |
| `0036b` | DEFER | P8 is the natural home |

### 6.2 Consolidated P1 verdict

**READY WITH CONDITIONS for the redesigned P1.**
**NO-GO for the original one-shot `upgrade head` bundle.**

### 6.3 Remaining blockers and evidence needed

| Blocker | Evidence needed |
|---|---|
| `transaction_per_migration=True` not yet implemented | Approved env.py change + T1/T2 rehearsal on staging |
| Revision split not yet implemented | 0032 columns only; 0032b separate index revision |
| `autocommit_block` without TPM commits prior revisions | TPM enabled before any autocommit revision; regression test |
| Concurrent index retry procedure not in production runbook | Runbook approved; invalid-index drill |
| Index deferrals not approved | Approve partial lease/progress/owner; defer retry/window/S3 |
| D11 scope unresolved | Include 0035 or set 0036.down_revision=0034 |
| Production-sized measurement absent | Lock wait/duration/index validity on a production copy |
| Backup freshness/integrity/PITR | Fresh verified dump, restore test, off-host copy, key, RPO decision |
| Final timeout values unset | Measured `lock_timeout`/`statement_timeout` |
| P1 authorization absent | Explicit user authorization |

## 7. Evidence retained

- `p1_rehearsal/results/rehearsal_results.json`
- Test harness and synthetic revisions under `p1_rehearsal/`
- Actual `env.py` baseline in `p1_rehearsal/actual_run/`
- Isolated dump copy at
  `C:\Users\Manoj\AppData\Local\Temp\1\opencode\p1_backup_evidence\p1_backup.dump`
  with SHA-256 recorded above.

## 8. Stop condition

This is the complete rehearsal evidence report. No application source,
migration, `env.py`, `deploy.sh`, schema, API, frontend, dependency, or
production configuration was changed. No production database operation was
performed. **P1 remains unauthorized.**
