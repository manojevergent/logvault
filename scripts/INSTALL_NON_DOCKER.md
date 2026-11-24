# Non-Docker install (single Linux host)

Use this when the host cannot run Docker — for example the AWS instance that
runs LogVault today. The script installs Postgres, Redis, Python, Node and
Nginx directly, and runs four systemd services instead of containers.

The Docker path (`./deploy.sh`) remains the default for the dev machine. This
script is self-contained and does not touch Docker.

Supported: **Ubuntu 22.04 / 24.04** and **Amazon Linux 2023**.

---

## What it installs

| Component | Local service | Bound to |
|---|---|---|
| API (FastAPI + uvicorn) | `logvault-api` | `127.0.0.1:8000` |
| Extraction worker (Celery) | `logvault-worker` | — |
| Scheduler (Celery beat, guarded) | `logvault-beat` | — |
| Web (Next.js standalone) | `logvault-web` | `127.0.0.1:3000` |
| PostgreSQL | `postgresql` | `127.0.0.1:5432` |
| Redis | `redis-server` / `redis6` | `127.0.0.1:6379` |
| Nginx | `nginx` | `80` / `443` |
| Nightly `pg_dump` | `logvault-backup.timer` | 02:30 daily |

Nginx is the only public listener. It serves the web app at `/` and proxies the
API at `/api/`, stripping the prefix. That matters because the FastAPI routes
are mounted at the root (`/auth/login`, `/jobs`, …), so the browser bundle is
built with `NEXT_PUBLIC_API_BASE_URL=https://<host>/api`.

Paths:

```
/opt/logvault/app            checkout (api/, worker/, web/, scripts/)
/opt/logvault/api/.venv      API virtualenv
/opt/logvault/worker/.venv   worker virtualenv
/etc/logvault/logvault.env   runtime config + generated secrets (0640)
/var/lib/logvault/exports    generated CSVs
/var/backups/logvault        nightly dumps
/var/log/logvault            reserved
```

---

## Before you start

1. **DNS** — point `DOMAIN` at the instance if you want TLS.
2. **Security group** — allow `80` and `443` only. The API, web, Postgres and
   Redis all listen on loopback.
3. **Repo access** — the repository is private. Either:
   - clone it on the host with a deploy key, or
   - clone/pull it on your machine and run the installer from that checkout
     (the script copies the tree to `/opt/logvault/app`).

   If you clone on the host, the checkout must be readable by the installer;
   the script will `chown` the copy it makes.

---

## Quick start

From a checkout of this repo:

```bash
sudo DOMAIN=logvault.example.com \
     TLS=1 TLS_EMAIL=ops@example.com \
     ./scripts/install.sh
```

Without a domain (plain HTTP, access by IP):

```bash
sudo ./scripts/install.sh
```

Dry run first if you want to see every command:

```bash
sudo DOMAIN=logvault.example.com TLS=1 TLS_EMAIL=ops@example.com \
     ./scripts/install.sh --dry-run
```

The first run generates:

- the database password
- `LAST9_ENCRYPTION_KEY` (Fernet)
- `JWT_SECRET`
- an initial admin password (printed once, and stored in the env file)

It prints the admin email/password and the service commands at the end.

---

## Configuration

All settings are environment variables. You can also put them in
`/etc/logvault/install.conf` (`KEY=value` lines); explicit environment variables
win.

| Variable | Default | Meaning |
|---|---|---|
| `DOMAIN` | hostname | Public hostname used in URLs and TLS |
| `TLS` | `0` | `1` obtains a Let's Encrypt certificate via webroot |
| `TLS_EMAIL` | — | Required when `TLS=1` |
| `API_PORT` | `8000` | Loopback port for the API |
| `WEB_PORT` | `3000` | Loopback port for the web app |
| `API_WORKERS` | `4` | uvicorn worker processes |
| `WORKER_CONCURRENCY` | `4` | concurrent extraction jobs |
| `APP_USER` | `logvault` | service account |
| `APP_DIR` | `/opt/logvault/app` | checkout location |
| `DATA_DIR` | `/var/lib/logvault` | exports live in `DATA_DIR/exports` |
| `BACKUP_DIR` | `/var/backups/logvault` | `pg_dump` output |
| `ENV_FILE` | `/etc/logvault/logvault.env` | runtime config |
| `DB_NAME` / `DB_USER` | `logvault` | local database |
| `DB_PASSWORD` | generated | database password |
| `DATABASE_URL` | — | set to use an external Postgres and skip local setup |
| `REDIS_URL` | local | set to use an external Redis |
| `LAST9_ENCRYPTION_KEY` | generated | **never rotate** after credentials are saved |
| `JWT_SECRET` | generated | session signing key |
| `INITIAL_ADMIN_EMAIL` | `admin@logvault.local` | first admin |
| `INITIAL_ADMIN_PASSWORD` | generated | first admin password |
| `DEFAULT_ORG_SLUG` | `evergentapse1` | Last9 default org |
| `LAST9_API_BASE` | `https://app.last9.io/api/v4` | Last9 endpoint (BYOC can change it in Admin later) |
| `EXPORT_RETENTION_DAYS` | `30` | how long exports are kept |
| `BACKUP_RETENTION_DAYS` | `14` | how many nightly dumps are kept |
| `SEED_SAMPLE_INDEX` | `0` | `1` seeds the sample `UMServices` index |

Generated secrets are written once. Re-running the installer reads them back
from `ENV_FILE`, so a normal update never invalidates saved Last9 credentials.

---

## Updating

```bash
sudo /opt/logvault/app/scripts/install.sh --update
```

`--update` pulls the checkout, reinstalls Python dependencies, rebuilds the web
app, runs `alembic upgrade head`, and restarts the services. Skip the web build
when only Python changed:

```bash
sudo SKIP_WEB_BUILD=1 /opt/logvault/app/scripts/install.sh --update
```

---

## Importing the saved searches

The bundle exported from the old instance is a JSON file. Copy it to the host,
then run the importer against the local API:

```bash
# dry run first
sudo -u logvault /opt/logvault/app/api/.venv/bin/python \
  /opt/logvault/app/scripts/import_saved_searches.py \
  --base-url http://127.0.0.1:8000 \
  --email 'admin@logvault.local' --password '<admin password>' \
  --bundle /root/saved-searches-bundle.json --dry-run

# then for real
sudo -u logvault /opt/logvault/app/api/.venv/bin/python \
  /opt/logvault/app/scripts/import_saved_searches.py \
  --base-url http://127.0.0.1:8000 \
  --email 'admin@logvault.local' --password '<admin password>' \
  --bundle /root/saved-searches-bundle.json --on-conflict skip
```

Credentials are matched by label and are **not** created by the importer,
because a credential needs a Last9 refresh token. Add the credentials in the UI
first; the saved searches then map to them. Missing indexes are created
automatically. See `scripts/IMPORT_SAVED_SEARCHES.md` for the full mapping.

---

## TLS

`TLS=1` writes an HTTP challenge site, runs `certbot certonly --webroot`, then
rewrites Nginx with the certificate and an HTTP→HTTPS redirect. Renewal is
handled by the `logvault-certbot-renew.timer` (twice daily; `certbot renew` is a
no-op until the certificate is near expiry).

If TLS is terminated upstream (ALB/CloudFront), leave `TLS=0` and point
`DOMAIN` at the public name; set `X-Forwarded-Proto` at the load balancer. The
web bundle bakes the API URL at build time, so changing the scheme or host
requires an update run (which rebuilds it).

---

## Troubleshooting

```bash
systemctl status logvault-api logvault-worker logvault-beat logvault-web
journalctl -u logvault-api -n 100 --no-pager
journalctl -u logvault-worker -n 100 --no-pager
nginx -t
```

| Symptom | Check |
|---|---|
| Web opens but every action 404s | `NEXT_PUBLIC_API_BASE_URL` was wrong at build time; re-run with the right `DOMAIN` |
| Login works, jobs never start | `systemctl status logvault-worker`; check Redis with `redis-cli ping` |
| Scheduler not firing | `journalctl -u logvault-beat`; the guard refuses to start if another beat holds `logvault:beat:lock` in Redis |
| 502 from Nginx | API/web not listening: `ss -ltnp \| grep -E '8000\|3000'` |
| SSE progress never updates | Nginx must have `proxy_buffering off` on `/api/`; the generated config does |
| `alembic` fails | `DATABASE_URL` in the env file; Postgres running; `pg_hba.conf` allows 127.0.0.1 password auth |
| Public downloads fail | They are signed URLs under `/api/jobs/...`; check `PUBLIC_API_BASE_URL` |

Logs are on the systemd journal; the app does not write its own log files.