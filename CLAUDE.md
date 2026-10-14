# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LogVault is an internal log extraction platform for Evergent's observability infrastructure. It replaces a Python CLI with a premium web UI that streams logs from Last9 (an observability platform) into downloadable CSV files. The system supports credential management, index management, long-running extraction jobs with checkpoint/resume, real-time progress tracking, and audit trails.

Target users: 60–180 engineers at Evergent.

Key constraint: Jobs can run for hours and produce millions of rows; the architecture must never accumulate data in memory.

---

## Architecture Overview

This is a monorepo with four main components:

### 1. Frontend (/web)
- Framework: Next.js 15+ (App Router) + TypeScript
- State: TanStack Query (server state) + Zustand (local UI state)
- Styling: Tailwind CSS + shadcn/ui components
- Design: Dark-mode-first, premium SaaS aesthetic (reference: Linear, Vercel, Stripe)
- Real-time updates: Server-Sent Events (SSE) from backend for job progress
- Auth: Auth.js/NextAuth with OIDC SSO (fallback: email magic-link or admin-provisioned accounts)

### 2. Backend API (/api)
- Framework: Python FastAPI
- Validation: Pydantic
- Database ORM: SQLAlchemy + Alembic (migrations)
- Key responsibilities:
  - JWT auth and token validation
  - CRUD for credentials (encrypted), indexes, and jobs
  - Job queueing and status lifecycle
  - SSE endpoints for live progress
  - Signed download links for CSV output

### 3. Worker (/worker)
- Job queue: Celery (or RQ/Arq) consuming from Redis
- Core logic: Last9 API client (token refresh, pipeline building, regex batching, streaming pagination, chunking, checkpoint/resume)
- Output streaming: Never loads full results into memory; writes rows as they arrive
- Concurrency: Fair queueing with per-worker and global limits

### 4. Infrastructure (/infra)
- Local dev: docker-compose.yml (postgres + redis + api + worker + web)
- Deployment: Production-ready Dockerfiles with health checks, graceful shutdown, env-based config
- Secrets: Last9 refresh tokens encrypted at rest (Fernet/AES from env/KMS), never logged

---

## Development Setup

### Prerequisites
- Docker & Docker Compose
- Python 3.11+
- Node.js 18+

### Local Development with Docker
```bash
docker-compose up
docker exec last9-api alembic upgrade head
docker exec last9-api python -m app.seed

# Frontend: http://localhost:3000
# Backend API docs: http://localhost:8000/docs
```

### Without Docker (rapid iteration)
Terminal 1: postgres/redis
```bash
docker run --rm -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:15
docker run --rm -d -p 6379:6379 redis:7
```

Terminal 2: Backend API
```bash
cd api
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Terminal 3: Worker
```bash
cd worker
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
celery -A app.celery worker --loglevel=info
```

Terminal 4: Frontend
```bash
cd web
npm install
npm run dev
```

---

## Common Commands

### Frontend (/web)
```bash
npm install              # Install dependencies
npm run dev              # Development server
npm run build            # Build for production
npm run start            # Run production build
npm test                 # Run tests
npm test -- --watch     # Watch mode
npm run lint             # Lint
npm run format           # Format code
npm run typecheck        # Type check
```

### Backend API (/api)
```bash
# Install & run
pip install -r requirements.txt
pip install -r requirements-dev.txt
uvicorn app.main:app --reload

# Testing
pytest
pytest --cov=app
pytest tests/test_last9_client.py
pytest tests/test_last9_client.py::test_token_refresh

# Code quality
ruff check . && black --check .
ruff check --fix . && black .

# Database
alembic upgrade head
alembic downgrade -1
alembic revision --autogenerate -m "description"
```

### Worker (/worker)
```bash
pip install -r requirements.txt
celery -A app.celery worker --loglevel=info
celery -A app.celery worker -c 4                 # With concurrency limit
celery -A app.celery inspect active
celery -A app.celery purge
```

### Docker Compose
```bash
docker-compose up
docker-compose up -d                             # Background
docker-compose logs -f
docker-compose logs -f api                       # Specific service
docker-compose down
docker-compose down -v                           # Remove volumes
docker-compose build
docker-compose exec api alembic upgrade head     # Run command in service
```

---

## Critical Last9 API Knowledge

These facts were learned against the production API. Implement exactly as written.

### Key Endpoints
```
Base:       https://app.last9.io/api/v4/organizations/{org_slug}
Query logs: POST {base}/logs/api/v2/query_range/json
OAuth:      POST https://app.last9.io/api/v4/oauth/access_token
Labels:     GET  {base}/logs/api/v1/labels
Label vals: GET  {base}/logs/api/v1/label/{labelName}/values
```

### Authentication
- Header: X-LAST9-API-TOKEN: Bearer <ACCESS_TOKEN> (NOT Authorization)
- Access tokens expire in 24 hours
- Refresh: POST .../oauth/access_token with {"refresh_token": "<token>"}
- On 401 or 200 with "Authorization token is expired": refresh inline and retry

### Query Request Body
The pipeline MUST be a JSON array, even for a single stage:
```json
{
  "pipeline": [
    {
      "query": { "$and": [...] },
      "type": "filter"
    }
  ]
}
```

### Valid Operators (Complete List)
$eq  $neq  $contains  $notcontains  $regex  $notregex  $gt  $lt  $gte  $lte

Critical gotchas:
- $containsWords DOES NOT EXIST - never use it
- Log message field is Body (capital B)
- Each operator: ["field", "value"] format

### The #1 Gotcha: Matching Many IDs

A $or block with many $contains/$regex clauses silently returns 0 rows. Always use single $regex with | alternation:

```json
{ "$regex": ["Body", "ID-AAA|ID-BBB|ID-CCC"] }
```

Batch approximately 100 IDs per regex (produces ~5 KB requests). Escape metacharacters except hyphens.

### Filter Semantics

Expose UI as:
```
(PHRASE_1 AND PHRASE_2 AND …) AND (ID_1 OR ID_2 OR …)
```

### Pagination & Streaming
- Response: data.data.result is list of streams
- Stream each row as it arrives - NEVER accumulate in memory

### Chunking & Checkpoint/Resume
- Split time range into N-hour chunks (default 1h)
- After each chunk written, atomically advance checkpoint
- On resume: skip completed chunks, append

### Retry Policy
- 5xx / timeout / connection error → exponential backoff, 10 attempts, cap 300s
- HTTP 400 → retry 3 times at 5s, then fast-fail
- Other 4xx → fast-fail
- 401 → refresh token and retry

### Regions
- India: ap-south-1
- Virginia: us-east-1
- Singapore: ap-southeast-1
- Frankfurt: eu-central-1

Index targets are region-scoped; index dropdown must be dependent on region.

### Timezones
- API takes UTC epoch seconds
- Users think IST (UTC+5:30)
- UI must show timezone toggle (IST ↔ UTC)

---

## Data Model (PostgreSQL)

Key tables:

- **users**: id, email, name, role (admin | member), created_at
- **last9_credentials**: id, label, org_slug, encrypted_refresh_token, encrypted_access_token, access_token_expires_at, owner_scope, created_by, created_at
- **index_targets**: id, name, region_code, full_index_string, description, created_by, created_at
- **jobs**: id, owner_id, status, region_code, index_target_id, credential_id, start_epoch, end_epoch, chunk_hours, id_batch_size, filter_spec (JSONB), rows_written, total_chunks, completed_chunks, current_chunk_start, checkpoint (JSONB), output_file_path, error_message, created_at, updated_at, started_at, finished_at
- **job_events**: id, job_id, ts, level, message, rows_delta
- **audit_log**: id, user_id, action, entity, entity_id, metadata (JSONB), ts

---

## Key Architectural Patterns

### 1. Last9 Client Library
Located in /api/app/last9_client.py (or /worker/app/last9_client.py if shared).

Key functions:
- `refresh_access_token(refresh_token) -> str`
- `build_filter_pipeline(phrases: List[str], ids: List[str], batch_size=100)`
- `stream_logs(credential, index, region, start_epoch, end_epoch, filter_pipeline, chunk_hours=1)`
- `resume_job(job_checkpoint) -> Iterator[dict]`

Unit test pipeline structure, regex batching, operator validation.

### 2. Job Lifecycle
States: queued → running → (paused ↔ running) → (completed | failed | canceled)

On run:
1. Celery task consumes job from Redis queue
2. Worker loads Last9 credential (decrypts refresh token)
3. Chunks full time range, iterates
4. For each chunk: builds pipeline, handles regex batching
5. Streams rows to output file, emits job events
6. Atomically updates checkpoint after each chunk
7. On completion: generates signed download URL

On pause/resume:
- Pause: checkpoints and stops
- Resume: reads checkpoint, skips completed chunks, appends

On cancel: halts, finalizes partial output

### 3. Server-Sent Events (SSE)
Frontend opens persistent connection to /api/jobs/{job_id}/progress.

Worker emits events:
```json
{ "type": "batch_done", "rows": 150, "total": 3000 }
{ "type": "heartbeat", "status": "scanning", "current_chunk": "2024-01-15T00:00" }
{ "type": "completed" }
{ "type": "error", "message": "..." }
```

Frontend updates real-time; survives refresh via DB persistence.

### 4. Credential Encryption
Last9 refresh tokens encrypted at rest. Never return to browser after save. Show masked preview.

### 5. Regions and Index Dependency
Index dropdown dependent on region:
- When region changes, fetch indexes for that region only
- Backend endpoint: GET /api/indexes?region=ap-southeast-1

### 6. New Job Wizard Structure
Steps (multi-step or single form with sections):
1. Credential picker
2. Region & Index (dependent dropdowns)
3. Time range (presets + custom, timezone toggle)
4. Filter builder (phrases, IDs, preview JSON)
5. Options (chunk hours, batch size, filename)
6. Review & run

### 7. File Download & Expiration
CSVs written to disk or S3-compatible storage.

- Generate signed/expiring URLs (e.g., 7-day expiration)
- Stream large files; never load fully into memory
- Delete files after retention period (configurable, e.g., 30 days)

---

## Testing Strategy

Backend:
- Unit tests (/api/tests): Last9 client (pipeline, batching, token refresh), checkpoint, regex escaping, retry
- Integration tests: Job creation, credential save/load (with decryption), migrations
- Fixtures: Mock Last9 responses, test data per region

Frontend:
- Component tests: Filter builder, timezone toggle, dropdown dependency, SSE reconnection
- E2E tests: Create job → progress → download (against mock or Docker stack)

Worker:
- Task tests: Job consumption, checkpoint, file creation, pause/resume

---

## Configuration & Secrets

Environment variables (.env.local for frontend, .env for backend/worker):

- DATABASE_URL: PostgreSQL connection
- REDIS_URL: Redis connection
- LAST9_ENCRYPTION_KEY: Fernet key for credential encryption
- NEXT_PUBLIC_API_BASE_URL: frontend API base (e.g., http://localhost:8000)
- JWT_SECRET: FastAPI JWT signing key
- DEFAULT_ORG_SLUG: e.g., evergentapse1

Never commit .env or .env.local.

---

## Code Standards

Python (API & Worker):
- Formatter: Black
- Linter: Ruff
- Type hints: Required (mypy checks)
- Async: Use async/await for I/O operations
- Logging: Structured JSON with correlation IDs (never log secrets)
- Error handling: Custom exception hierarchy, descriptive responses

TypeScript/React (Frontend):
- Framework: Next.js App Router
- Type checking: Strict tsconfig
- Styling: Tailwind + CSS Modules
- Components: Functional, hooks, strict prop typing
- State: Zustand (global), TanStack Query (server)
- Accessibility: WCAG AA (keyboard, focus, contrast)

---

## Debugging & Troubleshooting

**Worker not consuming jobs:**
1. Check Redis: redis-cli ping → PONG
2. Check queue name in task dispatch matches worker binding
3. Check Celery: celery -A app.celery inspect active

**Code changes don't take effect — CHECK WHICH STACK IS RUNNING FIRST:**

There are two deployment shapes, and they need different actions:

- **Dev** (`docker-compose.yml` alone): `./api` and `./worker` are bind-mounted.
  The api runs `uvicorn --reload` and picks changes up by itself; the worker does
  not, so a worker change needs `docker restart last9_web_app-worker-1`.
- **Prod** (`docker-compose.yml` + `docker-compose.prod.yml`, which is what
  normally runs here): the overlay sets `volumes: !override`, so there is **no
  source bind-mount at all**. Images are baked, and `docker restart` picks up
  **nothing** — a restart silently runs the old code and looks like it worked.
  Rebuild and recreate instead:

  ```bash
  ./deploy.sh worker        # or: api, web, or any subset; no args = all three
  ```

  Confirm the change is actually in the container before believing it:
  ```bash
  docker exec last9_web_app-worker-1 grep -c "<something you just added>" /app/app/<file>.py
  ```

Check with `docker inspect last9_web_app-worker-1 --format '{{range .Mounts}}{{.Destination}} {{end}}'`
— if you only see `/data/exports`, you are on prod and must rebuild.

In the dev shape, editing worker code without restarting produces confusing
half-states — freshly-imported modules see the new code while cached ones don't,
e.g.:

```
ImportError: cannot import name 'format_log_timestamp' from 'app.last9'
```

Tests won't catch this: pytest starts a new process every run, so the same code
passes green while the live worker is broken.

```bash
./deploy.sh worker                        # prod: rebuild + recreate (the usual case)
docker restart last9_web_app-worker-1     # dev only: bind-mounted source
docker logs --tail 20 last9_web_app-worker-1 | grep -E "ready|Traceback"
```

`logvault.run_job` marks the job `failed` with the error when this happens, so
it surfaces in the UI instead of the job sitting in `queued` forever — but the
fix is still to restart the worker.

**Token refresh failing:**
1. Verify LAST9_ENCRYPTION_KEY set and same across services
2. Check last9_credentials table
3. Test manually: curl -X POST https://app.last9.io/api/v4/oauth/access_token -d '{"refresh_token": "..."}'

**Job hangs mid-chunk:**
1. Check worker resource limits
2. Check network issues to Last9
3. Verify checkpoint written to DB
4. Check worker logs for API errors

**SSE connection drops:**
1. Check frontend SSE connection logs
2. Verify API endpoint /api/jobs/{job_id}/progress returns text/event-stream
3. Check backend logs for exceptions
4. Increase SSE timeout if network slow

---

## Project Phases (Reference)

The CLAUDE_CODE_PROMPT.md outlines six phases:

1. **Phase 1** — Foundation: Monorepo scaffold, Docker Compose, design system, empty dashboard
2. **Phase 2** — Last9 core: Token mgmt, pipeline builder, batching, pagination, chunking, checkpoint, retry
3. **Phase 3** — Credentials & Indexes: CRUD, encryption, test connection, dependent dropdowns
4. **Phase 4** — Job engine: Jobs table, Celery, queue, status, checkpoints, file output
5. **Phase 5** — New Job wizard + live view: Creation flow, SSE, pause/resume/cancel, history
6. **Phase 6** — Admin, audit, polish: Roles, audit log, settings, design, accessibility, docs

---

## Useful References

- **CLAUDE_CODE_PROMPT.md** — Full product spec and build phases
- **Last9 API docs** — https://docs.last9.io
- **FastAPI** — https://fastapi.tiangolo.com
- **Next.js** — https://nextjs.org/docs
- **Celery** — https://docs.celeryproject.io
- **SQLAlchemy** — https://docs.sqlalchemy.org
