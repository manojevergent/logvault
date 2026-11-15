# Release 1 P1 Operator Runbook

Status: **SUPERSEDED / HISTORICAL.** Use
[`RELEASE_1_P1_FINAL_OPERATOR_RUNBOOK.md`](./RELEASE_1_P1_FINAL_OPERATOR_RUNBOOK.md)
for the final P1 procedure. This file is retained for history only. P1 is not
authorized.

Verified current facts:

- Current Alembic revision in the observed database: `0031`.
- Project Alembic config: `api/alembic.ini`, `script_location = migrations`.
- Deployment entrypoint: `docker compose -f docker-compose.yml -f docker-compose.prod.yml`.
- `deploy.sh` currently runs `api alembic upgrade head`; this runbook deliberately
  does **not** use `upgrade head`.

Set the shell variables:

```bash
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
DB_USER="${POSTGRES_USER:-logvault}"
DB_NAME="${POSTGRES_DB:-logvault}"
PGO_META="-c lock_timeout=3s -c statement_timeout=60s -c idle_in_transaction_session_timeout=60s"
PGO_INDEX="-c lock_timeout=5s -c statement_timeout=900s -c idle_in_transaction_session_timeout=60s"
```

These are **initial test values**, not final production values. Replace them
with measured values from a production-sized copy.

## 1. Preconditions

| Check | Command | Pass |
|---|---|---|
| Current revision | `$COMPOSE run --rm --no-deps api alembic current` | `0031` |
| No unexpected changes | `git status --short` | Only approved P1 changes |
| P1 authorization | approval record | Explicit |
| D11 decision | approval record | `0035` included or graph adjusted |
| Backup | section 2 | Verified |
| Restore test | section 2 | Passed |
| Production copy measurement | section 4 | Recorded |
| Long transactions | `select ... from pg_stat_activity` | None on `jobs` |
| Lock conflicts | `pg_locks` | None |
| Disk headroom | `df -h` | Sufficient |
| Old stack health | `/ready`, `/health/ops` | Healthy |
| Change window | change record | Approved |
| Migration owner | roster | Named |

Stop if any check fails.

## 2. Backup and restore

### 2.1 Pause the backup sidecar

```bash
$COMPOSE stop backup
```

A `pg_dump` takes `ACCESS SHARE` on `jobs`; a dump running during DDL can block
the migration.

### 2.2 Fresh dump

```bash
STAMP=$(date +%Y%m%d-%H%M%S)
$COMPOSE exec -T postgres pg_dump -U "$DB_USER" -Fc -f "/tmp/p1-pre-$STAMP.dump" "$DB_NAME"
POSTGRES_ID=$(docker compose -f docker-compose.yml -f docker-compose.prod.yml ps -q postgres)
docker cp "$POSTGRES_ID:/tmp/p1-pre-$STAMP.dump" "./backups/p1-pre-$STAMP.dump"
```

Expected: non-zero file, exit 0.

### 2.3 Validate the dump

```bash
test -s "./backups/p1-pre-$STAMP.dump"
sha256sum "./backups/p1-pre-$STAMP.dump"
docker run --rm -v "$PWD/backups:/backups:ro" postgres:16-alpine \
  pg_restore --list "/backups/p1-pre-$STAMP.dump" > /dev/null
```

Expected: `pg_restore --list` exit 0.

### 2.4 Isolated restore test

Use a disposable database or container, never the production database:

```bash
$COMPOSE exec -T postgres dropdb -U "$DB_USER" --if-exists p1_restore_test
$COMPOSE exec -T postgres createdb -U "$DB_USER" p1_restore_test
$COMPOSE exec -T postgres pg_restore -U "$DB_USER" -d p1_restore_test --no-owner \
  "/tmp/p1-pre-$STAMP.dump"
$COMPOSE exec -T postgres psql -U "$DB_USER" -d p1_restore_test -c \
  "select version_num from alembic_version; select count(*) from jobs;"
```

Expected: version `0031`; row count matches the source snapshot.

Drop the scratch database after the test.

### 2.5 Off-host copy and key

```bash
cp "./backups/p1-pre-$STAMP.dump" /secure/offhost/
sha256sum /secure/offhost/"p1-pre-$STAMP.dump"
```

Confirm `LAST9_ENCRYPTION_KEY` is available outside the backup. Do not print the
key.

## 3. Apply revisions

### 3.1 0032 — ownership/completion columns

```bash
$COMPOSE run --rm --no-deps -e PGOPTIONS="$PGO_META" api alembic upgrade 0032
```

Expected:

- exit 0;
- `alembic current` = `0032`;
- 11 new `jobs` columns;
- no new indexes;
- API/worker healthy.

Verify:

```sql
select version_num from alembic_version;
select column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema='public' and table_name='jobs'
  and column_name in ('owner_id','lease_token','lease_expires_at','heartbeat_at',
                      'progress_at','pause_requested_at','cancel_requested_at',
                      'completion_state','gap_count','gap_reason','retry_of')
order by column_name;
```

### 3.2 0032b — lease/owner/progress indexes

```bash
$COMPOSE run --rm --no-deps -e PGOPTIONS="$PGO_INDEX" api alembic upgrade 0032b
```

Expected:

- exit 0;
- `alembic current` = `0032b`;
- `ix_jobs_lease`, `ix_jobs_owner`, `ix_jobs_progress` exist and are valid.

Verify:

```sql
select c.relname, i.indisvalid, i.indisready
from pg_index i
join pg_class c on c.oid = i.indexrelid
join pg_namespace n on n.oid = c.relnamespace
where n.nspname='public'
  and c.relname in ('ix_jobs_lease','ix_jobs_owner','ix_jobs_progress')
order by c.relname;

explain (analyze, buffers)
select 1 from jobs
where status='running' and lease_expires_at < now() - interval '1 minute';
```

Expected: `indisvalid=true`; planner can use the partial lease index.

### 3.3 0033 — artifact/checkpoint columns

```bash
$COMPOSE run --rm --no-deps -e PGOPTIONS="$PGO_META" api alembic upgrade 0033
```

Expected: `0033`; `store_path`, `spec_fingerprint`, `checkpoint_version` exist;
no indexes.

### 3.4 0034 — dispatch outbox

```bash
$COMPOSE run --rm --no-deps -e PGOPTIONS="$PGO_META" api alembic upgrade 0034
```

Expected: `0034`; `job_dispatch_outbox` exists; 0 rows; no dispatcher enabled.

Verify:

```sql
select to_regclass('public.job_dispatch_outbox');
select count(*) from job_dispatch_outbox;
```

### 3.5 0035 — schedule windows (only if D11 includes)

```bash
$COMPOSE run --rm --no-deps -e PGOPTIONS="$PGO_META" api alembic upgrade 0035
```

Expected: `0035`; `schedule_windows` exists; `jobs.schedule_window_id` and
`jobs.attempt_no` exist; 0 window rows; all `schedule_window_id` NULL; no jobs
indexes added by this revision.

Verify:

```sql
select count(*) from schedule_windows;
select count(*) from jobs where schedule_window_id is not null;
select column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema='public' and table_name='jobs'
  and column_name in ('schedule_window_id','attempt_no');
```

### 3.6 0035b — schedule indexes (optional)

Only if the P1 contract requires the unique guards now. Otherwise defer to P7.

```bash
$COMPOSE run --rm --no-deps -e PGOPTIONS="$PGO_INDEX" api alembic upgrade 0035b
```

Expected: `uq_jobs_schedule_attempt` and `uq_jobs_schedule_active` valid.

### 3.7 0036 — S3 attempt columns

```bash
$COMPOSE run --rm --no-deps -e PGOPTIONS="$PGO_META" api alembic upgrade 0036
```

Expected: `0036`; four S3 columns; all `s3_attempt_token=0`; no S3 behavior.

Verify:

```sql
select count(*) from jobs where s3_attempt_token <> 0;
select column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema='public' and table_name='jobs'
  and column_name in ('s3_attempt_token','s3_uploading_at',
                      's3_published_attempt','s3_manifest_uri');
```

### 3.8 0036b — S3 index (optional, usually defer to P8)

```bash
$COMPOSE run --rm --no-deps -e PGOPTIONS="$PGO_INDEX" api alembic upgrade 0036b
```

Expected: `ix_jobs_s3_uploading` valid.

## 4. Verification after every revision

```bash
$COMPOSE run --rm --no-deps api alembic current
curl -fsS http://localhost:8000/ready
curl -fsS http://localhost:8000/health/ops
$COMPOSE logs --tail=50 worker
```

SQL:

```sql
select version_num from alembic_version;

select pid, state, wait_event_type, wait_event, left(query,80)
from pg_stat_activity
where datname = current_database() and state <> 'idle';

select pid, pg_blocking_pids(pid)
from pg_stat_activity
where datname = current_database();

select c.relname, i.indisvalid, i.indisready
from pg_index i
join pg_class c on c.oid = i.indexrelid
join pg_namespace n on n.oid = c.relnamespace
where n.nspname='public' and c.relname like 'ix_jobs_%'
order by c.relname;
```

Expected: expected revision; no long blocked sessions; all P1 indexes valid; API
and worker healthy.

## 5. Stop conditions

Stop immediately if:

- any revision exits non-zero;
- `alembic current` is not the expected revision;
- a P1 index is missing or `indisvalid=false`;
- a lock timeout or statement timeout occurs;
- a long transaction or blocked queue appears on `jobs`;
- API error rate or worker heartbeat degrades;
- disk/connection headroom is insufficient;
- a process starts reading the new columns/tables (P2 behavior leaked).

Do not continue to the next revision after a stop condition.

## 6. Recovery actions

| Failure | Action |
|---|---|
| 0032/0033/0036 column revision fails | Transaction rolled back; check `alembic current`; fix; retry same revision |
| 0032b index fails | Check `pg_index.indisvalid`; if invalid: `DROP INDEX CONCURRENTLY <name>;` then retry 0032b |
| Process killed during index build | Inspect index; drop invalid; retry 0032b |
| Lock timeout | Abort; find blocker with `pg_blocking_pids`; reschedule; retry |
| Statement timeout | Abort; measure; increase only with evidence; retry |
| Version/object mismatch | Audit catalog; do not `alembic stamp`; repair or restore |
| App unhealthy after migration | Old app remains compatible; fix deployment; do not roll back schema reflexively |
| Irrecoverable corruption | Stop API/worker; restore verified dump; accept RPO loss |

### 6.1 Invalid index recovery

```sql
select c.relname, i.indisvalid, i.indisready
from pg_index i
join pg_class c on c.oid = i.indexrelid
where c.relname = '<index>';

drop index concurrently if exists <index>;
```

Then re-run the same index revision and verify.

## 7. D11 reduced-scope path

If D11 selects REDUCED:

1. Do not create `0035`, `0036`, `0035b`, or `0036b`.
2. Apply `0032`, `0032b`, `0033`, `0034`.
3. Graph becomes `0031 -> 0032 -> 0032b -> 0033 -> 0034`.
4. Later add the ledger/S3 revision(s) after the current head.

If `0036` is present under REDUCED, stop; the scope is wrong.

## 8. Evidence to retain

- `alembic current` before and after each revision.
- Full command output for each revision.
- Revision start/end time.
- `PGOPTIONS` values used.
- Lock wait and blocked-session output.
- Index validity query output.
- API `/ready` and `/health/ops` output.
- Worker log excerpt.
- Dump size, SHA-256, `pg_restore --list` output, restore duration.
- Row counts before/after.
- Operator name and go/no-go per revision.

## 9. Stop condition

This runbook is a future procedure. No command was executed against production.
P1 remains unauthorized.
