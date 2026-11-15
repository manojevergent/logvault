# Release 1 P1 Production Evidence Collection Plan

Status: **plan only.** No production measurement was taken. P1 is not authorized.
The isolated 25 MB rehearsal is not production evidence.

Use this plan to collect objective P1 evidence. Never invent or infer a
production measurement; leave placeholders unfilled until measured.

## 1. Evidence ownership

| Evidence | Owner | Required access |
|---|---|---|
| PostgreSQL version/config | DBA | Read-only production SQL |
| Database/table size, row counts | DBA | Read-only |
| Active transactions/locks | DBA | Read-only |
| Migration duration/lock waits | DBA + engineering | Production-sized copy or approved staging |
| Index inventory | DBA | Read-only |
| Disk capacity | Infrastructure | Host/container |
| Backup/off-host/checksum | DBA/operations | Backup storage |
| Restore/RTO | DBA/operations | Disposable restore environment |
| RPO/PITR | Business + infrastructure | Decision/approval |
| Change window/owner | Change management | Approval record |

## 2. Environment and capacity

Run on production read-only, or on the approved production-sized copy.

```sql
select version();
show server_version;
show server_version_num;
show max_connections;
show shared_buffers;
show work_mem;
show maintenance_work_mem;
show lock_timeout;
show statement_timeout;
show idle_in_transaction_session_timeout;
show default_transaction_isolation;
show archive_mode;
show wal_level;
show archive_command;
```

Database and table size:

```sql
select current_database(),
       pg_size_pretty(pg_database_size(current_database())) as db_size;

select relname,
       n_live_tup,
       n_dead_tup,
       pg_size_pretty(pg_relation_size(relid)) as heap,
       pg_size_pretty(pg_indexes_size(relid)) as indexes,
       pg_size_pretty(pg_total_relation_size(relid)) as total
from pg_stat_user_tables
where relname in ('jobs','job_events','schedules','extraction_groups')
order by relname;

select count(*) from jobs;
select status, count(*) from jobs group by status order by 2 desc;
```

Record TOAST separately:

```sql
select c.relname,
       pg_size_pretty(pg_total_relation_size(c.oid)
         - pg_relation_size(c.oid)
         - pg_indexes_size(c.oid)) as toast_and_other
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname='public' and c.relname='jobs';
```

Index inventory:

```sql
select tablename, indexname, indexdef
from pg_indexes
where schemaname='public'
  and tablename in ('jobs','job_events','schedules')
order by tablename, indexname;
```

Disk:

```bash
df -h /var/lib/postgresql/data   # container
df -h <host-data-path>           # host
```

## 3. Active transactions and locks

Baseline:

```sql
select state, count(*)
from pg_stat_activity
where datname = current_database()
group by state;

select pid, usename, state, wait_event_type, wait_event,
       now() - xact_start as xact_age,
       now() - query_start as query_age,
       left(query,120) as query
from pg_stat_activity
where datname = current_database()
  and state <> 'idle'
order by xact_start;

select pid, pg_blocking_pids(pid)
from pg_stat_activity
where datname = current_database()
  and cardinality(pg_blocking_pids(pid)) > 0;
```

During migration, sample every 1–5 seconds:

```sql
select now(),
       pid, state, wait_event_type, wait_event,
       now() - xact_start as xact_age,
       left(query,120) as query
from pg_stat_activity
where datname = current_database()
  and state <> 'idle'
order by xact_start;

select mode, granted, count(*)
from pg_locks
where relation = 'jobs'::regclass
group by mode, granted
order by mode, granted;
```

Record:

- `jobs` table lock mode and wait time;
- blocked sessions and blockers;
- whether reads or writes were blocked;
- API p99 latency and error rate during the run;
- worker heartbeat/beat freshness.

## 4. Migration duration and lock acquisition

Use a production-sized copy, not production, for the first measurement.

For each revision:

| Field | Record |
|---|---|
| Revision | `0032`, `0032b`, etc. |
| TPM setting | `true` |
| `PGOPTIONS` | exact values |
| Start/end time | UTC |
| Wall-clock duration | seconds |
| Max lock wait | seconds |
| Max blocked sessions | count |
| API p99 during run | ms |
| Worker heartbeat during run | healthy/stale |
| Index `indisvalid` | true/false |
| Errors | none / detail |

Run:

```bash
time PGOPTIONS="-c lock_timeout=3s -c statement_timeout=60s" \
  alembic -c api/alembic.ini upgrade 0032
```

Repeat per revision, using the index timeout for `0032b`.

Do not set `lock_timeout=0` to force a measurement.

Acceptance:

- metadata revision duration fits the approved window;
- no long blocked queue on `jobs`;
- index builds complete with `indisvalid=true`;
- final timeouts have a measured margin.

## 5. Backup and off-host evidence

### 5.1 Fresh dump

```bash
pg_dump -Fc -f /backups/p1-pre-<timestamp>.dump <database>
test -s /backups/p1-pre-<timestamp>.dump
sha256sum /backups/p1-pre-<timestamp>.dump
```

Record size, timestamp, checksum.

### 5.2 Integrity

```bash
pg_restore --list /backups/p1-pre-<timestamp>.dump > /dev/null
```

Pass: exit 0.

### 5.3 Off-host

Copy to independent storage and verify checksum.

### 5.4 Restore rehearsal

Restore into a disposable database/container. Record:

- restore start/end;
- restore duration;
- table counts;
- `alembic_version`;
- old API/worker smoke result;
- key/decrypt check.

Do not restore over production.

## 6. RPO and PITR

Record:

| Decision | Value |
|---|---|
| RPO accepted | yes/no |
| RPO value | `<measured/approved>` |
| PITR enabled | yes/no |
| PITR restore tested | yes/no/not applicable |
| Data-loss window | `<approved>` |
| Approver | `<name/role>` |

Current production state observed at preflight: `archive_mode=off`, no PITR,
latest dump more than 24 hours old. These are not acceptable production
recovery evidence until the decisions above are recorded.

## 7. Change window and ownership

Record:

- migration owner (name/role);
- DBA on call;
- operations on call;
- change record ID;
- window start/end;
- backup sidecar pause/resume owner;
- rollback decision owner;
- communication channel;
- stop/go authority.

## 8. Evidence file layout

```text
docs/evidence/p1/
  environment.txt
  table-stats.txt
  index-inventory.txt
  locks-baseline.txt
  locks-during-0032.txt
  duration-0032.txt
  duration-0032b.txt
  dump-metadata.txt
  dump-sha256.txt
  restore-duration.txt
  rpo-pitr-decision.md
  change-window.md
  operator-signoff.md
```

Do not store secrets, encryption keys, or credentials in evidence files.

## 9. Acceptance criteria

Production evidence is complete only when:

1. Environment/config is recorded.
2. Production-sized table stats and index inventory are recorded.
3. Baseline and during-migration lock behavior are recorded.
4. Each revision duration is measured on a production-sized copy.
5. Index validity is confirmed.
6. Fresh dump is non-zero and `pg_restore --list` passes.
7. Off-host checksum matches.
8. Restore rehearsal passes with measured duration.
9. RPO/RTO are approved.
10. PITR decision is recorded.
11. Change window and owner are recorded.
12. Evidence is reviewed and approved.

## 10. Stop condition

This is an evidence plan. Do not collect production evidence until the required
access and change approval exist. Do not change production settings. P1 remains
unauthorized.
