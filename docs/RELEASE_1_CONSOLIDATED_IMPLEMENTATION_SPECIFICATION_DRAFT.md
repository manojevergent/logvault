# Release 1 Consolidated Message-Dispatch Implementation Specification

Status: **FROZEN FOR M-01 REVIEW. NOT APPROVED.**
Document state: **FREEZE-1**, 2026-11-14. Content is immutable from this point;
any change requires FREEZE-2 and a new hash. This is not an authorization and
not evidence of one.

Pre-freeze hash (DRAFT-1):
`7C6E2850926856A00D27BEFBCF3BE3CB773DD0067D413A6B97F14CC69124CAE6`.
Frozen hash: recorded in `RELEASE_1_CONSOLIDATED_EXECUTION_PACKAGE.md` section 1.

Adoption (Project Owner decision C-1, 2026-11-14): on A14-01 approval this
document is the authoritative consolidated implementation specification. It
supersedes `RELEASE_1_P1_IMPLEMENTATION_SPECIFICATION.md` for the consolidated
scope; that file is retained unchanged for audit.

| Control | State |
|---|---|
| A14-01 specification approval | **HOLD - not approved** |
| Gate A (P-03) | **NOT GRANTED** |
| Gate B | **NOT GRANTED** |
| D11 FULL / REDUCED | **UNSIGNED** |
| P1 / consolidated implementation | **NOT STARTED** |

This draft does **not** modify `RELEASE_1_P1_IMPLEMENTATION_SPECIFICATION.md` or
`RELEASE_1_P1_IMPLEMENTATION_TEST_SPEC.md`. Both remain on HOLD and both remain
authoritative for schema shape.

On A14-01 approval against this file, this document supersedes the schema-only
P1 specification **for the consolidated message-dispatch scope only**. The
schema contract in section 7 is carried forward unchanged, so an approval of
this draft approves the same six revisions plus the runtime sections.

Approval evidence, when granted, must record: both specification paths, the
commit or version, each file's SHA-256, the D11 scope selected, approver,
reviewer, and date.

---

## 1. Scope and authority

This specification defines one deliverable: a working, reliable, fenced
message-dispatch and job-state-machine implementation.

It consolidates work previously split across the schema-only P1 phase and the
P2/P3/P4/P6/P7/P8 runtime phases. It does not create a new architecture. It
does not authorize implementation. It exists so that A14-01 and P-03 can
approve one scope instead of seven.

Authority order for this deliverable:

1. This specification.
2. `RELEASE_1_GATE_A_CANONICAL_REGISTER.md` for action/evidence governance.
3. `RELEASE_1_CHECKPOINT_RECOVERY_CONTRACT.md` for checkpoint semantics.
4. `LEASE_AND_FENCING.md`, `OUTBOX_AND_DISPATCH.md`,
   `ARTIFACT_PUBLICATION.md`, `JOB_LIFECYCLE.md` for component intent.
5. Existing application code for behavior that this specification does not
   change.

Where this document and a component note disagree, this document wins and the
note must be corrected before approval.

## 2. Component inventory

| ID | Component | Type | Prior phase |
|---|---|---|---|
| R1-C01 | Outbox writer in API write paths | runtime | P6 |
| R1-C02 | Outbox dispatcher | runtime | P6 |
| R1-C03 | Worker claim, ownership, lease increment | runtime | P2 |
| R1-C04 | Fenced write layer | runtime | P2 |
| R1-C05 | Progress-aware heartbeat | runtime | P2 |
| R1-C06 | Lease-expiry reconciler and redispatch | runtime | P2/P6 |
| R1-C07 | Duplicate-dispatch protection | runtime | P2 |
| R1-C08 | Retry, exhaustion, and recovery handling | runtime | P2/P9 |
| R1-C09 | Attempt-scoped artifact paths | runtime | P4 |
| R1-C10 | Atomic artifact publication pointer | runtime | P4/P8 |
| R1-C11 | Strict checkpoint validation | runtime | P4 |
| R1-C12 | Partial-completion reporting | runtime | P2/P3 |
| R1-C13 | Dedicated Celery beat | runtime | P7 |
| R1-C14 | Migrations `0032`, `0032b`, `0033`, `0034` (+ `0035`,`0036` if D11 FULL) | schema | P1 |
| R1-C15 | Migration, integration, and failure-recovery tests | evidence | P1-P8 |

Every component is required. None is an optional enhancement; the set is
interdependent. A partial delivery is not a partial success, because an
unfenced writer or a missing reconciler reintroduces the duplicate-execution
defect the whole scope exists to remove.

## 3. Execution authority model

Non-negotiable invariants. A test exists for each; see the test specification.

| ID | Invariant |
|---|---|
| I-01 | PostgreSQL is the sole execution authority. A Celery message is a hint that work may exist, never proof of ownership. |
| I-02 | No job executes without a row-level claim that atomically increments `lease_token`. |
| I-03 | Every state-changing job write carries a `lease_token` predicate. |
| I-04 | `lease_token` is monotonic per job. It is never reused, never decremented, never reset by retry, resume, or redispatch. |
| I-05 | An outbox row is inserted in the same transaction as the `jobs` row it describes. |
| I-06 | Dispatch never precedes commit. No broker call is made inside an uncommitted transaction. |
| I-07 | At most one worker holds a valid lease for a job at any instant. |
| I-08 | Heartbeat renewal requires progress. Liveness alone does not extend a lease. |
| I-09 | Artifact publication commits through one guarded DB pointer update; a file on disk or an object in S3 is not published until that update commits. |
| I-10 | A checkpoint is used only when its identity matches the current job, specification, and attempt lineage. |
| I-11 | Terminal states are absorbing and lease-guarded. A late writer cannot reopen or overwrite a terminal row. |
| I-12 | Transport loss never loses work. The database can reconstitute any missing message. |

## 4. Job state machine

Persisted statuses remain the existing six values. No new job status is
introduced; intermediate phases are derived from columns and are not stored as
`status`.

| Persisted status | Meaning |
|---|---|
| `queued` | Work is owed. No valid lease. |
| `running` | A lease is or was held. Valid iff `lease_expires_at > now()`. |
| `paused` | User-intent stop. Resumable. No valid lease. |
| `completed` | Terminal success or partial success. Absorbing. |
| `failed` | Terminal failure. Absorbing. |
| `canceled` | Terminal cancel. Absorbing. Dominates completion. |

Guarded transitions:

| # | From | To | Guard | Writer |
|---|---|---|---|---|
| T1 | (new) | `queued` | insert committed with outbox row | API |
| T2 | `queued` | `running` | `cancel_requested_at IS NULL` and no valid lease; increments `lease_token` | worker claim |
| T3 | `running` (expired lease) | `running` | reconciler increments `lease_token`, clears owner | reconciler |
| T4 | `running` | `paused` | lease valid, `pause_requested_at` set | worker |
| T5 | `paused` | `queued` | user resume; increments `lease_token`; outbox row upserted | API |
| T6 | `queued`/`running`/`paused` | `canceled` | `cancel_requested_at` set, writer holds valid lease or reconciler owns the decision | worker or reconciler |
| T7 | `running` | `completed` | valid lease, artifact publication committed, gap fields consistent | worker |
| T8 | `running` | `failed` | valid lease, or retry exhaustion decided by reconciler | worker or reconciler |
| T9 | any terminal | any | (none) | no writer |

Derived phases used only for reporting, never stored: `dispatch_pending`
(outbox pending), `stale` (running with expired lease), `finalizing` (lease
valid, publication in flight).

## 5. Outbox state machine

Table `job_dispatch_outbox`, one row per `(job_id, task_name)`.

| Status | Meaning |
|---|---|
| `pending` | Dispatch is owed and not yet confirmed. |
| `published` | Broker accepted the message. |
| `dead` | Attempt cap reached. Requires operator action. |

Transitions:

| From | To | Guard |
|---|---|---|
| `pending` | `published` | publish call returned success; update guarded by `locked_by` ownership |
| `pending` | `pending` | publish failed; `attempts += 1`; `next_attempt_at = now() + backoff(attempts)` |
| `pending` | `dead` | `attempts >= max_attempts` |
| `published` | `pending` | reconciliation reopens dispatch (lease expired, no valid lease, job non-terminal) |
| `dead` | `pending` | explicit operator replay only |

Backoff: exponential from 5s, factor 2, cap 300s, jitter +/-20%, `max_attempts`
default 12. The cap is configurable; the default is part of this specification.

Reopen rule: a reconciler may reset `published` to `pending` only when the job
is non-terminal **and** has no valid lease **and** at least one lease TTL has
elapsed since `published_at`. This prevents a publish from racing a healthy
worker.

## 6. Schedule-window ledger (D11 FULL only)

If D11 REDUCED is signed, section 6, revision `0035`, and every statement
referring to `schedule_windows`, `schedule_window_id`, or `attempt_no` are
**out of scope** and must be removed from the approved version of this
document. The beat component R1-C13 and the reconciler R1-C06 remain in scope.

If D11 FULL is signed, the ledger is the schedule-side deduplication authority:
one row per `(schedule_id, window_key)`, states `pending`, `running`,
`completed`, `failed`, `skipped`. A schedule tick creates at most one job per
window, guarded by the unique constraint, never by a `last_run_at` comparison
alone.

## 7. Schema contract

Carried forward unchanged from `RELEASE_1_P1_IMPLEMENTATION_SPECIFICATION.md`
sections 2 to 9. Summary of what this approval covers:

| Revision | Content |
|---|---|
| `0032` | `jobs`: `owner_id`, `lease_token`, `lease_expires_at`, `heartbeat_at`, `progress_at`, `pause_requested_at`, `cancel_requested_at`, `completion_state`, `gap_count`, `gap_reason`, `retry_of`. No indexes. |
| `0032b` | `CREATE INDEX CONCURRENTLY`: `ix_jobs_lease`, `ix_jobs_owner`, `ix_jobs_progress`. Autocommit blocks only. |
| `0033` | `jobs`: `store_path`, `spec_fingerprint`, `checkpoint_version`. No indexes. |
| `0034` | `job_dispatch_outbox` table, unique `(job_id, task_name)`, `ix_job_dispatch_due`, `ix_job_dispatch_locked`. |
| `0035` | `schedule_windows` table, `jobs.schedule_window_id`, `jobs.attempt_no`. D11 FULL only. |
| `0036` | `jobs`: `s3_attempt_token`, `s3_uploading_at`, `s3_published_attempt`, `s3_manifest_uri`. D11 FULL only. |

Retained constraints from the current specification:

- `transaction_per_migration=True` before any P1 revision.
- One transaction per non-concurrent revision; one autocommit block per
  concurrent index.
- No `alembic upgrade head` in the migration window.
- No deferred indexes: no `ix_jobs_retry_of`, `ix_jobs_schedule_window_id`,
  `ix_jobs_s3_uploading`, no `0035b`, no `0036b`.
- No CHECK constraints; `0037` remains P9.
- No data backfill. Existing rows receive column defaults.
- No P2-excluded security, credential, or deployment schema.

## 8. API write-path contract (R1-C01)

Every code path that creates or resumes work must, in one transaction:

1. insert or update the `jobs` row;
2. upsert `job_dispatch_outbox(job_id, task_name='logvault.run_job')` to
   `pending` with `next_attempt_at = now()`;
3. commit;

and must **not** call the broker directly in that transaction.

Paths in scope, identified from the current code:

| Path | Location |
|---|---|
| single job create | `api/app/routers/jobs.py` create handler, currently `dispatch_job(job.id)` at line ~326 |
| batch create | `api/app/routers/jobs.py` batch handler, currently line ~478 |
| rollup create | `api/app/routers/jobs.py` rollup handler, currently line ~654 |
| resume | `api/app/routers/jobs.py` resume handler, currently line ~848 |
| retry | `api/app/routers/jobs.py` retry handler, currently line ~1002 |
| group dispatch | `api/app/routers/groups.py` |
| scheduler window creation | `worker/app/scheduler.py` (D11 FULL ledger path) |

`api/app/tasks_client.py` loses its role as the authoritative dispatch entry
point. It is retained during the compatibility window as a legacy direct-send
used only by the dispatcher fallback in phase R1-P8.

Outbox upsert must be idempotent: a second create/resume for the same job and
task must not produce a second row.

## 9. Dispatcher contract (R1-C02)

Runs as a periodic worker task, not as part of an API request.

Tick algorithm:

1. Claim a bounded batch: `SELECT ... WHERE status='pending' AND
   next_attempt_at <= now() ORDER BY next_attempt_at FOR UPDATE SKIP LOCKED
   LIMIT :batch`, then `UPDATE ... SET locked_by=:owner, locked_until=now()+:lease`.
2. For each row, publish outside the transaction.
3. On success: `UPDATE ... SET status='published', published_at=now(),
   last_error=NULL WHERE id=:id AND locked_by=:owner`.
4. On failure: `attempts += 1`, `next_attempt_at = now() + backoff`,
   `last_error` set, `locked_by=NULL`.
5. Expired `locked_until` rows are reclaimable by the next tick without
   operator action.

Constraints:

- `batch` default 100, configurable.
- Publish lock lease default 60s.
- Exactly one successful publish per `(job_id, task_name)` in the normal path;
  duplicate publishes are tolerated because the worker claim is idempotent, but
  must be counted and alertable.
- Dispatcher must never publish a row whose job is terminal.

## 10. Worker claim and fence contract (R1-C03, R1-C04)

Claim is one conditional statement returning the new token:

```sql
UPDATE jobs
   SET status = 'running',
       owner_id = :owner,
       lease_token = lease_token + 1,
       lease_expires_at = now() + :ttl,
       heartbeat_at = now(),
       progress_at = now()
 WHERE id = :job_id
   AND cancel_requested_at IS NULL
   AND ( status = 'queued'
         OR ( status = 'running'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at < now() ) )
RETURNING lease_token;
```

Zero rows means no ownership. The task returns without executing. This is the
sole defense against duplicate delivery; it must not be short-circuited by a
cache, an in-memory set, or a Celery `task_id` match.

Fenced write layer: a single helper is the only permitted way to mutate a job.

```text
fenced_update(job_id, token, **values) ->
  UPDATE jobs SET ... WHERE id=:job_id AND lease_token=:token
  RETURNING id
```

- Empty result means the lease was superseded. The caller must abort the job,
  emit a `lease_lost` event, and must not publish artifacts, must not write
  terminal status, and must not delete attempt files it no longer owns.
- Terminal writes additionally require `owner_id = :owner`.
- `db.update_job` in `worker/app/db.py` (currently unguarded, line ~185) is
  removed or made private to non-job tables. Unguarded job updates become a
  test failure.

Owner identity: `owner_id` is `<hostname>:<pid>:<celery-task-id>` truncated to
128 chars. It is diagnostic; correctness rests on `lease_token`.

Lease TTL default 60s, worker-side heartbeat interval 10s.

## 11. Heartbeat and progress contract (R1-C05)

Two clocks, deliberately separate:

- `heartbeat_at`: proof of a live process. Renewed every interval.
- `progress_at`: proof of forward work. Renewed only when work advances.

Renewal rule:

```text
renew IF progress_at > last_renewed_progress_at
  THEN SET heartbeat_at=now(), lease_expires_at=now()+ttl, last_renewed_progress_at=progress_at
  ELSE SET heartbeat_at=now()      -- visibility only, lease NOT extended
```

Consequence, stated explicitly because it is the point of the contract: a
worker that is alive but making no progress **loses its lease** and is
redispatched. This is intended stalled-job detection, not a defect.

Therefore the runner must emit progress at bounded intervals in every long
phase:

| Emission point | Column |
|---|---|
| chunk claimed | `progress_at` |
| every N records or every M seconds within a chunk | `progress_at` |
| chunk complete + checkpoint committed | `progress_at` |
| phase change (extract -> aggregate -> package -> upload) | `progress_at` |

Defaults: N = 50,000 records, M = 15s, ttl 60s, interval 10s. N and M are
constants in this specification; changing them requires a spec amendment.

Heartbeat must run on a separate thread or a Celery-side scheduler independent
of the extraction loop, otherwise a blocked loop cannot report its own stall.

## 12. Lease-expiry reconciler (R1-C06)

Database-driven. Not event-driven. Not dependent on any prior message.

Tick algorithm:

1. Select expired: `status='running' AND lease_expires_at < now() LIMIT :batch
   FOR UPDATE SKIP LOCKED`.
2. Per row, decide in this order:
   - `cancel_requested_at IS NOT NULL` -> `canceled`, terminal, no redispatch.
   - `pause_requested_at IS NOT NULL` -> `paused`, no redispatch.
   - outbox attempts exhausted -> `failed` with reason `retry_exhausted`.
   - otherwise -> `lease_token = lease_token + 1`, `owner_id = NULL`,
     `lease_expires_at = NULL`, status stays `running` (derived `stale`), and
     the outbox row is reset to `pending`.
3. Emit an event per decision.

The token increment in step 2 is what fences the dead worker immediately,
before any new worker claims the job. This is the property that makes the
reconciler safe to run concurrently with a slow-but-alive worker: the slow
worker's next fenced write fails and it stops.

Retry accounting without `attempt_no` (D11 REDUCED): exhaustion is measured on
`job_dispatch_outbox.attempts` for the same `(job_id, task_name)`, because the
unique constraint guarantees one row per job. With D11 FULL, `attempt_no` is
also incremented and recorded for lineage.

Defaults: `batch` 50, tick interval 15s, max redispatches 6.

## 13. Attempt artifacts and publication (R1-C09, R1-C10)

Attempt identity is `(job_id, lease_token)`. The token is already monotonic, so
it doubles as the attempt counter with no extra column.

Local layout:

```text
<storage_dir>/exports/job_<id>/a<lease_token>/<artifact>
<storage_dir>/stores/job_<id>/a<lease_token>/<store dir>
```

Rules:

- The attempt directory is created exclusively. If it already exists, the
  worker must not append to it; it takes ownership only via a successful claim,
  which by construction implies a new token.
- No worker writes to another attempt's directory.
- Canonical legacy paths remain readable for old jobs and are never reused for
  new attempts.

S3 layout: `<prefix>/job_<id>/a<lease_token>/<artifact>`; manifest at
`<prefix>/job_<id>/a<lease_token>/manifest.json`.

Publication is a single guarded update, and it is the commit point:

```sql
UPDATE jobs
   SET output_file_path=:out, summary_file_path=:sum,
       counts_file_path=:cnt, unmatched_file_path=:unm,
       s3_manifest_uri=:manifest, s3_published_attempt=:s3token,
       completion_state=:state, gap_count=:gaps, gap_reason=:reason,
       status=:terminal, completed_at=now()
 WHERE id=:job_id AND lease_token=:token AND owner_id=:owner
RETURNING id;
```

Failure semantics:

| Situation | Result |
|---|---|
| upload fails | no pointer update; job fails or retries; attempt files quarantined |
| upload succeeds, pointer update fails (lease lost) | object exists but is unpublished; reconciler redispatches; new attempt publishes its own pointer |
| pointer update succeeds | published, immutable; later failures cannot unpublish |
| cleanup runs | published attempt never deleted; unpublished attempts eligible after retention |

## 14. Strict checkpoint contract (R1-C11)

A checkpoint is trusted only when all of these hold:

| Check | Reject action |
|---|---|
| checkpoint file parses and matches `checkpoint_version` | restart at chunk 0 |
| `spec_fingerprint` equals the current job fingerprint | restart at chunk 0 |
| `completed_chunks > 0` | restart at chunk 0 |
| recorded attempt key matches the attempt directory being written | restart in a fresh attempt |
| artifact file exists and its size is at least the recorded size | restart at chunk 0 |
| last completed chunk key matches the recorded sequence | restart at chunk 0 |

Additional rules:

- Checkpoint writes are atomic: write temp in the same directory, `fsync` file,
  `fsync` directory, `rename` into place. A checkpoint that is not the product
  of a completed atomic write is invalid by definition.
- `completed_chunks = 0` is never resumable.
- A checkpoint never survives a spec fingerprint change. On mismatch the job
  restarts rather than merging incompatible output.
- Resume appends only to the file the checkpoint names, and only after the
  identity checks pass.
- Checkpoint lineage is attempt-scoped: an attempt may resume only its own
  prior checkpoint within the same lease lineage.

## 15. Partial-completion contract (R1-C12)

- `completion_state` in `unknown | complete | partial`.
- `complete` requires `gap_count = 0` and every declared window closed.
- `partial` requires `gap_count > 0` and a non-empty `gap_reason`.
- Both are written only in the terminal guarded update.
- A partial job is visible, downloadable, and clearly labeled. It must never
  render as a clean success in API responses or UI.
- `unknown` is the default and is not a user-visible success state.

## 16. Celery and beat contract (R1-C13)

| Setting | Requirement |
|---|---|
| `acks_late` | `True` (unchanged) |
| `reject_on_worker_lost` | `True` (unchanged) |
| `worker_prefetch_multiplier` | `1` |
| visibility timeout | greater than the lease TTL, explicitly configured |
| soft/hard time limits | set above the longest legitimate chunk, documented |
| beat | dedicated process: `celery -A app.celery_app beat` |
| `-B` | removed from all worker start commands and deployment files |
| beat singleton | Redis lock `logvault:beat:lock`, TTL 2x tick, refreshed each tick |
| task-level overlap guard | DB advisory lock per periodic task |

`worker/app/celery_app.py` currently embeds `-B`; that must be removed for the
whole deployment surface, not only for local development.

## 17. Phase gates

Each phase is an internal gate inside the single approved scope. No phase may
start before its predecessor's exit criteria are recorded.

| Phase | Work | Exit criteria |
|---|---|---|
| R1-P0 | S-00 verification, branch/worktree, PG16 | isolation recorded |
| R1-P1 | `env.py` TPM; `0032`, `0032b`, `0033`, `0034` (+`0035`,`0036` if FULL) | T-P1-001..014 applied and passing |
| R1-P2 | model mirrors, constants, fenced-write helper | parity and inertness tests pass |
| R1-P3 | outbox writer + dispatcher | outbox tests pass, no direct API dispatch remains |
| R1-P4 | claim, fence, ownership | duplicate claim and stale-write tests pass |
| R1-P5 | heartbeat and progress | heartbeat tests pass |
| R1-P6 | reconciler and redispatch | expiry and exhaustion tests pass |
| R1-P7 | attempt artifacts and publication | artifact tests pass |
| R1-P8 | strict checkpoint | checkpoint tests pass |
| R1-P9 | partial completion, beat, legacy drain | completion, beat, compatibility tests pass |

## 18. Backward compatibility

| Stage | Schema | API | Worker | Safety property |
|---|---|---|---|---|
| A | migrated | old | old | additive schema; no reads; reversible |
| B | migrated | new writes outbox and legacy-sends | old | either path works; duplicate tolerated by claim |
| C | migrated | new | new claims with tokens | old workers ignore tokens but cannot outlive the drain window |
| D | migrated | new | new | dispatcher authoritative; legacy direct send removed |

Rules:

- Old API must operate against the migrated schema with no response change.
- Old worker must operate against the migrated schema (T-R1-080).
- During stage C, a healthy old worker is never "stolen": reconciliation
  requires an expired lease, and an old worker holds no lease, so the job must
  be drained before its lease semantics are enforced. The drain window is a
  named, recorded step, not an assumption.
- Absent token, absent lease, and absent outbox row are all tolerated inputs
  during A and B.
- Rollback from B to A is possible because nothing has read the new state.

## 19. Rollback (isolated engineering environment only)

| Scope | Rollback |
|---|---|
| migrations | downgrade `0032b` blocks and `0034`/`0033`/`0032` in reverse order; `0036`/`0035` first if present |
| dispatcher | stop the task; drain `pending` rows; revert API write path |
| claim/fence | stop new workers; restore unguarded update; keep columns |
| reconciler | disable task; rows are inert |
| artifacts | revert path selection; keep published pointers; quarantine attempt dirs |
| checkpoint | revert validation; old checkpoints remain readable |
| beat | restart embedded beat; stop dedicated beat |

No rollback is authorized against production. Gate B owns that decision.

## 20. Explicitly excluded

- Any P2-excluded security, credential, or deployment change.
- Any new dependency.
- Any router read of the new state beyond partial-completion labeling.
- Any change to `JobOut` field semantics.
- Any production migration, deployment, or data change.
- Any schema beyond the six named revisions.

## 21. Open questions to close before A14-01

1. D11 scope: FULL or REDUCED. Determines `0035`, `0036`, and section 6.
2. Exact filenames for runtime modules: `worker/app/lease.py`,
   `heartbeat.py`, `outbox.py`, `reconciler.py`, `attempt_paths.py`.
3. TTL and interval constants: lease 60s, heartbeat 10s, reconciler 15s,
   progress 50k records / 15s. Confirm or amend.
4. Max redispatches (6) and outbox `max_attempts` (12). Confirm.
5. Beat lock backend and advisory-lock keys.
6. Whether partial-completion labeling requires an API/UI change in this scope
   or a follow-up; this document assumes API-only labeling.
7. Confirmation that removing unguarded `db.update_job` usage for job rows does
   not break an out-of-scope caller.
8. Whether the compatibility drain window is enumerated per environment.

## 22. Migration bodies (review copy)

This section exists so M-01 reviews real DDL instead of prose. **No migration
file has been created.** The code below is inside a Markdown document; nothing
imports it, nothing runs it.

Style matches `0031_extraction_groups.py`: `from __future__ import
annotations`, `import sqlalchemy as sa`, `from alembic import op`, string
revision IDs, `sa.text("now()")` for timestamps.

### 22.1 `api/migrations/env.py` - the only edit to an existing file

In `run_migrations_online` only. Offline mode is unchanged.

```python
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            transaction_per_migration=True,
        )
```

Consequence that must be reviewed: with `transaction_per_migration=True` each
revision owns its transaction, so the outer `context.begin_transaction()` no
longer wraps the whole run. A failing revision rolls back alone. Without this
flag, a later `autocommit_block` would commit preceding revisions implicitly.

### 22.2 Shared helpers for concurrent index revisions

Placed in `0032b_jobs_lease_indexes.py`. `CREATE INDEX CONCURRENTLY` cannot run
inside a transaction block, so each build sits in its own `autocommit_block`.
`IF NOT EXISTS` is deliberately **not** used for creation: a leftover invalid
index would otherwise satisfy the name check and be silently accepted.

```python
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0032b"
down_revision = "0032"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_jobs_lease", ("status", "lease_expires_at"), "lease_expires_at IS NOT NULL"),
    ("ix_jobs_owner", ("owner_id",), "owner_id IS NOT NULL"),
    ("ix_jobs_progress", ("status", "progress_at"), "progress_at IS NOT NULL"),
)


def _index_is_valid(bind, name: str) -> bool:
    return bool(
        bind.execute(
            text(
                "SELECT i.indisvalid "
                "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE c.relname = :name"
            ),
            {"name": name},
        ).scalar()
    )


def _drop_if_present(bind, name: str) -> None:
    if bind.execute(text("SELECT to_regclass(:n)"), {"n": f"public.{name}"}).scalar():
        bind.execute(sa.text(f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"'))


def _ensure(bind, name: str, columns: tuple[str, ...], predicate: str) -> None:
    if _index_is_valid(bind, name):
        return
    _drop_if_present(bind, name)
    op.create_index(
        name,
        "jobs",
        list(columns),
        unique=False,
        postgresql_concurrently=True,
        postgresql_where=sa.text(predicate),
    )
    if not _index_is_valid(bind, name):
        raise RuntimeError(f"{name} did not become valid")
```

`upgrade()` calls `_ensure` once per index, each wrapped in its own block:

```python
def upgrade() -> None:
    for name, columns, predicate in INDEXES:
        with op.get_context().autocommit_block():
            _ensure(op.get_bind(), name, columns, predicate)


def downgrade() -> None:
    for name, _columns, _predicate in reversed(INDEXES):
        with op.get_context().autocommit_block():
            _drop_if_present(op.get_bind(), name)
```

Review note: recovery from an invalid index is the `_drop_if_present` path, so
re-running the revision is always safe. A manual operator recovery is
`DROP INDEX CONCURRENTLY "<name>";` then re-run `0032b`.

### 22.3 `0032_job_ownership_and_completion.py`

Eleven columns, no indexes. `down_revision = "0031"`.

```python
"""Job ownership, lease, progress, and completion state."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

COLUMNS = (
    sa.Column("owner_id", sa.String(length=128), nullable=True),
    sa.Column("lease_token", sa.BigInteger(), nullable=False, server_default="0"),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("progress_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("pause_requested_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("completion_state", sa.String(length=16), nullable=False, server_default="unknown"),
    sa.Column("gap_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("gap_reason", sa.Text(), nullable=True),
    sa.Column("retry_of", sa.Integer(), nullable=True),
)


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column("jobs", column)


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column("jobs", column.name)
```

Review notes: `server_default` is required on the three `NOT NULL` columns so
existing rows are valid without a backfill (PostgreSQL 11+ does this as metadata
only). No `ix_jobs_retry_of`; that is deferred to the retry-lineage phase.

### 22.4 `0033_job_artifact_paths.py`

Three columns, no indexes. `down_revision = "0032b"`.

```python
revision = "0033"
down_revision = "0032b"

COLUMNS = (
    sa.Column("store_path", sa.Text(), nullable=True),
    sa.Column("spec_fingerprint", sa.String(length=64), nullable=True),
    sa.Column("checkpoint_version", sa.Integer(), nullable=False, server_default="1"),
)
```

`upgrade`/`downgrade` are the same add/drop loop as 22.3. The four existing
artifact pointer columns are untouched.

### 22.5 `0034_job_dispatch_outbox.py`

New table. New-table indexes are **not** concurrent and must not appear inside
an `autocommit_block`; an empty table takes no meaningful lock.

```python
revision = "0034"
down_revision = "0033"


def upgrade() -> None:
    op.create_table(
        "job_dispatch_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("task_name", sa.String(length=80), nullable=False,
                  server_default="logvault.run_job"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("job_id", "task_name", name="uq_job_dispatch_outbox_job_task"),
    )
    op.create_index("ix_job_dispatch_due", "job_dispatch_outbox",
                    ["status", "next_attempt_at"])
    op.create_index("ix_job_dispatch_locked", "job_dispatch_outbox", ["locked_until"],
                    postgresql_where=sa.text("locked_until IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_job_dispatch_locked", table_name="job_dispatch_outbox")
    op.drop_index("ix_job_dispatch_due", table_name="job_dispatch_outbox")
    op.drop_table("job_dispatch_outbox")
```

Review notes: no foreign key to `jobs`, per the specification, so job deletion
is never coupled to dispatch. `sa.JSON` (not JSONB) preserves the portability
decision. No rows are inserted by the migration.

### 22.6 `0035_schedule_windows.py` - D11 FULL only

Not created if REDUCED is signed. `down_revision = "0034"`.

```python
revision = "0035"
down_revision = "0034"


def upgrade() -> None:
    op.create_table(
        "schedule_windows",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("schedule_id", sa.Integer(), nullable=False),
        sa.Column("window_key", sa.String(length=80), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_epoch", sa.BigInteger(), nullable=False),
        sa.Column("end_epoch", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("completion_state", sa.String(length=16), nullable=False,
                  server_default="unknown"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("current_job_id", sa.Integer(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("config_snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("schedule_id", "window_key", name="uq_schedule_windows_window"),
    )
    op.create_index("ix_schedule_windows_due", "schedule_windows",
                    ["status", "scheduled_for"])
    op.create_index("ix_schedule_windows_schedule", "schedule_windows",
                    ["schedule_id", "scheduled_for"])
    op.add_column("jobs", sa.Column("schedule_window_id", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("attempt_no", sa.Integer(), nullable=False,
                                    server_default="1"))


def downgrade() -> None:
    op.drop_column("jobs", "attempt_no")
    op.drop_column("jobs", "schedule_window_id")
    op.drop_index("ix_schedule_windows_schedule", table_name="schedule_windows")
    op.drop_index("ix_schedule_windows_due", table_name="schedule_windows")
    op.drop_table("schedule_windows")
```

Review note: no `jobs` indexes here. `ix_jobs_schedule_window_id`,
`uq_jobs_schedule_attempt`, and `uq_jobs_schedule_active` are deferred to the
window-enforcement phase, where their query shapes exist.

### 22.7 `0036_s3_attempt_publication.py` - D11 FULL only

`down_revision = "0035"`. Four columns, no index.

```python
revision = "0036"
down_revision = "0035"

COLUMNS = (
    sa.Column("s3_attempt_token", sa.BigInteger(), nullable=False, server_default="0"),
    sa.Column("s3_uploading_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("s3_published_attempt", sa.BigInteger(), nullable=True),
    sa.Column("s3_manifest_uri", sa.Text(), nullable=True),
)
```

Same add/drop loop. `ix_jobs_s3_uploading` is deferred to the S3-retry phase.

### 22.8 Application order

```text
0032 (tx) -> 0032b (3 autocommit blocks) -> 0033 (tx)
     -> 0034 (tx) -> [0035 (tx) -> 0036 (tx)  only if FULL]
```

Never `alembic upgrade head` in this window. Downgrade is the exact reverse,
with `0032b` last among the indexed revisions and every index drop inside an
`autocommit_block`.

### 22.9 Deliberately absent

No CHECK constraints, no backfill, no data migration, no trigger, no
`0035b`/`0036b`, no deferred index, no change to `JobOut`, no P2-excluded
security or credential schema, and no row inserted into any new table.

## 23. Stop condition

This is a draft specification. It authorizes nothing. Do not create migrations,
branches, environments, or code from it until A14-01 is approved and Gate A is
granted.
