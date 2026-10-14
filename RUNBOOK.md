# LogVault — Runbook

Operational guide: deploy, scale, troubleshoot, rotate secrets. For architecture
and local setup see [README.md](README.md).

## Deploy (Docker Compose on a VM)

Always deploy with the production overlay. `docker-compose.yml` on its own is
the **dev** stack: `web` runs `next dev` (which compiles every route on first
request, and with `WATCHPACK_POLLING` polls the filesystem forever) and `api`
runs `uvicorn --reload`. Served that way the UI feels slow no matter what the
API does.

```bash
git pull
cp .env.example .env            # first time only; then fill secrets (below)

alias lv='docker compose -f docker-compose.yml -f docker-compose.prod.yml'
lv build
lv up -d
lv exec api alembic upgrade head    # run migrations
lv exec api python -m app.seed      # optional: sample index
```

(`COMPOSE_FILE=a:b` works on Linux, but the separator is `;` on Windows and
gets confused with drive letters — the explicit `-f` flags behave the same
everywhere.)

The overlay swaps `web` to the standalone `Dockerfile.prod` build, drops the
source bind mounts, and runs the API under 4 uvicorn workers with no reloader.
`NEXT_PUBLIC_API_BASE_URL` must be set **before `build`** — Next inlines it into
the client bundle at build time, so changing it later needs a rebuild, not a
restart.

Health: `curl localhost:8000/health` (liveness), `/ready` (Postgres + Redis).

For local development, drop the `-f` flags: a plain `docker compose up` gives
you the hot-reloading dev stack as before. The two stacks build `web` to
different tags (`last9_web_app-web` vs `last9_web_app-web:prod`) so neither
overwrites the other — if you ever see `sh: next: not found` (exit 127) from
the dev `web` container, it is running a prod image and needs
`docker compose build web` once to restore the dev one.

## Secrets

Generate once, store in `.env` (never commit):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # LAST9_ENCRYPTION_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"                                # JWT_SECRET
```

**Rotating `LAST9_ENCRYPTION_KEY`** re-encrypts nothing automatically — existing
`last9_credentials` rows become undecryptable. To rotate: re-enter each
credential's refresh token after deploying the new key (or write a one-off
re-encrypt script using the old key to decrypt and the new to encrypt).

`JWT_SECRET` signs download links; rotating it invalidates outstanding links
(they regenerate on next page load).

## Scaling

- **Workers**: `docker compose up -d --scale worker=N`. Each worker runs
  `--concurrency=4`; jobs are independent. `worker_prefetch_multiplier=1` keeps
  one big job from starving others.
- **Long jobs**: chunked + checkpointed — a restarted worker resumes from the
  last completed chunk (exact, via CSV byte offset). Safe to redeploy mid-job.
- **Storage**: CSVs land in the `exports` volume (`STORAGE_DIR`). Mount durable
  storage in prod. Retention is `EXPORT_RETENTION_DAYS`, enforced hourly by
  `logvault.cleanup_exports`. A job refuses to start below `MIN_FREE_DISK_GB`
  free — `exports` and `pgdata` share a filesystem, so a run that fills the disk
  would stop Postgres writing and take everything down with it.

## Backup & restore

The `backup` service dumps the database on start and then daily, into
`BACKUP_DIR` on the host (default `./backups`), keeping 14 days. That volume
holds everything the platform knows: credentials (encrypted refresh tokens
included), index targets, schedules, templates and the whole job history.

```bash
ls -lh backups/                       # newest dump
docker compose logs backup            # did last night's run succeed?
curl -s localhost:8000/health/ops     # "backups": stale => nobody is dumping
```

Restore into a clean database:

```bash
docker compose stop api worker
docker compose exec -T postgres dropdb   -U logvault logvault
docker compose exec -T postgres createdb -U logvault logvault
docker compose exec -T postgres pg_restore -U logvault -d logvault --no-owner   < backups/logvault-YYYYmmdd-HHMMSS.dump
docker compose start api worker
```

`LAST9_ENCRYPTION_KEY` must be the same one that was in use when the dump was
taken, or every stored credential restores as undecryptable ciphertext. Keep it
with the backups, somewhere the backups are not.

The dumps sit on the same physical disk as the data they protect: they cover
`down -v`, a bad migration and an accidental delete, but not a dead disk. Copy
`BACKUP_DIR` off the box (rsync/S3/whatever this VM already backs up to) to
cover that too.

## Monitoring

`GET /health/ops` reports the two failures that are otherwise silent, with no
auth required so a probe can poll it:

| Check | `degraded` means |
| --- | --- |
| `worker_beat` | no beat tick in `WORKER_BEAT_STALE_SECONDS` — the worker is down or its scan is throwing, and **schedules are not firing** |
| `backups` | newest dump older than `BACKUP_STALE_HOURS` |

`/health` (liveness) and `/ready` (Postgres + Redis) are unchanged — a dead
worker deliberately does **not** make the API unready, or a healthy container
would be pulled from rotation for someone else's outage.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Worker not consuming | `docker compose logs worker`; `redis-cli -u $CELERY_BROKER_URL ping`; task name `logvault.run_job` matches |
| Job stuck "queued" | worker up? broker URL matches between api (`CELERY_BROKER_URL`) and worker? |
| Job "failed" | open the job → error message; or `job_events` table (level=error) |
| Job failed "refusing to start" | disk nearly full — `df -h`, prune `exports`, lower `EXPORT_RETENTION_DAYS` |
| Job failed "worker presumed dead" | reaped after `STALE_JOB_MINUTES` of silence; check worker logs for an OOM-kill, then retry (resumes from checkpoint) |
| Login returns 429 | `LOGIN_MAX_ATTEMPTS` failures on that email; wait `LOGIN_LOCKOUT_SECONDS`, or `redis-cli DEL login:fail:<email>` |
| Schedules silently stopped | `curl localhost:8000/health/ops` → `worker_beat` |
| Token refresh fails | `LAST9_ENCRYPTION_KEY` identical across api+worker; test via `POST /credentials/{id}/test` |
| SSE not updating | `/jobs/{id}/progress` returns `text/event-stream`? proxy buffering disabled? list falls back to 5s polling |
| Download 403 | link expired (`DOWNLOAD_URL_TTL_SECONDS`) — reopen the job for a fresh link |

## Job lifecycle

`queued → running → (paused ↔ running) → completed | failed | canceled`

- **Pause**: API sets `paused`; worker stops at the next chunk boundary.
- **Resume**: API sets `queued` + re-dispatches; worker resumes from checkpoint.
- **Cancel**: API sets `canceled`; running worker finalizes partial CSV.

## Not yet wired (architected for)

- **Auth/SSO**: endpoints are currently unauthenticated; `created_by`/`user_id`
  are nullable. Add OIDC (Auth.js → JWT verified by FastAPI) before exposing
  beyond a trusted network.
