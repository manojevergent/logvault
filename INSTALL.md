# LogVault — Installation Guide

One script takes a fresh clone to a running stack. This document covers
requirements, the installers, what gets set up, first login, upgrades, and
uninstall. Day-to-day operations (deploy, scaling, backups, troubleshooting)
live in [RUNBOOK.md](RUNBOOK.md).

## 1. Requirements

| Need | Minimum | Notes |
| --- | --- | --- |
| OS | Linux (any modern distro) or Windows 10/11 | Use `install.sh` on Linux, `install.ps1` on Windows |
| Docker | Docker Engine 24+ / Docker Desktop 4.25+ | Must include `docker compose` (v2 plugin) |
| RAM / disk | 4 GB RAM, 20 GB free disk | Extractions write CSVs to local disk; jobs refuse to start below `MIN_FREE_DISK_GB` free |
| Network | Outbound HTTPS to `app.last9.io` and your container registry | No inbound ports need exposing beyond your own access to the UI/API |

Ports published on the host (must match `docker-compose.yml`):

| Port | Service |
| --- | --- |
| 3001 | Web UI (both stacks) |
| 8000 | API + docs |
| 5432 | PostgreSQL |
| 6380 | Redis |

If any are taken, free the process or remap the port in `docker-compose.yml`
*before* installing — the installer warns but does not remap for you.

## 2. Install

```bash
git clone <your-repo-url> logvault && cd logvault   # or: manojevergent/logvault

# Linux:
./install.sh                 # interactive — prompts for the admin account
./install.sh --yes           # non-interactive — generated admin password printed once

# Windows (PowerShell):
.\install.ps1                # interactive
.\install.ps1 -Yes           # non-interactive
```

Flags (same on both, `-` vs `--` per platform):

| Flag | Effect |
| --- | --- |
| `--dev` | Hot-reloading dev stack instead of the production overlay |
| `--yes` | No prompts; default admin `admin@logvault.local` with a generated password (save it) |
| `--admin-email / --admin-password` | Set the initial admin explicitly |
| `--api-base URL` | API base URL (default `http://localhost:8000`); baked into the web build, so changing it later requires a rebuild |

Takes ~5–15 minutes depending on image pulls. The admin account is created on
first login — use the `INITIAL_ADMIN_EMAIL` / `INITIAL_ADMIN_PASSWORD` from
your `.env`.

## 3. What the installer does

1. **Preflight** — docker, compose, daemon, `curl`, and conflicting ports.
2. **`.env`** — copied from `.env.example` if absent (an existing file is
   never overwritten). Fills in a generated `LAST9_ENCRYPTION_KEY` and
   `JWT_SECRET`, sets `CORS_ORIGINS` to both `localhost:3000` and
   `localhost:3001` (the example allows only 3000, which otherwise breaks
   login with a CORS error), and stores the admin credentials.
3. **Build + start** — `docker compose -f docker-compose.yml
   -f docker-compose.prod.yml build` + `up -d` (dev: base file only).
4. **Health gates** — waits for Postgres (`pg_isready`), Redis (`PING`), and
   API `/health` before touching the database.
5. **Migrate + seed** — `alembic upgrade head`, then `python -m app.seed`
   (sample `UMServices` index; both are safe no-ops on re-run).
6. **Verify** — checks `/ready` and prints URLs, login, and next commands.

The script is idempotent: re-running it after a failure resumes rather than
starting over.

## 4. First login and first extraction

1. Open http://localhost:3001, sign in with the admin account.
2. **Settings → Credentials** — add one Last9 credential per region
   (`org_slug` + refresh token). Use **Test connection** on each.
3. **Indexes** — add the `UMServices` physical index per region code.
4. **New extraction** — pick source, time range, filter; optionally enable
   **Parse & aggregate** and number the output columns (see below).
5. **Schedules** — turn a proven search into a daily run.

For the invoice-API-logs batch (regions, customers, parse rules, schedules),
follow [LOGVAULT_JOB_SETUP_GUIDE.md](LOGVAULT_JOB_SETUP_GUIDE.md) and
[INVOICE_API_LOGS_COMPLETE_MAPPING.md](INVOICE_API_LOGS_COMPLETE_MAPPING.md).

### Google sign-in (optional)

Password login works out of the box. To add **Continue with Google** alongside
it:

1. In the [Google Cloud console](https://console.cloud.google.com/apis/credentials),
   create an **OAuth client ID** (type: Web application) and add an
   **Authorized redirect URI** exactly:
   `{PUBLIC_API_BASE_URL}/auth/google/callback`
   (default `http://localhost:8000/auth/google/callback`).
2. Set in `.env` and restart (no rebuild needed — these are runtime settings):
   `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and preferably
   `GOOGLE_ALLOWED_DOMAINS` (e.g. your Workspace domain; empty allows any
   verified Google account).
3. The login page shows the Google button automatically once configured
   (`GET /auth/providers`).

Behavior notes: first Google sign-in creates a `member` account (or `admin`
if the users table is empty); an existing password account that signs in with
the same email gets linked and keeps working both ways; linking never changes
roles — admins promote via Admin → Users. Sessions are the same 24h JWTs as
password login.

### Uniform CSV columns

Every extract can emit the same columns in the same order: in the Parse
section, open the **Output columns** table, tick the fields, type the
sequence (1 = first column after timestamp), and name the CSV header.
**Apply uniform invoice order** does `timestamp, api, spAccountID,
channelPartnerID, bu_name` in one click. Saved searches keep the layout, so
schedules inherit it.

Upgrading an existing database whose searches predate this feature:

```bash
docker compose exec api python -m app.uniform_columns_migration        # dry run
docker compose exec api python -m app.uniform_columns_migration --apply
```

## 5. Upgrades

```bash
git pull
./install.sh            # rebuilds images, restarts, migrates; keeps .env and data
```

`install.sh` preserves `.env` and all volumes (database, exports). For a
code-only redeploy without the full install flow, `./deploy.sh [api|worker|web]`
(Git Bash on Windows) rebuilds just those services. Never `docker restart`
alone after a code change on the prod overlay — images are baked, so a restart
without a rebuild silently keeps running the old code.

## 6. Uninstall

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml down      # keep data
docker compose -f docker-compose.yml -f docker-compose.prod.yml down -v   # DELETE database, exports, redis
```

`down -v` destroys the Postgres volume — the nightly dumps in `./backups/`
are the way back (see RUNBOOK → Backup & restore). `git clean` will not touch
`.env`, `backups/`, or `node_modules` (all gitignored).

## 7. Troubleshooting install problems

| Symptom | Fix |
| --- | --- |
| `port is already in use` warning, then a container won't start | Free the port (`ss -ltnp` / Task Manager) or remap it in `docker-compose.yml`, then re-run the installer |
| Login fails with CORS error | `.env` `CORS_ORIGINS` must include the origin you browse from; the installer sets both localhost ports already |
| UI shows an older version after upgrade | Hard refresh (`Ctrl+Shift+R`); client-side navigation keeps the old JS bundle until a full reload |
| `alembic upgrade head` fails | Postgres wasn't healthy yet — check `docker compose logs postgres`, wait, re-run the installer |
| `API not ready` / `/ready` fails | `docker compose ps`, then `docker compose logs api`; needs Postgres + Redis reachable |
| Login returns 429 | Too many failures for that email; wait `LOGIN_LOCKOUT_SECONDS` (default 15 min) |
| `LAST9_ENCRYPTION_KEY` changed and credentials broke | Expected — existing encrypted tokens are undecryptable with a new key; re-enter each credential's refresh token (RUNBOOK → Secrets) |

Anything beyond install (scaling, backups, rotation, worker issues):
[RUNBOOK.md](RUNBOOK.md).
