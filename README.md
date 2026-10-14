# LogVault

Internal platform for extracting logs from **Last9** into downloadable CSVs.
A web replacement for a battle-tested Python CLI: pick a time range, region,
index, and filter, then stream matching log lines to a CSV. Jobs can run for
hours and produce millions of rows, so the work runs in background workers with
checkpoint/resume — never in the request path.

> **Status: Phase 1 (Foundation).** Running skeleton — monorepo, Docker Compose,
> Postgres + Redis, health checks, and the styled app shell + dashboard. Feature
> work lands in later phases (see [build phases](#build-phases)).

## Architecture

A job-queue architecture across four services:

| Service   | Stack                                              | Role                                                        |
| --------- | -------------------------------------------------- | ----------------------------------------------------------- |
| `web`     | Next.js 15 (App Router), TypeScript, Tailwind      | UI: dashboard, job wizard, live progress, managers          |
| `api`     | FastAPI, Pydantic, SQLAlchemy + Alembic            | Auth, CRUD, job queueing, SSE progress, signed downloads    |
| `worker`  | Celery on Redis                                    | The actual Last9 streaming — token refresh, chunking, retry |
| infra     | PostgreSQL 16, Redis 7, Docker Compose             | State, broker/cache, local orchestration                    |

State is persisted to Postgres (so a page refresh recovers a running job), Redis
is the Celery broker + cache, and generated CSVs are written to a mounted volume
with signed/expiring download links.

```
last9_web_app/
├── web/      # Next.js frontend
├── api/      # FastAPI service + Alembic migrations
├── worker/   # Celery workers
├── docker-compose.yml
└── .env.example
```

## Quick start (Docker Compose)

> Prefer the guided path: [`INSTALL.md`](INSTALL.md) (`./install.sh` on Linux,
> `.\install.ps1` on Windows) handles secrets, ports, build, migrations, seed
> and health checks in one go. Below is the manual equivalent.

```bash
cp .env.example .env
# Generate the two secrets and paste them into .env:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # LAST9_ENCRYPTION_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"                                  # JWT_SECRET

docker compose up --build
```

- Web UI:        http://localhost:3000
- API docs:      http://localhost:8000/docs
- API health:    http://localhost:8000/health
- API readiness: http://localhost:8000/ready  (verifies Postgres + Redis)

Stop with `docker compose down` (add `-v` to drop volumes / stored data).

## Local development without Docker

Run Postgres + Redis (via Docker or locally), then each service in its own
terminal:

```bash
# API
cd api && python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload

# Worker
cd worker && python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
celery -A app.celery_app.celery worker --loglevel=INFO

# Web
cd web && npm install && npm run dev
```

## Common commands

| Area     | Command                                                            |
| -------- | ----------------------------------------------------------------- |
| API test | `cd api && pytest`                                                 |
| API lint | `cd api && ruff check . && black --check .`                       |
| Migrate  | `cd api && alembic revision --autogenerate -m "msg" && alembic upgrade head` |
| Web lint | `cd web && npm run lint`                                           |
| Web type | `cd web && npm run typecheck`                                      |

## Configuration

All config is environment-driven; see [`.env.example`](.env.example) for the
full list. Secrets (`LAST9_ENCRYPTION_KEY`, `JWT_SECRET`) must be set — Last9
refresh tokens are encrypted at rest and never returned to the browser after
save.

## Build phases

1. **Foundation** — scaffold, compose, health checks, design system + shell ← _current_
2. **Last9 core library** — token mgmt, pipeline builder, regex batching, streaming, checkpoint/resume, retry
3. **Credentials & Index managers** — encrypted CRUD, test connection, region→index dropdowns
4. **Job engine** — jobs table, Celery execution, lifecycle, file output + downloads
5. **New Job wizard + live view** — creation flow, SSE progress, pause/resume/cancel, history
6. **Admin, audit, polish** — roles, audit log, settings, retention, production Dockerfiles, runbook

See [`CLAUDE_CODE_PROMPT.md`](CLAUDE_CODE_PROMPT.md) for the full product spec and
the validated Last9 API ground-truth, and [`CLAUDE.md`](CLAUDE.md) for the
engineering quick-reference.
