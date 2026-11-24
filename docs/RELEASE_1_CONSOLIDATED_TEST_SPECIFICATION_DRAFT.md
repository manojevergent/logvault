# Release 1 Consolidated Message-Dispatch Test Specification

Status: **FROZEN FOR M-01 REVIEW. NOT APPROVED.**
Document state: **FREEZE-1**, 2026-11-14. Content is immutable from this point;
any change requires FREEZE-2 and a new hash.
Companion to `RELEASE_1_CONSOLIDATED_IMPLEMENTATION_SPECIFICATION_DRAFT.md`.

Pre-freeze hash (DRAFT-1):
`F65B6536DBA2E7C6B33F4AD355FD0151316B5DD83F61036FC81D6BD434E03A18`.
Frozen hash: recorded in `RELEASE_1_CONSOLIDATED_EXECUTION_PACKAGE.md` section 1.

Adoption (Project Owner decision C-1, 2026-11-14): on A14-01 approval this
document is the authoritative consolidated test specification. It supersedes
`RELEASE_1_P1_IMPLEMENTATION_TEST_SPEC.md` for the consolidated scope; that file
is retained unchanged for audit.

| Control | State |
|---|---|
| A14-01 specification approval | **HOLD - not approved** |
| Gate A (P-03) | **NOT GRANTED** |
| Gate B | **NOT GRANTED** |
| D11 FULL / REDUCED | **UNSIGNED** |
| Tests executed | **NONE** |

No test in this document has been executed. Nothing here is evidence. A row in
this specification becomes evidence only when a run record exists with the
environment, command, output, verdict, duration, and operator.

## 1. Environment

| Item | Required |
|---|---|
| PostgreSQL | 16.x, disposable container |
| Redis | disposable instance, no shared keyspace with any environment |
| Python | 3.12.x |
| Alembic / SQLAlchemy / psycopg | versions pinned by the API image |
| Source data | synthetic or sanitized only |
| Production access | none: no DB, credentials, queues, workers, or S3 |

Every run record captures: test ID, date, operator, commit, environment
versions, exact command, expected, actual, verdict, duration, evidence path.

## 2. Migration suite

Carried forward unchanged: **T-P1-001 to T-P1-014** from
`RELEASE_1_P1_IMPLEMENTATION_TEST_SPEC.md`. They remain valid; their scope does
not change under consolidation. Additionally:

### T-R1-M01 - D11 REDUCED graph

| Field | Detail |
|---|---|
| Setup | D11 REDUCED signed; no `0035`/`0036` files |
| Action | `alembic history`, `alembic heads`, apply chain |
| Expected | `0031 -> 0032 -> 0032b -> 0033 -> 0034`; single head `0034` |
| Pass | Exact chain; no reference to `0035`/`0036` anywhere in the tree |
| Fail | Missing head, dangling down_revision, or a stray ledger/S3 column |
| Evidence | history output, schema diff |

### T-R1-M02 - D11 FULL graph continuity

| Field | Detail |
|---|---|
| Setup | D11 FULL signed; all six revisions present |
| Action | Apply `0034`, then `0035`, then `0036`; query `alembic_version` between each |
| Expected | `0036` head; `0036.down_revision == "0035"` |
| Pass | Chain linear; no `0035b`/`0036b`; no jobs indexes in `0035` |
| Fail | Branch, deferred revision, or index in `0035`/`0036` |
| Evidence | history, `pg_indexes` |

### T-R1-M03 - Migration idempotence after a failed revision

| Field | Detail |
|---|---|
| Setup | Force `0033` to fail after `0032b` succeeded |
| Action | Fix and re-run `0033` only |
| Expected | `0032b` remains committed and valid; `0033` applies cleanly |
| Pass | Version `0032b` after failure; `0033` after retry; indexes valid |
| Fail | Index dropped or invalidated by the retry |
| Evidence | version, `pg_index`, logs |

## 3. Claim, ownership, and fencing

### T-R1-001 - Two workers claim the same job

| Field | Detail |
|---|---|
| Setup | One `queued` job; two task invocations released simultaneously |
| Action | Run both workers against the same `job_id` |
| Expected | Exactly one claim returns a token; the other returns zero rows and exits without executing |
| Pass | One `lease_token` increment; one artifact set; one terminal event |
| Fail | Two executions, two artifact attempts, or two terminal events |
| Evidence | claim return values, event log, artifact listing |

### T-R1-002 - Duplicate Celery delivery

| Field | Detail |
|---|---|
| Setup | `broker` delivers the same message twice, both before and after claim |
| Action | Replay the identical message while the first run is in flight, then after completion |
| Expected | Second delivery exits at claim (running, valid lease) or at a terminal check |
| Pass | Single execution; no duplicate rows; no artifact overwrite |
| Fail | Re-entry into runner, duplicate output, or corrupted counts |
| Evidence | logs, row counts, output checksum |

### T-R1-003 - Claim rejected when cancel is requested

| Field | Detail |
|---|---|
| Setup | `queued` job with `cancel_requested_at` set |
| Action | Deliver the message |
| Expected | Claim returns zero rows; job moves to `canceled` by the canceling writer |
| Pass | Never enters `running`; no artifact directory created |
| Fail | Job runs, or hangs in `queued` forever |
| Evidence | status timeline, events |

### T-R1-004 - Pause during run

| Field | Detail |
|---|---|
| Setup | Running job with a valid lease; `pause_requested_at` set mid-chunk |
| Action | Let the current chunk finish |
| Expected | Chunk completes, checkpoint commits, job moves to `paused` via a fenced write |
| Pass | No data loss, token unchanged, resume possible |
| Fail | Immediate abort with partial unwritten output, or pause ignored |
| Evidence | checkpoint state, events |

### T-R1-005 - Resume increments the token

| Field | Detail |
|---|---|
| Setup | `paused` job with checkpoint |
| Action | Resume via API |
| Expected | New outbox row (or reset to pending); next claim increments `lease_token` |
| Pass | Token strictly greater than the pre-pause token; resume appends to the same attempt lineage only if the attempt key matches |
| Fail | Token reused or reset; resume appends into a foreign attempt |
| Evidence | token values, artifact paths |

### T-R1-006 - Stale worker write rejection

| Field | Detail |
|---|---|
| Setup | Worker A holds token N; reconciler or worker B advances to N+1 |
| Action | Worker A attempts a progress write, then a terminal write |
| Expected | Both fenced updates return zero rows; A aborts and emits `lease_lost` |
| Pass | No write applied; no artifact published by A; A does not delete A's files if B owns them |
| Fail | Any write applied with a stale token |
| Evidence | update row counts, `lease_lost` event, final row state |

### T-R1-007 - Terminal state is absorbing

| Field | Detail |
|---|---|
| Setup | Completed job with token N |
| Action | Replay the message; attempt a fenced write with N and with N+1 |
| Expected | No transition away from `completed` |
| Pass | Status, pointers, and gap fields unchanged |
| Fail | Reopened, overwritten, or duplicated |
| Evidence | before/after row snapshot |

## 4. Crash and recovery

### T-R1-010 - Crash immediately after claim

| Field | Detail |
|---|---|
| Setup | Worker killed after the claim commit, before any output |
| Action | Wait one TTL, then run the reconciler |
| Expected | Reconciler increments the token, clears owner, resets outbox to `pending`; new worker claims |
| Pass | Job resumes at chunk 0 in a new attempt; total executions <= 2 |
| Fail | Job stuck in `running` indefinitely; or two live owners |
| Evidence | lease timeline, attempts, reconciler log |

### T-R1-011 - Crash during processing

| Field | Detail |
|---|---|
| Setup | Kill the worker mid-chunk with a valid checkpoint from a prior chunk |
| Action | Reconciler, then redispatch |
| Expected | New attempt validates the checkpoint, resumes at the next chunk |
| Pass | No duplicated rows; row count equals a clean single run |
| Fail | Duplicate rows, truncated output, or restart from 0 with valid checkpoint |
| Evidence | output row count/checksum against a control run |

### T-R1-012 - Crash after artifacts, before publication

| Field | Detail |
|---|---|
| Setup | Kill the worker after files are closed and uploaded, before the pointer update |
| Action | Reconciler, redispatch |
| Expected | Job is still non-terminal; a new attempt runs or re-publishes; exactly one attempt becomes published |
| Pass | One published pointer; orphaned attempt is quarantined, not published |
| Fail | Job shows `completed` with a null or stale pointer; two published pointers |
| Evidence | pointer values, `s3_published_attempt`, object listing |

### T-R1-013 - Lease expiry redispatch

| Field | Detail |
|---|---|
| Setup | Running job, lease expired, outbox `published` |
| Action | Run the reconciler twice |
| Expected | First tick fences and reopens; second tick is a no-op (idempotent) |
| Pass | Exactly one token increment per tick that acts; no duplicate outbox row |
| Fail | Double increment per tick, or repeated reopen storm |
| Evidence | token sequence, outbox attempts |

### T-R1-014 - Retry exhaustion

| Field | Detail |
|---|---|
| Setup | Job that always crashes after claim; `max_attempts` lowered for the test |
| Action | Reconciler loop until cap |
| Expected | Job terminal `failed` with `retry_exhausted`; outbox `dead` or attempts capped |
| Pass | Bounded attempts; no further dispatch; reason recorded |
| Fail | Infinite redispatch, or silent `dead` with no job failure |
| Evidence | attempts counter, terminal state, events |

### T-R1-015 - Redispatch capped by terminal user intent

| Field | Detail |
|---|---|
| Setup | Running job, lease expired, `cancel_requested_at` set |
| Action | Reconciler tick |
| Expected | `canceled`, not redispatched |
| Pass | No new outbox dispatch; terminal |
| Fail | Canceled work resumes |
| Evidence | status, outbox state |

## 5. Heartbeat and progress

### T-R1-020 - Heartbeat without progress does not renew

| Field | Detail |
|---|---|
| Setup | Worker loop deliberately blocked; heartbeat thread alive |
| Action | Observe for > 1 TTL |
| Expected | `heartbeat_at` advances; `lease_expires_at` does not; lease expires |
| Pass | Lease expires while heartbeat is fresh; reconciler acts |
| Fail | Lease extended by liveness alone |
| Evidence | timestamp series |

### T-R1-021 - Progress-aware renewal

| Field | Detail |
|---|---|
| Setup | Worker making steady progress |
| Action | Observe for > 3 TTL |
| Expected | Every progress advance renews `lease_expires_at`; no expiry |
| Pass | No redispatch; single attempt |
| Fail | Spurious expiry mid-run |
| Evidence | timestamp series, attempt count |

### T-R1-022 - Stalled job detection

| Field | Detail |
|---|---|
| Setup | Worker blocked longer than TTL after progress had been made |
| Action | Reconciler tick |
| Expected | Job classified stale, redispatched; stall event recorded |
| Pass | Detection latency <= TTL + reconciler interval |
| Fail | Undetected stall, or detection requiring manual action |
| Evidence | timestamps, events |

### T-R1-023 - Progress emission cadence

| Field | Detail |
|---|---|
| Setup | Single long chunk exceeding the progress interval |
| Action | Run to completion |
| Expected | At least one `progress_at` advance per M seconds (15s default) within the loop |
| Pass | Maximum observed gap <= M + tolerance |
| Fail | No progress for a full TTL during healthy work |
| Evidence | timestamp series |

## 6. Outbox

### T-R1-030 - Outbox written in the job transaction

| Field | Detail |
|---|---|
| Setup | Job creation endpoint |
| Action | Create a job with the dispatcher stopped |
| Expected | Exactly one `pending` outbox row, same `job_id`, committed with the job |
| Pass | Row exists; no broker call occurred; job `queued` |
| Fail | Job without outbox row, or a broker call before commit |
| Evidence | table row, broker inspect, transaction log |

### T-R1-031 - Outbox rollback on failed job insert

| Field | Detail |
|---|---|
| Setup | Force the job insert to fail after the outbox statement |
| Action | Call the creation path |
| Expected | Neither row exists |
| Pass | Both absent |
| Fail | Orphan outbox row or orphan job |
| Evidence | row counts |

### T-R1-032 - Publisher crash mid-publish

| Field | Detail |
|---|---|
| Setup | Dispatcher killed after locking a batch, before marking published |
| Action | Wait past `locked_until`; run the dispatcher |
| Expected | Row is reclaimable and published exactly once |
| Pass | One message observed; no stuck `locked_by` |
| Fail | Row permanently locked, or lost |
| Evidence | lock fields, broker message count |

### T-R1-033 - Replay after broker outage

| Field | Detail |
|---|---|
| Setup | Broker unreachable; several jobs created |
| Action | Restore broker; run the dispatcher |
| Expected | All pending rows publish in `next_attempt_at` order; attempts recorded |
| Pass | Every job dispatched; backoff respected; no duplicate rows |
| Fail | Lost jobs, ignored backoff, or duplicate outbox rows |
| Evidence | attempt series, dispatch log |

### T-R1-034 - Duplicate dispatch suppression

| Field | Detail |
|---|---|
| Setup | A published row for a non-terminal job with an expired lease |
| Action | Force a reopen, publish again |
| Expected | Only one of the two messages executes; the unique row is reused, not duplicated |
| Pass | Unique constraint holds; single execution |
| Fail | Two outbox rows for one `(job_id, task_name)` |
| Evidence | constraint check, executions |

### T-R1-035 - Attempt cap to dead

| Field | Detail |
|---|---|
| Setup | Permanently failing publish |
| Action | Run the dispatcher past `max_attempts` |
| Expected | Status `dead`, last error retained, no further automatic attempts |
| Pass | Bounded attempts; explicit operator replay required |
| Fail | Infinite retry, or silent drop |
| Evidence | attempts, status |

### T-R1-036 - Dispatcher never publishes terminal jobs

| Field | Detail |
|---|---|
| Setup | Outbox row for a job canceled after publish |
| Action | Force reopen evaluation |
| Expected | No dispatch |
| Pass | No new message |
| Fail | Canceled work redispatched |
| Evidence | broker inspect |

## 7. Artifacts and publication

### T-R1-040 - Attempt isolation

| Field | Detail |
|---|---|
| Setup | Two sequential attempts (token N, then N+1) |
| Action | Run both against the same job |
| Expected | Distinct local and S3 paths per attempt; no cross-write |
| Pass | Path sets disjoint; final pointers reference the published attempt only |
| Fail | Shared path, append across attempts, or one attempt deleting the other's files |
| Evidence | directory listing, object listing, pointers |

### T-R1-041 - Artifact upload failure

| Field | Detail |
|---|---|
| Setup | S3 endpoint returns an error (local stub) |
| Action | Run to completion |
| Expected | No pointer update; job fails or retries per policy; local files retained |
| Pass | Pointers unchanged; failure reason recorded; retry possible |
| Fail | Job marked completed with a missing object |
| Evidence | pointers, error, retry run |

### T-R1-042 - Pointer update failure after successful upload

| Field | Detail |
|---|---|
| Setup | Object uploaded; force the guarded update to affect zero rows (lease stolen) |
| Action | Continue |
| Expected | Worker aborts, emits `lease_lost`, does not mark terminal |
| Pass | Job non-terminal; reconciler redispatches; exactly one eventual published pointer |
| Fail | Terminal status without a committed pointer |
| Evidence | row state, events, final pointers |

### T-R1-043 - Published pointer is immutable

| Field | Detail |
|---|---|
| Setup | Job completed with a published attempt |
| Action | Attempt a late write with an older token |
| Expected | Rejected |
| Pass | Pointers and `s3_published_attempt` unchanged |
| Fail | Overwritten pointer |
| Evidence | before/after snapshot |

### T-R1-044 - Cleanup preserves published artifacts

| Field | Detail |
|---|---|
| Setup | One published attempt and one orphaned attempt for the same job |
| Action | Run retention/cleanup |
| Expected | Published attempt retained; orphan eligible; pointer still resolves |
| Pass | Download works after cleanup |
| Fail | Published file deleted |
| Evidence | file listing, download result |

## 8. Checkpoint

### T-R1-050 - Incomplete checkpoint restarts

| Field | Detail |
|---|---|
| Setup | Checkpoint file truncated or written without the final rename |
| Action | Claim and resume |
| Expected | Validation fails; restart at chunk 0 |
| Pass | No partial merge; output equals a clean run |
| Fail | Resume on a torn checkpoint |
| Evidence | checksum comparison |

### T-R1-051 - Inconsistent checkpoint restarts

| Field | Detail |
|---|---|
| Setup | Checkpoint claims a chunk whose artifact is absent/short |
| Action | Resume |
| Expected | Restart at chunk 0 |
| Pass | Correct output |
| Fail | Missing rows or a crash loop |
| Evidence | validation log, output count |

### T-R1-052 - Zero completed chunks restarts

| Field | Detail |
|---|---|
| Setup | `completed_chunks = 0` checkpoint |
| Action | Resume |
| Expected | Restart, never append |
| Pass | Single clean output |
| Fail | Append to an empty/foreign file |
| Evidence | output, paths |

### T-R1-053 - Fingerprint mismatch restarts

| Field | Detail |
|---|---|
| Setup | Checkpoint from a different filter spec |
| Action | Resume |
| Expected | Restart at chunk 0 in a fresh attempt |
| Pass | No cross-spec data |
| Fail | Merged output |
| Evidence | output content diff |

### T-R1-054 - Valid checkpoint resumes correctly

| Field | Detail |
|---|---|
| Setup | Two completed chunks, artifact intact |
| Action | Resume |
| Expected | Continue at chunk 3; totals match a clean run |
| Pass | Row counts and checksums equal the control |
| Fail | Duplicate or missing rows |
| Evidence | control comparison |

## 9. Partial completion

### T-R1-060 - Partial job reported

| Field | Detail |
|---|---|
| Setup | Force a gap (one window fails, others succeed) |
| Action | Run to terminal |
| Expected | `completion_state='partial'`, `gap_count>0`, non-empty `gap_reason` |
| Pass | All three present and consistent |
| Fail | `complete` with a gap |
| Evidence | API response, row snapshot |

### T-R1-061 - Partial never displays as clean success

| Field | Detail |
|---|---|
| Setup | Partial job |
| Action | List and detail endpoints |
| Expected | Distinct partial indication; download available |
| Pass | No success-only labeling |
| Fail | Renders identically to a complete job |
| Evidence | response bodies, UI capture |

### T-R1-062 - Complete requires zero gaps

| Field | Detail |
|---|---|
| Setup | No gaps |
| Action | Terminal write |
| Expected | `complete`, `gap_count=0`, empty reason |
| Pass | Consistent |
| Fail | `partial` with zero gaps |
| Evidence | row snapshot |

## 10. Beat and scheduler

### T-R1-070 - Single beat instance

| Field | Detail |
|---|---|
| Setup | Two beat processes started |
| Action | Observe one tick window |
| Expected | Only the lock holder runs the scan |
| Pass | One scan per tick |
| Fail | Duplicate scans |
| Evidence | logs, lock key |

### T-R1-071 - No duplicate schedule jobs

| Field | Detail |
|---|---|
| Setup | D11 FULL ledger; one due window |
| Action | Two concurrent scans |
| Expected | Unique `(schedule_id, window_key)` admits one job |
| Pass | One job, one window row |
| Fail | Duplicate jobs for one window |
| Evidence | row counts |

### T-R1-072 - No embedded beat

| Field | Detail |
|---|---|
| Setup | Deployment and start scripts |
| Action | Static scan for `-B` |
| Expected | No `-B` in any runtime path |
| Pass | Absent everywhere |
| Fail | Any embedded beat remains |
| Evidence | grep output, start command |

## 11. Compatibility

### T-R1-080 - Old worker on migrated schema

| Field | Detail |
|---|---|
| Setup | Schema at head; previous release worker |
| Action | Run a normal job |
| Expected | Succeeds; ignores new columns; no lease |
| Pass | Job completes; new columns remain defaults |
| Fail | SQL error, missing column, or changed response |
| Evidence | worker log, row state |

### T-R1-081 - Mixed-version drain

| Field | Detail |
|---|---|
| Setup | Old and new workers consuming the same queue |
| Action | Drain a bounded queue |
| Expected | No job executes twice; old worker jobs complete once |
| Pass | Execution count equals job count |
| Fail | Duplicate execution during mixed operation |
| Evidence | per-job execution counters |

### T-R1-082 - Outbox dual-write equivalence

| Field | Detail |
|---|---|
| Setup | Stage B: outbox and legacy direct send both active |
| Action | Create N jobs; stop the dispatcher |
| Expected | Legacy path dispatches; outbox rows remain pending without double execution |
| Pass | N executions, N rows |
| Fail | 2N executions |
| Evidence | counters |

### T-R1-083 - Dispatcher authoritative in stage D

| Field | Detail |
|---|---|
| Setup | Stage D; legacy direct send removed |
| Action | Create a job with the dispatcher stopped, then start it |
| Expected | Nothing runs until the dispatcher publishes |
| Pass | Exactly one execution after publish |
| Fail | Any direct dispatch remains |
| Evidence | static scan, dispatch log |

## 12. Verdict rules

A run fails if any of the following occurs, even when the individual test
reports success:

- a test is marked passed without a captured run record;
- an unguarded job write path remains reachable;
- `upgrade head` is used in a migration window;
- a deferred index appears before its owning phase;
- two live owners are observed for one job;
- a terminal row is modified;
- a published pointer is overwritten;
- a partial job renders as complete;
- an execution count exceeds one per job in the single-worker path;
- any production system was touched.

## 13. Stop condition

This is a test specification. It authorizes no execution. Tests may run only
after A14-01 is approved and Gate A is granted, and only inside the isolated
engineering environment.
