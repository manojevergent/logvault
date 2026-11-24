# Central State Transitions

Status: architecture proposal. Not implemented. Companion to
[`JOB_LIFECYCLE.md`](./JOB_LIFECYCLE.md) and
[`STATE_MACHINES.md`](./STATE_MACHINES.md).

This document is the single place to look up **what may transition to what**,
**which guard makes it safe**, and **which layer owns it**. The goal is that a
new state or transition is a one-table change plus a contract test, not a
14-file hunt.

Legend: **[V]** verified current behavior, **[R]** recommendation, **[A]**
assumption.

## 1. Transition registry format

Every row has:

- **ID** - stable identifier for tests and code comments.
- **From -> To** - states.
- **Trigger** - the event or call.
- **Guard** - the predicate that must be true.
- **Owner** - the only layer allowed to perform it.
- **Side effects** - writes that must be atomic with the transition.
- **On failure** - what the caller sees and what state remains.

The registry is normative for the canonical model. The current code differs in
the places marked in section 3.

## 2. Job execution transitions

| ID | From -> To | Trigger | Guard | Owner | Side effects |
|---|---|---|---|---|---|
| J1 | - -> queued | create/import/batch/group/schedule/rollup | validation passes | API/beat | insert, audit, dispatch |
| J2 | queued -> running | worker claim | `status='queued'` OR (`status='running'` AND `heartbeat_at < cutoff` AND redelivered) | worker | `owner_id`, `lease_token+1`, `started_at`, clear error, event |
| J3 | running -> running | heartbeat | owner + token match | worker | `heartbeat_at`, event |
| J4 | queued/running -> paused | pause request | `status IN ('queued','running')` | API then worker | `pause_requested_at`; worker writes `paused` at safe boundary |
| J5 | paused -> queued | resume | `status='paused'` | API | clear pause request, dispatch |
| J6 | queued -> canceled | cancel | `status='queued'` | API | `cancel_requested_at`, `finished_at`, completion state |
| J7 | running -> canceled | cancel observed | owner + token, `cancel_requested_at` set | worker | finalize partial artifact, `finished_at` |
| J8 | running -> completed | loop ends | owner + token, no cancel request | worker | `completion_state`, artifacts, `finished_at` |
| J9 | running -> failed | exception | owner + token | worker | `error_message`, `finished_at`, alert |
| J10 | running -> failed | reaper | `status='running'` AND heartbeat older than threshold | beat | `lease_token+1`, `error_message`, `finished_at`, alert |
| J11 | paused -> canceled | cancel | `status='paused'` | API | `finished_at`, keep checkpoint/artifact |

### 2.1 Current deviations

| ID | Current behavior | Evidence | Risk |
|---|---|---|---|
| J2 | Claim is conditional, but only by status + event age; no owner/token | `db.py:210-230` | Old worker can continue after reclaim |
| J4 | API writes `paused` immediately; worker acknowledges later | `jobs.py:834-837`; `runner.py:647-652` | Resume can race the old worker |
| J6/J7 | Cancel writes `canceled` immediately; worker finalizer writes `completed` unconditionally | `jobs.py:858-866`; `runner.py:830-831` | Cancel lost; job reappears completed |
| J8 | Completion write is unconditional | `runner.py:830-895` | Completion after cancel/fence |
| J10 | Reaper fails unconditionally; no token bump | `scheduler.py:238-248` | Late worker can overwrite failed |
| J11 | No `finished_at` on API cancel | `jobs.py:858-866` | Never cleaned by retention |
| J1 | Commit then publish outside a transaction; no outbox | `jobs.py:324-327` | Orphaned queued jobs on broker failure |

## 3. Worker lease transitions

| ID | From -> To | Trigger | Guard | Owner |
|---|---|---|---|---|
| L1 | unclaimed -> owned | first delivery | `status='queued'` | worker |
| L2 | owned -> owned | heartbeat | owner/token match | worker |
| L3 | owned -> reclaimable | heartbeat older than `stale_reclaim_minutes` | row still `running` | clock / beat |
| L4 | reclaimable -> owned | redelivery | `redelivered=True` AND heartbeat cutoff | new worker, token+1 |
| L5 | owned -> fenced | any write with stale token | `lease_token != current` | database (0 rows) |
| L6 | owned -> failed | reaper | heartbeat older than `stale_job_minutes` | beat, token+1 |

Rules:

- `L4` must increment `lease_token`.
- `L5` must abort the worker without a write. It is not an error to report to
  the user; it is a normal "I no longer own this" exit.
- `L3` is not a state change by itself; it is a predicate.
- The reaper (`L6`) and a reclaim (`L4`) must not both win. The conditional
  update serializes them.

## 4. Checkpoint transitions

| ID | From -> To | Trigger | Guard | Owner |
|---|---|---|---|---|
| C1 | no checkpoint -> mid-range | first chunk complete | owner/token, chunk durable | worker |
| C2 | mid-range -> next chunk | chunk complete | owner/token | worker |
| C3 | mid-range -> end | `next_chunk_start >= end_epoch` | owner/token | worker |
| C4 | mid-range -> mid-range | pause/cancel observed | owner/token | worker |
| C5 | mid-range -> mid-range | reclaim/resume | new token, same row | new worker |
| C6 | any -> fresh | retry creates new row | original terminal | API |

Rules:

- The checkpoint write and the chunk event are one transaction **[V]**
  (`runner.py:626-630`).
- The checkpoint index is the aggregation idempotency key
  (`completed_chunks - 1`) **[V]** (`runner.py:619`).
- `C4` must persist the last durable chunk, not the in-flight row.
- `C6` is the retry semantic decision. Current code does not copy the
  checkpoint **[V]** (`jobs.py:975-996`).

## 5. Completeness transitions

| ID | From -> To | Trigger | Guard | Owner |
|---|---|---|---|---|
| K1 | unknown -> complete | full run ends | covered, no skipped batches, rollup sources usable | worker |
| K2 | unknown -> partial | full run ends with gaps | skipped batches or rollup skips | worker |
| K3 | unknown -> unknown | failure/reap | no reliable coverage | worker/beat |
| K4 | partial -> complete | not allowed on the same row | - | - |

Rules:

- Completeness is set once, in the terminal write.
- A retry is a new row, so `K4` is intentionally forbidden.
- A preview is not `partial` by default; `is_preview` is the discriminator
  **[R]**.
- Do not parse `error_message` in new code.

## 6. Schedule transitions

| ID | From -> To | Trigger | Guard | Owner |
|---|---|---|---|---|
| S1 | disabled -> enabled | toggle | - | API |
| S2 | enabled -> disabled | toggle | - | API |
| S3 | enabled -> owed | beat | owed windows non-empty | beat |
| S4 | owed -> inserted | beat | window not already covered | beat |
| S5 | inserted -> dispatched | beat | broker accepts | beat |
| S6 | dispatched -> up-to-date | commit | `last_run_at=now` | beat |
| S7 | enabled -> backfilling | beat | >1 owed window | beat |
| S8 | covered -> owed | manual retry / re-enable | explicit operator action | API |

Rules:

- `S4` must be atomic with a unique key on `(created_by, start_epoch)` for
  schedule owners **[R]**. Current check-then-insert is not atomic **[V]**
  (`scheduler.py:94-108`).
- `S4` should treat only `completed` as covered for retry purposes, or record
  a window row with status. Current code treats any status as covered
  **[V]**, so a failed day is never re-run automatically.
- `S6` happens after insert, before dispatch **[V]**
  (`scheduler.py:175-188`). Keep `last_run_at` as a dispatch cursor and derive
  success from jobs **[R]**.
- `S7` is capped at 14 days **[V]** (`scheduler.py:27`).
- `S8` is manual today: retry the failed job. A schedule-level "retry window"
  does not exist.

### 6.1 Schedule state that should stay derived

| State | Derivation | Persist? |
|---|---|---|
| `missed` | enabled + expected daily + no successful run in cadence/36 h | no |
| `pending` | enabled + expected daily + today + no run | no |
| `off` | disabled | no (`enabled`) |
| `last_success_at` | max completed job `finished_at` | no, unless a query needs it |
| `last_dispatch_at` | `last_run_at` | yes (existing column) |

## 7. Group transitions

| ID | From -> To | Trigger | Guard | Owner |
|---|---|---|---|---|
| G1 | - -> queued | create | >=1 item, validation passes | API |
| G2 | queued -> running | derived | any child running/paused | read helper |
| G3 | running -> completed | derived | all children completed, none partial | read helper |
| G4 | running -> partial | derived | any child failed/canceled/partial + some completed | read helper |
| G5 | running -> failed | derived | all children failed | read helper |
| G6 | running -> canceled | derived | all children canceled | read helper |
| G7 | any -> retry child | retry | >=1 failed/canceled child | API |
| G8 | active -> canceled | cancel | child active | API |

Rules:

- Group status is derived; no persisted column **[V]**.
- `G4` should include `completion_state=partial` children **[R]**.
- `G7` creates a new group with `parent_group_id`, not an in-place reset
  **[V]** (`groups.py:255-357`).
- `G8` should set `finished_at` on children it cancels **[R]**.
- Empty group -> `completed` today **[V, L]**; change to `queued`/`none`
  **[R]**.

## 8. Report transitions

| ID | From -> To | Trigger | Guard | Owner |
|---|---|---|---|---|
| R1 | none -> off | derived | schedule exists, disabled | read helper |
| R2 | none -> missed | derived | enabled, expected daily, past day, no run | read helper |
| R3 | none -> pending | derived | enabled, expected daily, today, no run | read helper |
| R4 | any -> failed | derived | any failed job | read helper |
| R5 | any -> running | derived | any active job | read helper |
| R6 | any -> partial | derived | any partial, or canceled+completed | read helper |
| R7 | any -> ok | derived | all completed | read helper |
| R8 | alert open -> acknowledged | operator action | does not exist | - |

Rules:

- Precedence must be shared with the group helper where possible. The current
  orders differ **[V]** (`groups.py:38-50` vs `reports.py:100-125`).
- Day key for calendar-day schedules should be the window day, not
  `created_at` **[R]**.
- `missed` should use the schedule cadence or `last_success_at` **[R]**.
- `R8` is a missing machine: alerts are recomputed on every request and have
  no acknowledgement or mute state. This is acceptable for a read-only report,
  but it means an operator cannot "clear" an alert.

## 9. Comparison transitions

| ID | From -> To | Trigger | Guard | Owner |
|---|---|---|---|---|
| X1 | - -> running | run request | valid window | API (optional) |
| X2 | running -> ok | both sides ok | - | API |
| X3 | running -> partial | one side ok | - | API |
| X4 | running -> failed | neither side ok | - | API |

Current code only persists `X2-X4` after both calls finish **[V]**
(`comparisons.py:758-812`). `X1` is a recommendation for crash visibility, not
a defect in successful runs.

## 10. Token transitions

| ID | From -> To | Trigger | Guard | Owner |
|---|---|---|---|---|
| T1 | unknown -> valid | refresh success | refresh token accepted | token manager |
| T2 | valid -> expiring | clock | within display window (1 h) | API display |
| T3 | valid/expiring -> refreshing | get token / 401 | no fresh token | worker/API |
| T4 | refreshing -> valid | success | response has access token | token manager |
| T5 | refreshing -> failed | 4xx (non-429) | - | token manager |
| T6 | refreshing -> retrying | 5xx/429/transport | attempts left | token manager |
| T7 | failed -> unknown | operator re-auth | - | credentials API |

Rules:

- `T3-T4` must be serialized per credential across processes **[R]**. The
  comparison request has a thread lock only **[V]**.
- Persist the rotated refresh token with a compare-and-swap on the token that
  was used, or hold a DB row lock, so a slower refresh cannot overwrite a newer
  rotation **[R]**.

## 11. Authentication transitions

### 11.1 Login throttle

| ID | From -> To | Trigger | Guard | Owner |
|---|---|---|---|---|
| A1 | under -> under | failed login | count < max | API |
| A2 | under -> locked | failed login | count reaches max | API |
| A3 | locked -> under | correct login after expiry | TTL elapsed | API |
| A4 | locked -> locked | any login | count >= max | API |
| A5 | under -> under | successful login | - | API, clears key |

Current behavior is fixed-window, per-email, fail-open **[V]**
(`auth.py:72-137`).

### 11.2 OAuth handshake

| ID | From -> To | Trigger | Guard | Owner |
|---|---|---|---|---|
| O1 | idle -> initiated | `/google/login` | provider enabled | API |
| O2 | initiated -> callback | Google redirect | state + cookie valid, <600 s | API |
| O3 | callback -> authenticated | exchange/validate/provision | domain allowed | API |
| O4 | callback -> failed | error/disabled/denied/domain/invalid state | - | API |

Current state is a signed JWT + cookie, no server-side one-time store
**[V]** (`auth.py:161-212`, `365-386`).

### 11.3 Session

| ID | From -> To | Trigger | Guard | Owner |
|---|---|---|---|---|
| N1 | anonymous -> authenticated | login/Google | valid credentials | API/client |
| N2 | authenticated -> expired | 24 h | JWT exp | API |
| N3 | authenticated -> cleared | any 401 | - | client |
| N4 | cleared -> anonymous | redirect | - | client |

## 12. Infrastructure transitions

### 12.1 Health

| ID | From -> To | Trigger | Guard | Owner |
|---|---|---|---|---|
| H1 | below -> breached | sample >= threshold | metric enabled | monitor |
| H2 | breached -> breached | sample >= threshold | cooldown not elapsed | monitor |
| H3 | breached -> recovered | sample < threshold | breach latch exists | monitor |
| H4 | recovered -> below | recovery notice sent | - | monitor |

Current latches are Redis-only **[V]** (`health_monitor.py:159-217`).

### 12.2 Notification

| ID | From -> To | Trigger | Guard | Owner |
|---|---|---|---|---|
| D1 | not attempted -> retrying | send fails | attempts left | notifier |
| D2 | retrying -> sent | send succeeds | - | notifier |
| D3 | retrying -> failed | attempts exhausted | - | notifier |

No persisted state **[V]** (`notifications.py:76-99`).

### 12.3 Capacity

| ID | From -> To | Trigger | Guard | Owner |
|---|---|---|---|---|
| P1 | configured N -> live M | pool grow/shrink | worker answers | API control |
| P2 | live M -> configured N | restart | env | worker |

### 12.4 Retention

| ID | From -> To | Trigger | Guard | Owner |
|---|---|---|---|---|
| E1 | present -> deleted | age > retention | terminal job, path set | cleanup |
| E2 | present -> deleted | low disk | oldest completed | cleanup |
| E3 | present -> manually deleted | operator | not active | API |
| E4 | deleted -> present | does not exist | - | - |

Rules:

- `E1` should select all terminal jobs, including queued-canceled rows with no
  `finished_at` **[R]**.
- `E1`/`E2` should null all four paths **[R]**.
- `E1-E3` never change lifecycle fields **[R]**.

### 12.5 Index cache / beat / readiness

| ID | From -> To | Trigger | Guard | Owner |
|---|---|---|---|---|
| I1 | miss -> hit | GET | key exists | API |
| I2 | hit -> invalidated | write/delete | - | API |
| I3 | invalidated -> miss | TTL 900 s | - | Redis |
| B1 | fresh -> stale | no beat write | TTL 600 s | Redis |
| B2 | stale -> fresh | beat scan completes | - | worker |

## 13. Parse mode transitions

| ID | From -> To | Trigger | Guard | Owner |
|---|---|---|---|---|
| M1 | raw -> parse-only | create/update | `enabled && !aggregate` | API |
| M2 | parse-only -> aggregate | create/update | `enabled && aggregate` | API |
| M3 | aggregate -> library | create/update | `use_library` and >=1 enabled format | API/worker |
| M4 | any -> raw | create/update | `enabled=false` | API |

Parse mode is immutable for a job after creation, mutable for a schedule.
There is no persisted mode enum today; derive it through one helper **[R]**.

## 14. Client transitions

Client state is local, but it must not invent lifecycle semantics. These tables
are the minimum contract.

### 14.1 Wizard

| ID | From -> To | Trigger | Guard |
|---|---|---|---|
| W1 | step N -> N+1 | Continue | `stepDone[N]` |
| W2 | step N -> M | rail click | M visited or current |
| W3 | any -> run | Run | `canRun` |
| W4 | any -> reset | reload | none |

### 14.2 Job feed

| ID | From -> To | Trigger | Guard |
|---|---|---|---|
| F1 | connecting -> live | `onopen` | - |
| F2 | live -> reconnecting | error, not closed | - |
| F3 | reconnecting -> live | message | - |
| F4 | any -> closed | terminal type or `error` | - |

Fix: the server must accept `Last-Event-ID` or the client must dedupe by event
id. Today the server restarts at 0 and the client prepends duplicates
**[V]** (`jobs.py:1167`; `jobs/[id]/page.tsx:198-199`).

### 14.3 List selection

| ID | From -> To | Trigger | Guard |
|---|---|---|---|
| Q1 | unselected -> selected | checkbox | `isActive` |
| Q2 | selected -> unselected | checkbox/unmount | - |
| Q3 | selected -> confirm | Cancel N | selected non-empty |
| Q4 | confirm -> result | bulk cancel | server responds |
| Q5 | selected -> pruned | poll | job no longer active |

### 14.4 Save-as-search

| ID | From -> To | Trigger | Guard |
|---|---|---|---|
| V1 | idle -> saving | Save | name non-empty |
| V2 | saving -> conflict | duplicate/409 | - |
| V3 | conflict -> saved | Update/Rename | valid name |
| V4 | conflict -> idle | Cancel | - |

### 14.5 Other client machines

- Auto-detect: closed/open/detecting/result/applied/saved/error.
- Job actions: idle/pending/applied/error + confirm.
- Templates: viewing/selecting/batch/created/editing/confirm-delete.
- Schedules: list/adding/editing/rolling-up/confirm-delete.
- Groups: selection/custom-window/pending/error; detail active/done/confirm.
- Reports: window/retention-save/remove-confirm.
- Palette: closed/open/query/results/active.
- Login: idle/submitting/error/redirect.

These are fully documented per machine in
[`STATE_MACHINES.md`](./STATE_MACHINES.md) section 4.

## 15. Enforcement patterns

### 15.1 Conditional update (preferred)

Use one SQL statement with the current state in the `WHERE` clause and
`RETURNING` to learn whether the caller won.

```sql
UPDATE jobs
   SET status = :to, ...
 WHERE id = :id
   AND status = :from
   AND (owner_id IS NULL OR owner_id = :owner)
   AND (lease_token IS NULL OR lease_token = :token)
RETURNING id, lease_token;
```

- 1 row -> transition applied.
- 0 rows -> conflict; read the row to decide 409 vs silent exit.

### 15.2 Compare-and-swap on JSON

For `s3_*` and token rotation, a version column or a conditional `WHERE`
on the previous value is safer than a blind write. Example:

```sql
UPDATE last9_credentials
   SET encrypted_refresh_token = :new, ...
 WHERE id = :id
   AND encrypted_refresh_token = :used;
```

### 15.3 Advisory lock

Use for refresh-per-credential and schedule-window insertion when a unique
constraint is not enough:

```sql
SELECT pg_advisory_xact_lock(:credential_id);
```

The lock is released at transaction end. It does not replace the unique key;
it reduces contention and makes the check-then-insert atomic.

### 15.4 Unique constraint

For schedule windows:

```sql
CREATE UNIQUE INDEX uq_jobs_schedule_window
    ON jobs (created_by, start_epoch)
    WHERE created_by LIKE 'schedule:%';
```

This is a partial index; it does not affect manual jobs. It makes
`_already_extracted` a `ON CONFLICT DO NOTHING` insert instead of a race.

### 15.5 Outbox

For create -> dispatch:

- Option A: a `job_dispatch` outbox row inserted in the same transaction as
  the job; a sweeper publishes and marks it.
- Option B: make dispatch idempotent and retry it from a `queued` sweeper.
- Option C: accept the risk and return the created job even if publish fails,
  with a `dispatch_pending` flag.

Option A is the robust choice; Option B is a smaller first step.

## 16. Atomic transition helper

Recommended shared module (Python, no new dependency):

```python
# api/app/job_state.py (proposal; not implemented)
from enum import StrEnum

class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"

ACTIVE = frozenset({JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.PAUSED})
TERMINAL = frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELED})
DOWNLOADABLE = TERMINAL | {JobStatus.PAUSED}

TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.PAUSED, JobStatus.CANCELED}),
    JobStatus.RUNNING: frozenset({JobStatus.PAUSED, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELED}),
    JobStatus.PAUSED: frozenset({JobStatus.QUEUED, JobStatus.CANCELED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELED: frozenset(),
}

def can_transition(src: str, dst: str) -> bool:
    return JobStatus(dst) in TRANSITIONS[JobStatus(src)]
```

The worker cannot import `api/` (independent build), so mirror the tiny module
under `worker/app/job_state.py` and assert equality in a contract test. Do not
create a third copy in TypeScript by hand; generate it or validate it.

## 17. Cross-language contract

### 17.1 The problem

`JobStatus` is a Python `Literal` **[V]** (`api/app/schemas.py:199`) and a
TypeScript union **[V]** (`web/lib/api.ts:217`). There is no generated source of
truth. The sets of active/terminal/downloadable are re-declared in at least
eight more places.

### 17.2 Recommended contract

1. **Source of truth:** a language-neutral JSON file, e.g.
   `contracts/job-state.json`:

```json
{
  "statuses": ["queued", "running", "paused", "completed", "failed", "canceled"],
  "active": ["queued", "running", "paused"],
  "terminal": ["completed", "failed", "canceled"],
  "downloadable": ["completed", "failed", "canceled", "paused"],
  "transitions": {
    "queued": ["running", "paused", "canceled"],
    "running": ["paused", "completed", "failed", "canceled"],
    "paused": ["queued", "canceled"],
    "completed": [],
    "failed": [],
    "canceled": []
  }
}
```

2. **Python:** load it in a small `job_state.py` (or generate an enum) and use
   it in the API. The worker gets a mirrored copy generated by the same script
   or a checked-in copy with a test.
3. **TypeScript:** generate `web/lib/job-state.ts` with `as const` and derived
   types. A CI check regenerates and fails on diff.
4. **Runtime contract:** `JobOut` includes `status` and (after the change)
   `completion_state`, `gap_count`, `gap_reason`. The OpenAPI schema is the
   API contract; the JSON file is the vocabulary contract.

If a generated file is too much process, the minimum is a single test that
asserts the Python and TypeScript sets match by parsing both files. That test
is cheap and catches the exact drift that exists today.

## 18. Transition test matrix

At minimum:

| Test | Assertion |
|---|---|
| pause queued | 200 -> paused |
| pause running | 200 -> paused; worker acknowledges |
| pause completed | 409, unchanged |
| resume paused | 200 -> queued + dispatched |
| resume running | 409, unchanged |
| cancel queued | 200 -> canceled + finished_at |
| cancel running then worker completes | final status canceled, artifact kept |
| cancel completed | 409 |
| retry failed | new row queued; lineage set |
| retry running | 409 |
| claim twice | one winner |
| reclaim without redelivery | no-op |
| reclaim with redelivery | token increments |
| old worker writes after reclaim | 0 rows, no mutation |
| reaper fails running | failed, token increments |
| reaper leaves live | unchanged |
| schedule two scans | one job per window |
| schedule failed job next scan | no duplicate; explicit policy |
| rollup claim twice | one winner |
| rollup cancel | canceled, no completed overwrite |
| S3 two retries | one attempt or idempotent row |
| token two refreshes | one rotation persisted, no lost token |
| group 9 failed + 1 completed | documented status |
| report backfill yesterday | day key matches window |

Property tests:

- **Settle-once:** a terminal row never leaves the terminal set.
- **Fence:** a write with a stale token never changes the row.
- **Idempotency:** replaying the same chunk does not duplicate counts.
- **Window uniqueness:** no two schedule jobs share `(created_by, start_epoch)`.
- **Cancel dominance:** if `cancel_requested_at` is set, the final status is
  never `completed`.

## 19. What is intentionally not enforced

- UI-only states (wizard step, palette, confirm strips) are not server
  contracts. They do not need DB enforcement.
- Comparison `running` is optional because the request is synchronous.
- Group/report statuses are derived, not enforced by a transition table.
- `missed`/`pending` are derived views of schedule cadence, not persisted
  states.
- `downloadable` and `expired` are derived from paths and existence.

## 20. Migration-free first step

If schema changes are not yet approved, the following can be done with no
migration and no API break:

1. Add `api/app/job_state.py` and `worker/app/job_state.py` with the same
   constants and a contract test.
2. Add `web/lib/job-state.ts` generated or asserted against the Python sets.
3. Replace the duplicated literal sets with imports.
4. Add transition guards to the four mutating routes using the existing
   columns (status only). This does not fix fencing, but it removes the
   vocabulary drift and the obvious 409 gaps.
5. Add the cancel-dominance check in the runner using `current_status`:
   before the final write, re-read the row; if `canceled`, write `canceled`
   and keep the artifact. This is a code change, so it belongs to the roadmap,
   not this task.

The fencing and completeness columns require migrations and are therefore in
[`STATE_MACHINE_ROADMAP.md`](./STATE_MACHINE_ROADMAP.md).
