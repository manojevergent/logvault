# Build Prompt — "LogVault": Internal Last9 Log Extraction Platform

> Paste this entire file into Claude Code as your opening instruction. It contains
> the full product spec **and** the hard-won Last9 API knowledge needed to avoid
> weeks of trial-and-error. Treat the "Last9 API — Ground Truth" section as
> non-negotiable fact; it was validated against the live API.

---

## 0. Role & expectations

You are a senior full-stack engineer building an internal tool for a company of
60–180 engineers. The app extracts logs from Last9 (an observability platform)
and is shared across the whole team.

**Non-negotiable quality bar:** This must look and feel like a professionally
built, premium SaaS product — think Linear, Vercel dashboard, or Stripe. It must
**not** look AI-generated or "vibe-coded": no generic purple gradients, no emoji
headings, no default Bootstrap look, no clutter. Restrained, confident, modern.
Robust, scalable, and maintainable code throughout.

Build it in clear phases (below). After each phase, stop, summarize what you did,
and wait for me to confirm before continuing.

---

## 1. What the product does

A web replacement for a battle-tested Python CLI script that streams logs from
Last9's Query API into CSV files. The platform lets any team member:

1. **Run extraction jobs** — pick a time range, region, index, and filter, then
   stream matching log lines to a downloadable CSV. Jobs can run for hours and
   produce millions of rows.
2. **Manage Last9 credentials** — save access/refresh tokens once; the system
   auto-refreshes the access token (24 h expiry) transparently.
3. **Manage indexes** — create/save named index targets (e.g. `UMServices`)
   scoped to a region.
4. **Filter with AND/OR logic** — required phrases (all must match) AND a set of
   IDs/values (any one must match), with IDs loadable by paste or file upload.
5. **Watch live progress** — real-time row counts, per-batch progress, ETA.
6. **Resume interrupted jobs** — checkpoint/resume so a killed or crashed job
   continues from where it left off.
7. **Download results** and see a history/audit trail of who ran what.

---

## 2. Last9 API — GROUND TRUTH (validated against the live API — do not deviate)

This section is the most important part of the prompt. These facts were learned
the hard way against the production API. **Implement exactly as written.**

### 2.1 Endpoints

```
Base URL:   https://app.last9.io/api/v4/organizations/{org_slug}
Query logs: POST {base}/logs/api/v2/query_range/json
OAuth:      POST https://app.last9.io/api/v4/oauth/access_token
Labels:     GET  {base}/logs/api/v1/labels
Label vals: GET  {base}/logs/api/v1/label/{labelName}/values
```

### 2.2 Authentication

- Header is **`X-LAST9-API-TOKEN: Bearer <ACCESS_TOKEN>`** — NOT the standard
  `Authorization` header.
- Access tokens expire in **24 hours**.
- Refresh: `POST .../oauth/access_token` with JSON body
  `{"refresh_token": "<token>"}`. Response contains `access_token`,
  possibly a rotated `refresh_token`, and `expires_at`.
- On a 401 **or** a 200 whose body contains `"Authorization token is expired"`,
  refresh the token inline and retry the same request.

### 2.3 Query parameters (on the POST URL, not the body)

`start`, `end` (UTC epoch **seconds** in our usage), `limit` (use 10000),
`direction` (`backward`), `step` (`200ms`), `offset` (pagination),
`index` (e.g. `physical_index:UMServices`), `region` (e.g. `ap-southeast-1`).

### 2.4 Request body — the pipeline MUST be a LIST

```json
{
  "pipeline": [
    {
      "query": { "$and": [ ... ] },
      "type": "filter"
    }
  ]
}
```

Key order inside the stage is `query` then `type`. The top-level `pipeline`
value is always a JSON **array**, even for a single stage.

### 2.5 Valid operators (THE COMPLETE LIST — nothing else exists)

```
$eq  $neq  $contains  $notcontains  $regex  $notregex  $gt  $lt  $gte  $lte
```

- **`$containsWords` DOES NOT EXIST.** Do not use it anywhere. (Earlier attempts
  with it wasted days — it sometimes silently "worked" then failed unpredictably.)
- Each operator is a 2-element array: `["field", "value"]`, e.g.
  `{"$contains": ["Body", "GetEntitlements"]}`.
- The log message field is **`Body`** (capital B). This is confirmed working.

### 2.6 CRITICAL: how to OR many values (the #1 gotcha)

A `$or` block that wraps many separate `$contains`/`$regex` clauses
**silently returns 0 rows** (no error — just empty). Do **not** build
`{"$or": [{"$contains": [...]}, {"$contains": [...]}, ...]}` for many IDs.

**The correct, proven way to match ANY of N IDs is a single `$regex`** with the
IDs joined by `|` (alternation):

```json
{ "$regex": ["Body", "ID-AAA|ID-BBB|ID-CCC"] }
```

Because one giant regex with thousands of IDs is rejected by Last9's pipeline
size limit, **batch the IDs** (~100 per regex) and run one request per batch
against each time window, streaming all results into the same output. ~100 IDs
per batch produces ~5 KB requests, which is safe. Make batch size configurable.

Escape regex metacharacters in each ID but **leave hyphens literal** (hyphens
are only special inside `[...]` character classes, not in alternation). Use a
custom escaper:

```python
import re
def esc(s: str) -> str:
    return re.sub(r'([.^$*+?()\[\]{}|\\])', r'\\\1', s)
```

### 2.7 AND / OR filter semantics to expose in the UI

```
(PHRASE_1 AND PHRASE_2 AND …)        # all required phrases must match
        AND
(ID_1 OR ID_2 OR ID_3 OR …)          # any one ID must match
```

Built as:
```json
{ "$and": [
    {"$contains": ["Body", "phrase 1"]},
    {"$contains": ["Body", "phrase 2"]},
    {"$regex":    ["Body", "id1|id2|id3|…"]}     // the batched ID block
]}
```
Three modes: phrases only, IDs only, or both. If there are no IDs, omit the
regex clause. If there are no phrases, the pipeline is just the regex clause.

### 2.8 Pagination & streaming

- Response shape: `data.data.result` is a list of streams; each stream's
  `values` is a list of `[timestamp, raw_line]`. `result` is `null` when empty.
- Extract the message from each `raw_line` (it may be JSON — try keys
  `message`, `Message`, `Body`, `body`, `msg`; otherwise use the raw string).
- Page until a page returns fewer than `limit` rows; advance `offset += limit`.
- **Never accumulate rows in memory.** Stream each row to the output as it
  arrives (DB, file, or response stream). Production runs exceed millions of rows.

### 2.9 Chunking & checkpoint/resume

- Split the full time range into N-hour chunks (default 1 h) so each request
  stays small.
- After each chunk's rows are durably written, advance a checkpoint
  (next chunk start, rows written so far) atomically.
- On resume, skip completed chunks and append — never re-write headers or
  duplicate data. A kill mid-chunk replays only that chunk (time windows are
  non-overlapping, so no duplicates).

### 2.10 Retry policy

- 5xx / timeouts / connection errors → exponential backoff, up to 10 attempts,
  cap 300 s.
- HTTP 400 → can be transient; retry up to 3 times at a flat 5 s, then fast-fail
  that batch and continue.
- Other 4xx (403/404/429) → fast-fail.
- 401 → refresh token and retry (see 2.2).

### 2.11 Regions

Last9 uses AWS-style region codes. Expose these four with friendly labels:

| Friendly label | Region code      |
| -------------- | ---------------- |
| India          | `ap-south-1`     |
| Virginia       | `us-east-1`      |
| Singapore      | `ap-southeast-1` |
| Frankfurt      | `eu-central-1`   |

Index targets are region-scoped. The index dropdown must be **dependent** on the
selected region (only show indexes saved for that region).

### 2.12 Time handling

- The API takes UTC epoch. Most users think in IST (UTC+5:30). The UI must show
  a clear timezone toggle (IST ↔ UTC) and convert correctly. Display both the
  selected local time and the resolved UTC range before a job runs.

### 2.13 Other learned facts

- Data is unevenly distributed across hours — many ID batches legitimately
  return 0 rows. Empty stretches are normal; show a "scanning…" heartbeat, not
  an error.
- Index format string: `physical_index:<name>` (also `rehydration_index:<name>`
  exists but we use physical).
- Target org for this company: `evergentapse1` (make it configurable, not
  hard-coded — other orgs may be added).

---

## 3. Architecture

Long-running, multi-hour, million-row jobs shared by up to 180 users means this
**cannot** be a single front-end calling Last9 directly. Use a proper
job-queue architecture.

**Recommended stack (use this unless you have a strong reason otherwise):**

- **Frontend:** Next.js (App Router) + TypeScript + Tailwind CSS + shadcn/ui
  components + TanStack Query for server state + Zustand for local UI state.
- **Backend API:** Python **FastAPI** (reuse the proven Last9 logic, which is
  Python). Pydantic models for all request/response validation.
- **Worker:** **Celery** (or RQ/Arq) workers consuming jobs from **Redis**. The
  actual log streaming runs here, not in the web request.
- **Database:** **PostgreSQL** via SQLAlchemy + Alembic migrations.
- **Cache/broker:** **Redis**.
- **Real-time progress:** Server-Sent Events (SSE) from FastAPI to the browser
  (simpler than WebSockets for one-way progress); job progress is also persisted
  to Postgres so a page refresh recovers state.
- **File storage:** generated CSVs written to disk (or S3-compatible storage if
  configured) with signed/expiring download links. Stream large files; never
  load them fully into memory.
- **Auth:** company SSO via OIDC (Auth.js/NextAuth on the frontend, JWT verified
  by FastAPI). If SSO isn't available initially, support email-magic-link or a
  simple admin-provisioned account system, but architect for SSO.
- **Containerization:** Dockerfiles for web, api, worker; a `docker-compose.yml`
  for local dev (postgres + redis + api + worker + web). Production-ready
  (health checks, graceful shutdown, env-based config, no secrets in code).

**Secrets:** Last9 refresh tokens are sensitive. Store them **encrypted at rest**
(e.g. Fernet/AES with a key from env/KMS), never log them, and never return them
to the browser after save (write-only field; show only a masked preview).

---

## 4. Data model (Postgres — adjust as needed)

- `users` — id, email, name, role (`admin` | `member`), created_at.
- `last9_credentials` — id, label, org_slug, encrypted_refresh_token,
  encrypted_access_token (cache), access_token_expires_at, owner/scope
  (shared-team vs personal), created_by, created_at.
- `index_targets` — id, name (e.g. `UMServices`), region_code, full index string
  (`physical_index:UMServices`), description, created_by, created_at.
- `jobs` — id, owner_id, status (`queued|running|paused|completed|failed|canceled`),
  region_code, index_target_id, credential_id, start_epoch, end_epoch,
  chunk_hours, id_batch_size, filter_spec (JSONB: phrases[], ids[], mode),
  rows_written, total_chunks, completed_chunks, current_chunk_start,
  checkpoint (JSONB), output_file_path, error_message, created_at, updated_at,
  started_at, finished_at.
- `job_events` — id, job_id, ts, level, message, rows_delta (for the live feed
  and audit).
- `audit_log` — id, user_id, action, entity, entity_id, metadata JSONB, ts.

---

## 5. Feature specs

### 5.1 New Job wizard (the core flow)

A clean, multi-step (or single well-structured) form:

1. **Credential** — pick a saved Last9 credential (shared or personal).
2. **Region** — dropdown (India / Virginia / Singapore / Frankfurt).
3. **Index** — dropdown **dependent on region**; only indexes saved for that
   region appear. Inline "＋ New index" affordance.
4. **Time range** — a presets dropdown (Last 1h / 6h / 24h / 7d / Custom) **plus**
   a custom range picker. Timezone toggle IST ↔ UTC. Show the resolved UTC range
   and the estimated number of chunks before submitting.
5. **Filter builder** — visual AND/OR builder:
   - "Required phrases" repeater (AND, `$contains`).
   - "Match any of these IDs" — large textarea (one per line) **and** file
     upload (.txt / .csv), with live de-dupe + count + batch-count preview.
   - Mode auto-detected (phrases only / IDs only / both) and shown as a summary.
   - Show the generated pipeline JSON in a collapsible "Advanced / preview" panel
     so power users can verify it.
6. **Options** — chunk hours, ID batch size (sensible defaults: 1 h, 100),
   output filename.
7. **Review & run** — summary card, then submit. The job is queued; the user is
   taken to the live job view.

### 5.2 Job detail / live view

- Big status header (queued/running/etc.) with a progress bar
  (`completed_chunks / total_chunks`) and a live **rows written** counter.
- Live event feed via SSE: per-batch `+N rows` lines and `scanning…` heartbeats,
  exactly mirroring the CLI's clean progress output.
- Throughput (rows/sec) and a rough ETA.
- Controls: **Pause/Resume**, **Cancel**, and **Download CSV** (enabled when
  partial or complete output exists). Resume uses the checkpoint.
- Survives refresh (state from DB) and reconnection (SSE auto-reconnect).

### 5.3 Jobs list / history

- Table of all jobs (filter by me / everyone, status, date). Sortable.
- Each row: who, region, index, time range, rows, status, duration, download.

### 5.4 Credentials manager

- List saved credentials (masked). Add new (label, org slug, refresh token,
  optional initial access token). "Test connection" button that does a tiny
  query to validate. Auto-refresh status indicator (valid / expiring / expired).
- Scope: shared-with-team vs personal. Only admins manage shared ones.

### 5.5 Index manager

- List index targets grouped by region. Create (name + region + description).
  The full index string is derived (`physical_index:<name>`). Edit/delete.

### 5.6 Admin

- User management (roles), audit log viewer, global settings (default org,
  storage location, retention policy for generated CSVs).

---

## 6. Design direction (make it premium)

- **Aesthetic:** calm, dense-but-legible, engineering-tool feel. Reference
  points: Linear, Vercel, Stripe Dashboard, Grafana (modern). Dark mode first,
  with a polished light mode.
- **Color:** a single restrained accent (pick one tasteful brand color, e.g. a
  deep indigo or teal) on a neutral gray scale. No rainbow gradients. Use color
  semantically (success/warn/error/info) and sparingly.
- **Typography:** one clean sans for UI (e.g. Inter or Geist) and a mono
  (e.g. JetBrains Mono / Geist Mono) for IDs, timestamps, JSON previews, log
  lines. Strong typographic hierarchy; generous but disciplined spacing.
- **Components:** shadcn/ui as the base, customized — don't ship the defaults
  untouched. Subtle borders, soft shadows, 8px-grid spacing, rounded-md.
- **Motion:** tasteful, fast (120–200 ms) transitions; skeleton loaders, not
  spinners, where possible. Progress feels alive but not noisy.
- **Empty/loading/error states:** design all three for every view. No raw
  stack traces in the UI.
- **Data display:** monospace for log content; virtualized tables for large
  lists; copy-to-clipboard on IDs and the pipeline JSON.
- **No emoji in the UI chrome.** No "✨ AI-powered" language. It's a serious
  internal tool.
- **Accessibility:** keyboard navigable, focus states, WCAG AA contrast.

---

## 7. Robustness & scale (60–180 users)

- All long work runs in workers, never in the request path.
- Concurrency limits per worker and a global cap; fair queueing so one huge job
  doesn't starve others. Per-user rate limiting on job creation.
- Idempotent, resumable jobs with durable checkpoints (as in §2.9).
- Backpressure-aware streaming writes; bounded memory regardless of row count.
- Structured logging (JSON) with correlation IDs; never log secrets.
- Health/readiness endpoints; graceful worker shutdown that checkpoints first.
- Config entirely via environment variables; `.env.example` documented.
- Tests: unit tests for the Last9 pipeline builder (especially §2.5/2.6),
  token refresh, checkpoint logic, and the regex batching; an integration test
  with the Last9 client mocked.

---

## 8. Build phases (stop after each for my review)

**Phase 1 — Foundation.** Repo scaffolding (monorepo: `/web`, `/api`,
`/worker`, `/infra`), Docker compose for local dev, Postgres + Redis wired up,
base config/secrets handling, health checks. No features yet — just a running
skeleton with the design system, layout shell, nav, dark/light theme, and a
styled empty dashboard so we can judge the look early.

**Phase 2 — Last9 core library.** A well-tested Python module implementing
everything in §2 (token mgmt, pipeline builder with regex batching, streaming
pagination, chunking, checkpoint/resume, retry policy). Unit tests proving the
§2.5/§2.6 gotchas are handled. This is the riskiest part — get it right and
covered by tests before building UI on top.

**Phase 3 — Credentials & Index managers.** Backend CRUD + encryption, the two
management UIs, "test connection", region→index dependent dropdown data.

**Phase 4 — Job engine.** Jobs table, Celery worker running the Phase 2 library,
queue, status lifecycle, checkpoint persistence, file output + download links.

**Phase 5 — New Job wizard + live view.** The full creation flow (§5.1), SSE
progress, pause/resume/cancel, live event feed, jobs history.

**Phase 6 — Admin, audit, polish.** Roles, audit log, settings, retention,
final design pass, empty/error states, accessibility, docs (README + runbook),
production Dockerfiles.

---

## 9. Deliverables

- Clean, documented monorepo with the structure above.
- `docker-compose up` brings the whole thing up locally.
- `README.md` (setup, architecture, env vars) and `RUNBOOK.md` (deploy, scale,
  troubleshoot, rotate secrets).
- Seed script that inserts the four regions and a sample `UMServices` index for
  Singapore so the app is usable immediately.

---

## 10. Start now

Begin with **Phase 1 only**. Propose the exact folder structure and tech
versions, scaffold it, get `docker-compose up` working with the styled shell and
theme, then stop and show me before moving on. Ask me any clarifying questions
about SSO/auth, hosting target, and brand accent color before you start Phase 1.
