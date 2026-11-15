# Release 1 P1 Final Operator Runbook

Status: **future procedure only.** P1 is not authorized. The P1 migration files
`0032`, `0032b`, `0033`, `0034`, `0035`, `0036` do not exist yet. These commands
become executable only after explicit P1 authorization and after the revisions
are created and reviewed.

This runbook supersedes the earlier `RELEASE_1_P1_OPERATOR_RUNBOOK.md` for the
authorization phase.

Verified current facts:

- Current revision in the observed database: `0031`.
- Alembic config: `api/alembic.ini`, `script_location = migrations`.
- Deployment compose: `docker-compose.yml` + `docker-compose.prod.yml`.
- `deploy.sh` currently runs `api alembic upgrade head`; this runbook does not.

## 1. Shell setup

```bash
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
DB_USER="${POSTGRES_USER:-logvault}"
DB_NAME="${POSTGRES_DB:-logvault}"
PGO_META="-c lock_timeout=3s -c statement_timeout=60s -c idle_in_transaction_session_timeout=60s"
PGO_INDEX="-c lock_timeout=5s -c statement_timeout=900s -c idle_in_transaction_session_timeout=60s"
```

These are **initial test values**, not final production values. Replace them
with measured values from a production-sized copy before the window.

## 2. Preconditions

| Check | Command | Pass |
|---|---|---|
| Revision | `$COMPOSE run --rm --no-deps api alembic current` | `0031` |
| TPM implemented | image built from approved commit | `transaction_per_migration=True` present |
| P1 authorization | authorization record | Explicit |
| D11 decision | approval record | Full ledger; `0035` included |
| Graph | `alembic history` / reviewed files | `0031 -> 0032 -> 0032b -> 0033 -> 0034 -> 0035 -> 0036` |
| Backup | section 3 | Verified |
| Restore rehearsal | section 3 | Passed |
| Production copy measurement | section 5 | Recorded |
| Long transactions | `pg_stat_activity` | None on `jobs` |
| Lock conflicts | `pg_locks` | None |
| Disk/connection headroom | `df`, `pg_stat_activity` | Sufficient |
| Old stack health | `/ready`, `/health/ops` | Healthy |
| Window/owner | change record | Approved/named |

Stop if any check fails.

## 3. Backup and restore

### 3.1 Pause backup sidecar

```bash
$COMPOSE stop backup
```

### 3.2 Fresh dump and off-host copy

```bash
STAMP=$(date +%Y%m%d-%H%M%S)
$COMPOSE exec -T postgres pg_dump -U "$DB_USER" -Fc -f "/tmp/p1-pre-$STAMP.dump" "$DB_NAME"
POSTGRES_ID=$(docker compose -f docker-compose.yml -f docker-compose.prod.yml ps -q postgres)
docker cp "$POSTGRES_ID:/tmp/p1-pre-$STAMP.dump" "./backups/p1-pre-$STAMP.dump"
test -s "./backups/p1-pre-$STAMP.dump"
sha256sum "./backups/p1-pre-$STAMP.dump"
cp "./backups/p1-pre-$STAMP.dump" /secure/offhost/
sha256sum /secure/offhost/"p1-pre-$STAMP.dump"
```

Expected: non-zero file; checksums match.

### 3.3 Verify archive

```bash
docker run --rm -v "$PWD/backups:/backups:ro" postgres:16-alpine \
  pg_restore --list "/backups/p1-pre-$STAMP.dump" > /dev/null
```

Expected: exit 0.

### 3.4 Isolated restore rehearsal

Use a disposable DB/container, never production:

```bash
$COMPOSE exec -T postgres dropdb -U "$DB_USER" --if-exists p1_restore_test
$COMPOSE exec -T postgres createdb -U "$DB_USER" p1_restore_test
$COMPOSE exec -T postgres pg_restore -U "$DB_USER" -d p1_restore_test --no-owner \
  "/tmp/p1-pre-$STAMP.dump"
$COMPOSE exec -T postgres psql -U "$DB_USER" -d p1_restore_test -c \
  "select version_num from alembic_version; select count(*) from jobs;"
```

Expected: version `0031`; row count matches. Measure restore duration. Drop the
scratch DB.

### 3.5 Key

Confirm `LAST9_ENCRYPTION_KEY` is available outside the backup and matches the
dump era. Do not print the key.

## 4. Apply revisions

### 4.1 0032 — ownership/completion columns

```bash
$COMPOSE run --rm --no-deps -e PGOPTIONS="$PGO_META" api alembic upgrade 0032
```

Expected: `0032`; 11 columns; no indexes; API/worker healthy.

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

Stop if any column is missing or an index was added.

### 4.2 0032b — concurrent lease/owner/progress indexes

```bash
$COMPOSE run --rm --no-deps -e PGOPTIONS="$PGO_INDEX" api alembic upgrade 0032b
```

Expected: `0032b`; three valid indexes:

- `ix_jobs_lease (status, lease_expires_at) WHERE lease_expires_at IS NOT NULL`
- `ix_jobs_owner (owner_id) WHERE owner_id IS NOT NULL`
- `ix_jobs_progress (status, progress_at) WHERE progress_at IS NOT NULL`

Verify:

```sql
select c.relname, i.indisvalid, i.indisready
from pg_index i
join pg_class c on c.oid = i.indexrelid
join pg_namespace n on n.oid = c.relnamespace
where n.nspname='public'
  and c.relname in ('ix_jobs_lease','ix_jobs_owner','ix_jobs_progress')
order by c.relname;
```

Expected: all `indisvalid=true`.

If an index is invalid:

```sql
drop index concurrently if exists <invalid_index>;
```

Retry `0032b`. Do not continue with an invalid index.

### 4.3 0033 — artifact/checkpoint columns

```bash
$COMPOSE run --rm --no-deps -e PGOPTIONS="$PGO_META" api alembic upgrade 0033
```

Expected: `0033`; `store_path`, `spec_fingerprint`, `checkpoint_version`; no
indexes.

### 4.4 0034 — dispatch outbox

```bash
$COMPOSE run --rm --no-deps -e PGOPTIONS="$PGO_META" api alembic upgrade 0034
```

Expected: `0034`; `job_dispatch_outbox`; 0 rows; no dispatcher.

Verify:

```sql
select to_regclass('public.job_dispatch_outbox');
select count(*) from job_dispatch_outbox;
```

### 4.5 0035 — schedule windows

```bash
$COMPOSE run --rm --no-deps -e PGOPTIONS="$PGO_META" api alembic upgrade 0035
```

Expected: `0035`; `schedule_windows`; `jobs.schedule_window_id`;
`jobs.attempt_no`; 0 window rows; all `schedule_window_id` NULL; no jobs
indexes.

Verify:

```sql
select count(*) from schedule_windows;
select count(*) from jobs where schedule_window_id is not null;
select column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema='public' and table_name='jobs'
  and column_name in ('schedule_window_id','attempt_no');
```

### 4.6 0036 — S3 attempt columns

```bash
$COMPOSE run --rm --no-deps -e PGOPTIONS="$PGO_META" api alembic upgrade 0036
```

Expected: `0036`; four S3 columns; `s3_attempt_token=0` on all rows; no S3
behavior.

Verify:

```sql
select count(*) from jobs where s3_attempt_token <> 0;
select column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema='public' and table_name='jobs'
  and column_name in ('s3_attempt_token','s3_uploading_at',
                      's3_published_attempt','s3_manifest_uri');
```

### 4.7 Deferred revisions

Do **not** run in P1:

- `0035b` — schedule unique indexes; P7.
- `0036b` — S3 index; P8.
- `ix_jobs_retry_of` — P2/P9.
- `ix_jobs_schedule_window_id` — P7.
- `ix_jobs_s3_uploading` — P8.

## 5. Production-sized measurement

Before the window, on a production-sized copy:

- measure each revision duration;
- measure lock wait and blocked sessions;
- measure index build duration;
- verify `indisvalid=true`;
- run API-like reads/writes and worker-like updates;
- record p99 API latency and worker heartbeat;
- choose final `lock_timeout` and `statement_timeout`;
- confirm the migration fits the approved window.

Do not use the 25 MB rehearsal database to set production values.

## 6. Verification after every revision

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

Expected: expected revision; no blocked queue; all P1 indexes valid; API/worker
healthy.

## 7. Stop conditions

Stop and do not continue if:

- any revision exits non-zero;
- `alembic current` is not expected;
- a P1 index is missing or `indisvalid=false`;
- lock or statement timeout occurs;
- a long transaction or blocked queue appears on `jobs`;
- API error rate or worker heartbeat degrades;
- disk/connection headroom is insufficient;
- any process reads the new columns/tables (P2 behavior leaked).

## 8. Recovery

| Failure | Action |
|---|---|
| Column/table revision fails | Rollback; check `alembic current`; fix; retry |
| Concurrent index fails | Check `indisvalid`; drop invalid; retry 0032b |
| Process killed during index | Drop invalid; retry 0032b |
| Lock timeout | Abort; find blocker with `pg_blocking_pids`; reschedule |
| Statement timeout | Abort; measure; increase only with evidence |
| Version/object mismatch | Audit; do not `alembic stamp`; repair or restore |
| App unhealthy | Old app compatible; fix deployment |
| Irrecoverable corruption | Restore verified dump; accept RPO loss |

## 9. Rollback

Before P2:

1. Downgrade `0032b` (drop indexes concurrently).
2. Downgrade `0036`, `0035`, `0034`, `0033`, `0032` in reverse order.
3. Verify old API/worker.

After P2: disable P2 behavior, drain workers, decide outbox/window state, roll
back P2 code, then P1.

## 10. D11 reduced-scope exception

If D11 selects REDUCED:
- exclude `0035` and `0036`;
- do not create `0035`, `0036`, or `0035b`;
- apply `0032`, `0032b`, `0033`, `0034`;
- graph becomes `0031 -> 0032 -> 0032b -> 0033 -> 0034`.

## 11. Evidence to retain

- `alembic current` before/after each revision.
- Full revision output.
- Start/end time and `PGOPTIONS`.
- Lock wait/blocked session output.
- Index validity output.
- API/worker health output.
- Dump size/SHA-256/`pg_restore --list`/restore duration.
- Row counts before/after.
- Operator and per-revision go/no-go.

## 12. Stop condition

This is a future procedure. No command was executed against production. P1
remains unauthorized.
