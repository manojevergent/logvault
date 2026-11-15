# Release 1 - Production Deployment and Rollback Runbook

Status: **prepared, NOT executed.** No production system was touched. Gate B is
NOT GRANTED. Every command below is for a future approved deployment window.

Two rules override convenience:

1. **Migration first, code second.** New Release 1 code fails on schema `0031`
   (`UndefinedColumn: jobs.lease_token`, verified). There is no compatible
   order where code lands first.
2. **No downgrade while dispatch obligations exist.** A downgrade drops
   `job_dispatch_outbox`. If any obligation is unresolved, downgrading destroys
   the only record that work is owed. See section 5.

---

## 1. Pre-deployment checks

| Check | Command | Pass condition |
|---|---|---|
| Current schema | `alembic current` | `0031` |
| Target schema | `alembic heads` | single head `0034` |
| Disk headroom | `df -h <pgdata>` | > 2x current database size free |
| Replica lag | `SELECT client_addr, state, sent_lsn, replay_lsn FROM pg_stat_replication;` | caught up |
| Open jobs | `SELECT status, count(*) FROM jobs GROUP BY status;` | documented |
| Outbox state | `SELECT status, count(*) FROM job_dispatch_outbox GROUP BY status;` | empty on `0031` |
| App health | `curl -fsS $API/ready` | `postgres: ok, redis: ok` |

Record every value. These are the rollback comparison baseline.

## 2. Database backup

```bash
pg_dump -Fc -f /backups/pre-release1-$(date +%Y%m%dT%H%M%S).dump "$DATABASE_URL"
pg_restore --list /backups/pre-release1-*.dump | head
```

Verify by restoring into a scratch database and comparing `alembic_version` and
row counts before proceeding. An unverified backup is not a backup.

## 3. Migrations 0032 - 0034

Apply **one revision at a time**. Never `alembic upgrade head`.

```bash
export PGOPTIONS='-c lock_timeout=5s -c statement_timeout=15min'
alembic upgrade 0032      # 11 columns on jobs
alembic upgrade 0032b     # 3 partial concurrent indexes (autocommit blocks)
alembic upgrade 0033      # artifact/checkpoint pointers
alembic upgrade 0034      # job_dispatch_outbox
```

Verify after each step:

```sql
SELECT version_num FROM alembic_version;
SELECT count(*) FROM information_schema.columns
 WHERE table_name='jobs' AND column_name IN
 ('owner_id','lease_token','lease_expires_at','heartbeat_at','progress_at',
  'pause_requested_at','cancel_requested_at','completion_state','gap_count',
  'gap_reason','retry_of','store_path','spec_fingerprint','checkpoint_version');
-- expect 14
SELECT c.relname, i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
 WHERE c.relname IN ('ix_jobs_lease','ix_jobs_owner','ix_jobs_progress');
-- expect 3 rows, all true
```

Failure handling: a lock or statement timeout aborts only the current revision;
the version stays at the previous one. Do not stamp. Find the blocker, retry.
An invalid concurrent index must be dropped with `DROP INDEX CONCURRENTLY`
before re-running `0032b`.

## 4. Application deployment order

```bash
# 4.1 API (must be after migrations)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build api
curl -fsS $API/ready && curl -fsS $API/health/ops

# 4.2 Worker (replaces the old embedded-beat worker)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build worker

# 4.3 Exactly one Beat, under the guard
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d beat
docker logs <beat> --tail 20   # expect "beat_guard: acquired logvault:beat:lock"
```

Never scale beat: `docker compose up -d --scale beat=1` only. A second instance
exits non-zero by design, but do not rely on that as the primary control.

## 5. Rollback runbook (tested)

### Data-loss rule

`alembic downgrade 0031` drops `job_dispatch_outbox`. There is **no** supported
case for accepting that silently. If any obligation is unresolved, **do not
downgrade**. Choose one of:

- finish dispatching, then downgrade; or
- keep the new schema and roll back only application code (schema is additive
  and the old code runs on `0034` - verified); or
- escalate as an incident with an explicit, recorded decision.

### Drain procedure (tested in disposable PostgreSQL)

1. **Stop acceptance.** Remove the API from the load balancer / scale API to 0.
   Confirm no new job commits:
   ```sql
   SELECT count(*) FROM jobs WHERE created_at > now() - interval '60 seconds';
   -- must stop increasing
   ```
2. **Stop dispatch acquisition.** Stop the dispatcher (beat) but keep one
   worker for in-flight work:
   ```bash
   docker compose stop beat
   ```
3. **Settle leases.** Release anything held:
   ```sql
   UPDATE job_dispatch_outbox
      SET status='pending', locked_by=NULL, locked_until=NULL
    WHERE status='leased';
   ```
4. **Publish what is owed - through the real dispatcher only.**

   `published` has exactly one meaning: the broker accepted the message and the
   guarded database transition confirmed it. **Never set `published` by hand to
   clear a gate.** A row may leave `pending` only via
   `worker/app/outbox.py:mark_published()`, which requires `status='pending'`,
   the dispatcher's own `locked_by`, and exactly one affected row.

   ```bash
   # with the API stopped and one dispatcher running:
   celery -A app.celery_app.celery call logvault.publish_outbox
   # repeat until the dispatcher reports a zero backlog
   ```

   Verify, do not assume:
   ```sql
   SELECT status, count(*) FROM job_dispatch_outbox GROUP BY status;
   -- pending must reach 0 by publication, not by UPDATE ... SET status
   ```

5. **Dead rows are resolved by job state, never by relabelling.** A dead row
   means dispatch was never confirmed. It may be:

   - replayed (reset to `pending` and dispatched), or
   - resolved by making its **job** terminal, with an audit event recording the
     operator decision.

   ```sql
   -- option A: replay
   UPDATE job_dispatch_outbox SET status='pending', attempts=0,
          next_attempt_at=now(), last_error=NULL
    WHERE status='dead' AND job_id = <id>;

   -- option B: the job is abandoned. The row stays 'dead'; the JOB carries the
   -- truth, and the audit event records who decided it.
   INSERT INTO job_events (job_id, ts, level, message)
   SELECT job_id, now(), 'warning',
          'rollback: job abandoned undelivered by operator <id>'
     FROM job_dispatch_outbox WHERE status='dead' AND job_id = <id>;
   UPDATE jobs SET status='failed', finished_at=now(),
          error_message='abandoned during rollback: dispatch never confirmed'
    WHERE id = <id>;
   ```

   A dead row whose job is terminal is not an outstanding obligation. A dead row
   whose job is non-terminal **is**, and blocks the downgrade.
6. **Make every non-terminal job recoverable by the legacy path.** Legacy code
   re-dispatches `queued` and `paused` work; it cannot recover `running` with no
   lease:
   ```sql
   UPDATE jobs SET status='queued', owner_id=NULL, lease_expires_at=NULL
    WHERE status='running' AND lease_expires_at IS NULL;
   ```
7. **Gate - all four must hold before any downgrade:**
   ```sql
   -- 1. nothing queued or in flight
   SELECT count(*) FROM job_dispatch_outbox WHERE status IN ('pending','leased'); -- 0
   -- 2. no job stuck running with nobody holding a lease
   SELECT count(*) FROM jobs WHERE status='running' AND lease_expires_at IS NULL; -- 0
   -- 3. every non-terminal job still has a dispatch record (recovery path)
   SELECT count(*) FROM jobs WHERE status NOT IN ('completed','failed','canceled')
     AND id NOT IN (SELECT job_id FROM job_dispatch_outbox);                    -- 0
   -- 4. every dead row belongs to a terminal job (resolved, not hidden)
   SELECT count(*) FROM job_dispatch_outbox o JOIN jobs j ON j.id = o.job_id
    WHERE o.status='dead' AND j.status NOT IN ('completed','failed','canceled'); -- 0
   ```

   Any non-zero value aborts the downgrade. There is no "accept the loss" path:
   the only resolutions are publish it, replay it, or make the job terminal
   through the approved state.
8. **Stop worker, then beat.** Worker first so nothing new is claimed.
9. **Downgrade.**
   ```bash
   alembic downgrade 0031
   ```
10. **Verify.** Version `0031`, job inventory identical to the baseline, all
    non-terminal jobs `queued`, audit events present.

### Broker messages already in Redis

Published messages live in Redis independently of the database. After a
downgrade the old worker consumes them and ignores lease tokens (verified: old
worker on `0034` schema works). Messages the **new** worker cannot run are
redelivered to whichever worker is attached, so attach the old worker before
downgrading and let the queue drain. Do not flush the queue: that is the same
silent loss the outbox exists to prevent.

### Tested drill evidence

```
pre  outbox={dead:1, leased:1, pending:2, published:2}
post_drain obligations=all published  non_terminal_jobs_without_dispatch=0
gate  outstanding_dispatch=0  running_without_lease=0  SAFE_TO_DOWNGRADE=True
downgrade 4 revisions → version=0031
post  jobs_total=6  by_status=completed:1 failed:1 queued:4
      outbox_table=absent  nonterminal_recoverable=4  audit_events=1
```

## 6. Controlled test job after deployment

1. Create one small job through the API.
2. Confirm `job_dispatch_outbox` reaches `published` within 10s.
3. Confirm the job reaches `completed` and `completion_state='complete'`.
4. Download via the signed URL; confirm the file opens.
5. Confirm `output_file_path` points at an existing file under
   `job_<id>/a<token>/`.

Any failure here is a stop condition.

## 7. Dispatch health verification

```bash
curl -fsS $API/health/dispatch | jq '.status, .metrics, .broker'
```

Expect `status: ok`, `outbox_oldest_pending_age_s` near 0, `beat_lock_present: 1`.

## 8. Stop conditions

Abort and roll back if any of these occur:

- Migration error that leaves the version behind the actual schema.
- `/ready` degraded for more than 2 minutes.
- `outbox_oldest_pending_age_s` above 300 with jobs still being accepted.
- Any job completed with a NULL `output_file_path`.
- Two beat locks observable, or duplicate periodic dispatch.
- Worker crash loop.

## 9. Post-deployment observation

| Window | Check |
|---|---|
| 15 min | dispatch health `ok`, no dead rows |
| 1 h | no lease expiries beyond baseline, queue depth normal |
| 24 h | partial-job count, artifact drift = 0, one clean backup |

## 10. Configuration requirements (placeholders)

| Variable | Required |
|---|---|
| `DATABASE_URL` | production DSN, pooled |
| `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | production Redis |
| `LAST9_ENCRYPTION_KEY` | existing production Fernet key - unchanged |
| `JWT_SECRET` | existing production value |
| `STORAGE_DIR` | shared persistent volume, writable by worker |
| `BACKUP_DIR` | host path for `pg_dump` output |

No default, no committed secret. `change-me-in-production` must never reach
production.
