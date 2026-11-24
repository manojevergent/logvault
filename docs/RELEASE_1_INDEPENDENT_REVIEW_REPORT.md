# Release 1 — Independent Review Report (self-critical analysis for a reviewer)

> **Authoritative candidate: `7f2ac46` (`7f2ac468e21de16e2feee9f2bd81b8fe0669c89b`).**
> Worker image `last9-worker:release-1-final-7f2ac46-fix4`
> (`sha256:f96fac9f…f224fbb`), package
> `release-artifacts/release-1-final-7f2ac46-fix4/`.
> Everything below is the historical `78fb0a7` → `84046b2` review record; the
> reconciliation at the end of this document supersedes its candidate identity.
> Reviewer fields remain blank and Gate B remains NOT GRANTED.


> **This is not an independent review.** It was produced by the implementation
> author acting as a critic. An independent review requires a separate,
> identified human who performs and accepts it. Every reviewer field below is
> deliberately blank. Treat this as input to that review, not as approval.

| Field | Value |
|---|---|
| Commit reviewed | `78fb0a7531f4534e91a48c652e72fa3231a26f60` |
| Parent | `6719568f6fe7233e74aa151e3ba3531b2d6cb99d` |
| `main` at review | `6719568f` (unchanged) |
| Branch | `release-1/p1-dispatch` |
| Working tree | clean; 4 untracked package dirs |
| Prepared by | implementation author (not independent) |
| Reviewer | ____________________ |

## Executive summary

The dispatch, fencing, outbox, artifact and recovery machinery is real and
largely well-evidenced. **One critical defect invalidates the headline claim of
this release:**

**The progress-aware heartbeat is implemented but never wired into the real
runner.** `worker/app/heartbeat.py` exists and is unit-shaped, but
`worker/app/runner.py` never imports it, never starts it, and never calls
`renew_progress`. The claim TTL is 60 seconds and nothing renews it.

Consequence: **every job that runs longer than 60 seconds has an expired lease
while it is still alive.** The reconciler will fence it and redispatch it, so a
long extraction can be executed twice, its writes silently fail, and retries can
exhaust. This is precisely the failure mode the release exists to prevent.

Status: **FAIL**. Recommendation: do not proceed to Gate B until this is fixed
and retested with a real long-running job.

## Methodology

Source read at the reviewed commit; call sites traced; existing tests inspected;
no test executed during this review except read-only greps. Nothing was modified.

## Area 1 — State machine and lifecycle

Paths: `worker/app/db.py:228-306`, `worker/app/fenced.py`, `worker/app/runner.py`,
`worker/app/reconciler.py`.

- Six statuses; terminal absorbing; cancel dominant — **PASS**.
- Claim is one conditional UPDATE returning the token — **PASS**.
- Reconciler-fenced rows are reclaimable only with `owner_id IS NULL` and
  `token > 0`, so legacy rows are not stolen — **PASS** (three regression tests).
- No path sets `running` without a token increment — **PASS**.
- **Permanently stuck job:** possible via F-01 (lease expires, reconciler
  redispatches, job ping-pongs until `retry_exhausted`). **FAIL** (see F-01).

## Area 2 — Transactional outbox

Paths: `api/app/outbox.py`, `worker/app/outbox.py`, 7 call sites in
`api/app/routers/jobs.py` and `groups.py`.

- Row written before commit at all seven sites — **PASS** (by inspection).
- Dispatcher uses `FOR UPDATE SKIP LOCKED` on PostgreSQL only — **PASS**.
- `mark_published` requires `status='pending'`, own `locked_by`, `rowcount == 1` —
  **PASS**; unconfirmed publish counted as `lost_update`.
- Crash window *commit → publish*: row stays `pending`, retried — **PASS by design**.
- Crash window *publish → mark*: `locked_until` expires, row reclaimed, duplicate
  message harmless because the claim is fenced — **PASS by design**.
- **Direct test of either crash window: none.** Only `lost_update` is tested.
  **PARTIAL.**

## Area 3 — Ownership, claims and fencing

Paths: `worker/app/fenced.py`, `worker/app/db.py:228-306`,
`worker/app/runner.py:213,970`.

- Token monotonic via `coalesce(lease_token,0)+1` — **PASS**.
- Fenced writes require the token; terminal writes require owner — **PASS**.
- `artifacts.publish` is the only publication path — **PASS**.
- **`db.update_job` remains unfenced and still has job-state callers:**
  `rollup.py:85,96,153,186,228`, `tasks.py:128,192,198,215`,
  `scheduler.py:239`, `runner.py:213` (pre-claim, safe).
  `rollup.py:85` sets `status="running"` **without a token**. Whether rollup
  claims first was not established. **PARTIAL — must be traced by the reviewer.**
- **Return values of fenced writes are ignored** at chunk boundaries
  (`runner.py` checkpoint updates). A stale worker keeps running after its writes
  start failing. **PARTIAL** (correctness preserved by the fence; wasted work).

## Area 4 — Heartbeat and progress — **FAIL**

Paths: `worker/app/heartbeat.py`, `worker/app/runner.py`, `worker/app/db.py:241`.

- `runner.py` contains **no** reference to `Heartbeat`, `renew_progress` or
  `heartbeat_only` (grep: zero hits).
- `runner.py` has no `.progress(` call (grep: zero hits).
- Claim sets `lease_expires_at = now + 60s` (`db.py:241`).
- The runner's only periodic signal is `db.add_event(...)` every
  `HEARTBEAT_SECONDS = 300` (`runner.py:546,699`) — an *event*, not a lease
  renewal.
- Therefore the lease expires 60 s into every non-trivial job.

Phase coverage: claim ✔, chunk boundary ✔ (checkpoint), extraction loop ✘,
artifact packaging ✘, S3 upload ✘, publication ✘ — none renew the lease.

False positives: any job > 60 s is treated as stalled. False negatives: none,
because detection is not progress-based at all in practice.

**Status: FAIL. Severity: critical. Blocks production.**

## Area 5 — Lease expiry and recovery

Paths: `worker/app/reconciler.py`, `worker/app/fenced.py`.

- Reconciler logic, ordering, fencing, exhaustion — **PASS** as written.
- Because of F-01, it fires against healthy long jobs. **FAIL in practice.**
- Recovery after restart: reconciler is stateless and DB-driven — **PASS**.

## Area 6 — Checkpoint validation

Paths: `worker/app/last9/checkpoint.py`, `runner.py:274-300,377,443-444,646`.

- Validation of job id, version, numeric progress, offset, artifact presence —
  **PASS** (17 checks executed earlier).
- Resume truncates to the recorded offset before appending — **PASS by design**.
- Interaction with F-01: a redispatched long job resumes from a checkpoint while
  the original worker may still be writing. The fence stops the writes, but the
  two processes share one artifact path on a shared volume. **Risk, PARTIAL.**

## Area 7 — Artifact isolation and publication

Paths: `worker/app/artifacts.py`, `runner.py:351-380,970`.

- Attempt paths `job_<id>/a<token>/` — **PASS** (12 tests).
- Publication is one guarded UPDATE with token + owner + `status='running'` —
  **PASS**.
- A resume deliberately reuses the file the checkpoint names; two attempts can
  therefore coexist on disk only when the checkpoint is valid — **PASS by design**.
- Cleanup of orphaned attempts: **not implemented**. Disk grows. **PARTIAL.**

## Area 8 — Migrations and rollback

Paths: `api/migrations/env.py`, `versions/0032*, 0032b*, 0033*, 0034*`.

- TPM enabled; concurrent indexes in autocommit blocks; validity **and**
  definition checked — **PASS**.
- Upgrade and downgrade executed on disposable PG16; 4.2 s at toy size —
  **PASS at toy size only**.
- **Downgrade drops `job_dispatch_outbox`.** The four drain gates are checked in
  one statement batch, not atomically with the downgrade, so concurrent dispatch
  or job creation between the gate query and `alembic downgrade` can reintroduce
  obligations. **PARTIAL — the gates are necessary but not provably sufficient.**

## Area 9 — Beat singleton and orchestration

Paths: `worker/app/beat_guard.py`, `celery_app.py`, `docker-compose.yml`.

- Separate beat; no `-B`; guard holds a Redis lock; child is terminated when the
  lock is lost or unverifiable — **PASS** (10 failure-mode tests).
- Lock lives in the broker Redis DB; health reads the same DB — **PASS** (fixed).
- TTL 90 s means a hard-killed beat delays its replacement — acceptable, documented.

## Area 10 — API, frontend, partial completion

Paths: `api/app/schemas.py`, `routers/jobs.py`, `web/lib/completion.ts`,
`web/app/jobs/*`.

- `completion_state` / `gap_count` / `gap_reason` exposed with defaults —
  **PASS**.
- Frontend shows a partial badge and a warning line; legacy responses render
  unchanged — **PASS** (8 unit tests, tsc clean).
- Partial jobs are downloadable — intended — **PASS**.

## Area 11 — Security and images

Paths: `requirements.txt` (both), `SECURITY_RESCAN.md`, `IMAGE_INVENTORY.md`.

- cryptography 50.0.0, python-jose 3.4.0 — remediated, verified in image.
- starlette 0.41.3 (7 advisories) — **DEFERRED**, not resolved.
- ecdsa 0.19.2 (1) and python-jose PYSEC-2025-185 — **no fix**, deferred.
- Images: API `341a8da7…`, Worker `05ca0ee7…`, Web `6a6489dc…` — recorded,
  provenance verified file-by-file for API and worker.
- **Web image is built with `http://localhost:8000`** — not deployable as-is.
  **BLOCKING for deployment.**

## Area 12 — Testing, observability, governance

- API 289, worker suite, frontend 8, tsc clean, stack verified — **PASS** as
  reported, reproducible.
- **No test covers a long-running job against the real runner's lease.** The
  long-chunk test (`test_runner.py:348`) asserts events, not lease renewal —
  which is why F-01 went unnoticed. **FAIL coverage.**
- No test covers the outbox crash windows directly — **NOT TESTED**.
- No test covers actual Last9 behaviour — **NOT TESTED**.
- Monitoring: 11 gauges; `unknown` handling verified; task failure/retry counters
  absent — **PARTIAL**.
- Governance: single-person control — **documented, not mitigated**.

## Critical issues

| ID | Issue | Severity |
|---|---|---|
| F-01 | Heartbeat module not wired into runner; lease expires after 60 s | **Critical** |
| F-02 | `db.update_job` still used for job state without fencing (`rollup.py`, `tasks.py`) | High |
| F-03 | Fenced write failures ignored in runner loops | Medium |
| F-04 | Drain gates not atomic with downgrade | Medium |

## Recommendations

1. **Do not proceed to Gate B** until F-01 is fixed and proven with a job longer
   than several lease TTLs.
2. Fix: start `Heartbeat(eng, job_id, token)` after the claim, call `.progress()`
   at chunk boundaries and at each 300 s event beat, and stop the job when the
   lease is lost.
3. Trace and fence F-02, or prove rollup/tasks cannot race.
4. Add a regression test: job running 5× TTL with no progress must be fenced and
   redispatched; job running 5× TTL with progress must complete untouched.

## Final technical assessment

**FAIL — critical defect outstanding.** The architecture is sound and most
components are genuinely implemented and tested; the heartbeat is the exception,
and it is the one that makes long-running work safe. This is exactly the class of
defect that self-review misses and an independent reviewer exists to find.

---

## Addendum - commit 9aac582 (F-01 lease renewal fix)

Reviewed commit: `9aac582676d51df8c13d6817400b7b6c528d3207` (parent `78fb0a7`).
This addendum supersedes the commit identity above; the earlier text is
preserved as the `78fb0a7` review record.

**F-01 status: PARTIAL - improved, not closed.**

Verified in the commit and in the worker image (runner.py byte-identical):

- renewal at chunk commit (`runner.py:673`), in the same transaction as the
  checkpoint, so the two commit atomically;
- renewal during the row-flow status check (`runner.py:702`), ~20 s, inside the
  60 s TTL;
- both use the job's own fencing token and raise if the lease is already gone;
- disposable PostgreSQL 16: renewal extends the lease, the reconciler leaves the
  job alone, silence is fenced (token+1, owner cleared), a superseded token is
  refused, concurrent claims have one winner.

**Residual gap.** Renewal fires only when a row is yielded or a chunk commits.
A single blocking call inside `iter_extraction` - a Last9 request with a retry
chain, or a slow page - yields nothing for its duration. A stall longer than the
60 s TTL still expires the lease, and the reconciler will fence a healthy worker
mid-request. Fencing prevents corruption; it does not prevent the work being
thrown away and redispatched.

Classification: **condition for acceptance**, not a test-coverage gap. Either
accept the >60 s stall exposure explicitly with that impact recorded, or replace
the inline tick with a timer-driven heartbeat that does not depend on row flow.

F-02 and F-04 remain **OPEN**. F-01 being fixed does not close them.
Real-time full-runner test beyond the TTL: **NOT TESTED**.
Images: api `1fe369ff…`, worker `010008e2…`, web `6a6489dc…` (unchanged).
Package: `release-1-final-78fb0a7-fix1`, 30 files, 0 mismatches, manifest
`AB4577EC…`.
Reviewer checkboxes remain unmarked. No independent reviewer has been named.
Gate B: **NOT GRANTED**.

### Area 4 matrix update (this addendum)

| Area | 78fb0a7 | 9aac582 |
|---|---|---|
| 4 Heartbeat | FAIL | **PARTIAL** - row flow and chunk commit renew; blocking-call stalls still expire |
| 5 Recovery | FAIL in practice | **PARTIAL** - no longer fires on row-flowing jobs; still fires on >TTL stalls |
| 12 Tests | FAIL | **PARTIAL** - lease test added; real-time >TTL run still NOT TESTED |

New finding: F-13 (stall inside a single extraction call outlives the TTL).
New risk: RK-17.

---

## Addendum 2026-11-15 - commit 84046b2 (supersedes 9aac582 / 616a8d3 for identity only)

Source commit: 84046b2 (parent 616a8d3). Branch release-1/p1-dispatch. main 6719568f unchanged. Not pushed.

Candidate images: last9-api:release-1-final-616a8d3-fix3 sha256:78f7f987cf3bc5074e6f3aeb9b08c3816bf4e18d7ddb57b3b4772de21c6396bb; last9-worker:release-1-final-616a8d3-fix3 sha256:c36ac27faa3c386a04f0ed08c1d3123a0aa28f9d9762047c701d2bcf596d8917; web unchanged last9-web:release-1-final-78fb0a7.

Package: release-artifacts/release-1-final-84046b2-fix3/ - 31 files, 0 checksum mismatches. checksums.sha256 SHA-256 7A207A3BA1A8913965B32BB1E9CE9DB0A6AAD930A00E24468153F81F9B7A8E4A.

Finding status in this commit:
- F-02a rollup: claim added; all writes fenced. Rollup caller inventory: worker/app/tasks.py:172 -> run_rollup(job_id); no other caller. Five write sites converted.
- F-04 downgrade: LOCK TABLE job_dispatch_outbox IN ACCESS EXCLUSIVE MODE taken before the guard counts. Refuses instead of dropping obligations. Concurrency proof still relies on the disposable PG16 runs already recorded; no new concurrent-dispatch test was added.
- F-13 keeper: 4 tests added (renewal without rows, stale token, terminal state, transient DB error). A real bug was found and fixed: self._stop shadowed Thread._stop() so join() raised TypeError; renamed to self._stopped. A real wall-clock >60s blocked extraction call is still NOT proven.

Tests executed for this commit: worker suite all passed exit 0; API 289 passed exit 0; frontend 8 passed; tsc exit 0; worker image app/rollup.py byte-identical to the commit.

Still open: F-13 real-time blocked-call test; Last9 extraction NOT TESTED; production web API URL absent; starlette/ecdsa/python-jose advisories deferred; single-person control; no independent review; commit not pushed. Gate B NOT GRANTED.

---

## Final test closure 2026-11-15 - commit 84046b2 (executed evidence)

**This section supersedes the finding statuses above.** It records what was
executed during the final closure pass. It does not change any reviewer box,
name, date or signature, and it is not an independent review.

| Item | Value |
|---|---|
| Branch | `release-1/p1-dispatch` |
| Candidate commit | **`84046b2`** (parent `616a8d3`) |
| `main` | `6719568f` - unchanged |
| Ahead of main | 4 commits |
| Pushed | **No** - `origin/release-1/p1-dispatch` is `78fb0a7` |
| API image | `last9-api:release-1-final-84046b2-fix3` = `sha256:78f7f987cf3bc5074e6f3aeb9b08c3816bf4e18d7ddb57b3b4772de21c6396bb` |
| Worker image | `last9-worker:release-1-final-84046b2-fix3` = `sha256:c36ac27faa3c386a04f0ed08c1d3123a0aa28f9d9762047c701d2bcf596d8917` |
| Web image | `last9-web:release-1-final-78fb0a7` = `sha256:6a6489dcc5d3d9ef76ef5c6cc0cc4ab11faa8fac376895a14f9974b0fd660ab1` (unchanged) |
| Package | `release-artifacts/release-1-final-84046b2-fix3/` - 31 files, 0 checksum mismatches |
| Package checksum | `7A207A3B...8E4A` as recorded in the addendum above; the `checksums.sha256` in the package now hashes to `44077dbeec9d878aa1cc2c69525df585a3d0162b01ac4fece3b5d8bbf1b2608d`, and all 30 of its entries verify. See "Evidence discrepancies" below. |
| New evidence | `release-artifacts/evidence-final-closure-84046b2/` |
| Source changes in this pass | **none** |
| Gate B | **NOT GRANTED** |

### F-02a - rollup ownership: IMPLEMENTED, seven scenarios executed

Implementation (unchanged from `84046b2`): atomic `db.claim_job` at
`worker/app/rollup.py:88`, early return when the claim is lost at `:95`, five
state writes routed through the fenced `save()` at `:99-101`. One entry point:
`worker/app/tasks.py:174`.

New file `worker/tests/test_rollup_ownership.py`, executed inside the release
worker image, with scenario 3 on disposable PostgreSQL 16 (threads plus a
barrier, so the race is real rather than serialised by SQLite):

| # | Scenario | Result |
|---|---|---|
| 1 | normal claim and completion under one owner | **PASS** |
| 2 | duplicate delivery while an owner is live bows out | **PASS** |
| 3 | concurrent claims have exactly one winner (PG16) | **PASS** |
| 4 | superseded rollup cannot write its result | **PASS** |
| 5 | crash after claim: duplicate bows out, reconciler fences, retry completes | **PASS** |
| 6 | retry after lease expiry: stale token refused, retry completes | **PASS** |
| 7 | failure in a superseded rollup cannot fail the new owner's job | **PASS** |

`python -m pytest tests/test_rollup_ownership.py` with
`WORKER_TEST_PG_URL=postgresql+psycopg://.../p1test` -> **7 passed, 1 xfailed,
exit 0** (`evidence-final-closure-84046b2/f02a-rollup-ownership-release-image.log`).

**New finding F-02a-1 - OPEN, not fixed.** `run_rollup` ignores the boolean
returned by its fenced `save()` and appends `"Rollup completed"` regardless
(`rollup.py:243-256`). The job row is protected - the guarded UPDATE matches
zero rows - but the event feed then reports a completion that never happened.
`runner.py` handles this correctly (`"Publication refused: lease superseded"`
when its guarded publish returns false), so the omission is specific to the
rollup path. The failure branch has the same shape: a superseded rollup appends
`"Failed: ..."` and may send a failure alert to the schedule owner while another
worker owns the job. A strict-xfail test
(`test_a_refused_completion_must_not_announce_success`) encodes the required
behaviour and fails today. No source change was made after the finding.

**Observation F-02a-2 - no fix.** The aggregation spec is validated *after* the
claim and outside the `try` (`rollup.py:154-162`). An invalid spec raises
through `run_rollup` to `tasks.py`, whose `_mark_failed` deliberately only
touches `queued` rows, so the row stays `running` until the lease expires and
the retry cap is reached. Seen live in the smoke run (attempts at 13:15:45 and
13:17:30 UTC). Reachability is limited because the API validates the spec when
the job is created.

### F-04 - downgrade atomicity: IMPLEMENTED, eight concurrency scenarios executed

Implementation (unchanged): `LOCK TABLE job_dispatch_outbox IN ACCESS EXCLUSIVE
MODE` at `api/migrations/versions/0034_job_dispatch_outbox.py:82`, taken before
both obligation counts and held until the transaction ends.

`f04_concurrency.py` drives the migration's **real** `upgrade()`/`downgrade()`
against a fresh disposable PostgreSQL 16 database with separate connections and
real waiting:

| # | Scenario | Result |
|---|---|---|
| 1 | dispatcher committed before the lock is taken | **PASS** |
| 2 | downgrade waits for an in-flight dispatcher, then counts its row | **PASS** |
| 3 | dispatcher inserts after the lock is held - blocked, then preserved | **PASS** |
| 4 | worker claims during the lock window - blocked, then preserved | **PASS** |
| 5 | pending row prevents the drop | **PASS** |
| 6 | leased row prevents the drop | **PASS** |
| 7 | dead row for a non-terminal job prevents the drop (terminal-dead does not) | **PASS** |
| 8 | fully drained outbox allows the drop | **PASS** |

`python /src/f04_concurrency.py` in `last9-api:release-1-final-84046b2-fix3` ->
**8 passed, exit 0** (`evidence-final-closure-84046b2/f04-pg16-concurrency.log`).

Recorded per scenario: isolation level (`read committed`), the SQL captured by a
driver event (LOCK, both counts, both index drops, the table drop), lock
acquisition order (ACCESS EXCLUSIVE -> counts -> refuse/drop), blocking
behaviour (`pg_stat_activity.wait_event_type = Lock`, with backend pids), final
outbox state, and the downgrade verdict. Scenarios 3 and 4 execute the
migration's exact statement sequence with a deliberate hold, because the real
function refuses or drops within ~20 ms; that substitution is stated in the log.

### F-13 - timer-driven heartbeat: IMPLEMENTED, real 70 s blocked call executed

`f13_blocked_extraction.py` runs the real `run_extraction` and the real
`LeaseKeeper` against disposable PostgreSQL 16, with `iter_extraction` replaced
by a controlled blocking double that yields no rows and never calls
`on_chunk_complete` until released. **This proves heartbeat independence, not
Last9 integration** - no non-production credential exists.

| Check | Result |
|---|---|
| A: claimed with a 60 s lease | **PASS** |
| A: reconciler at ~30 s does not fence the blocked healthy worker | **PASS** (`expired=0`) |
| A: lease still owned and unexpired after 70 s with zero rows delivered | **PASS** (lease moved 13:12:51.495 -> 13:13:51.536 UTC) |
| A: runner completes after release | **PASS** (completed, 0 rows, finished_at set) |
| A: keeper shuts down after the job turns terminal | **PASS** |
| A: no failure or fencing event written | **PASS** |
| B: second job claimed | **PASS** |
| B: keeper stops itself when the token is superseded | **PASS** |
| B: superseded runner cannot publish or fail the new owner's job | **PASS** |

Actual blocked duration: **70.0 s** of wall clock against a 60 s lease. The
reconciler ran at ~30 s and ~70 s and reported `expired=0` both times, so the
renewal can only have come from the keeper's own tick while no row was
delivered. Command -> **9 passed, exit 0**
(`evidence-final-closure-84046b2/f13-blocked-extraction.log`).

The remaining keeper sub-cases (superseded token, database error, terminal job,
worker shutdown) are the four tests in `worker/tests/test_lease_keeper.py`; they
pass in the release image, both in the full suite and in the targeted run.

### Release image verification

Provenance (`evidence-final-closure-84046b2/provenance-84046b2.txt`): all ten
inspected files match the commit. Eight are byte-identical; two
(`worker/app/rollup.py`, `worker/app/runner.py`) are identical after CRLF to LF
normalisation (`diff_lines=0`), because the build host has `core.autocrlf=true`
and the images were built from the Windows working tree. No content differed.

Tests run **inside the release images**, application code read from the image,
only the test directory mounted, pytest installed at run time (no image rebuilt
or modified):

| Suite | Command | Result |
|---|---|---|
| Worker (image) | `python -m pytest tests` | **277 passed, 1 skipped, 1 xfailed, exit 0** |
| Worker, PG scenario | `WORKER_TEST_PG_URL=... pytest tests/test_rollup_ownership.py` | **7 passed, 1 xfailed, exit 0** |
| API (image) | `python -m pytest tests` | **289 passed, exit 0** |
| Targeted regression (9 files) | see log | **78 passed, 1 xfailed, exit 0** |

The single skip is scenario 3 of the ownership file, which needs
`WORKER_TEST_PG_URL`; it is executed, and passes, by the PG run above.

Runtime smoke using release images only: `alembic upgrade head` on a fresh
database applied 0023 -> 0034 (exit 0); API `/health` -> `{"status":"ok"}`;
`/ready` -> postgres ok, redis ok; `/health/dispatch` -> ok, beat heartbeat
11.9 s, worker online 1; beat guard and worker started; a synthetic rollup job
inserted with an outbox row was published by beat, executed by the worker and
completed in 38 ms with `job_dispatch_outbox.status = published`.
Logs: `smoke-job-final.txt`, `smoke-api.log`, `smoke-beat.log`.

The first two smoke attempts failed on the synthetic fixture itself (the
aggregation regex omitted the `BU` group the spec grouped by), not on release
code; that is what exposed observation F-02a-2.

### Evidence discrepancies found while verifying (for the reviewer)

Two inconsistencies in the frozen package were found while verifying it. Neither
was corrected: the package is historical evidence, and a release candidate must
not be silently rewritten.

1. **Manifest self-hash does not reproduce.** Every one of the 30 entries in
   `release-artifacts/release-1-final-84046b2-fix3/checksums.sha256` verifies
   against its file, and `checksums.sha256` itself hashes to
   `44077dbeec9d878aa1cc2c69525df585a3d0162b01ac4fece3b5d8bbf1b2608d`. The value
   recorded earlier (`7A207A3B...8E4A`) is not reproducible from the file as
   stored, under CRLF, LF or sorted order. Treat the per-file entries as
   authoritative and the aggregate value as unverified.
2. **`BUILD_LOG.md` names an earlier tag.** The package's build log records
   `last9-api:release-1-final-9aac582-fix2` and
   `last9-worker:release-1-final-9aac582-fix2`, while the manifest, the tags
   inspected in this pass and the verified digests are
   `release-1-final-84046b2-fix3` (`78f7f987...396bb`, `c36ac27f...d8917`). The
   image contents match commit `84046b2` (see the provenance file), so the log
   text is stale rather than the images being wrong.

### Still outstanding (unchanged by this pass)

- **F-02a-1** false completion event and possible false failure alert from a
  superseded rollup - open, no fix applied.
- **Last9 extraction not tested** (GB-08, no credential).
- **Production web image blocked** (GB-05, no approved API URL).
- Backup/restore at volume (GB-02/03), migration rehearsal at volume (GB-04),
  real alert channel (GB-07), deployment rehearsal (GB-09), on-call (GB-10).
- Single-person control (RK-03); no independent reviewer named.
- Commit not pushed; release packages not committed.
- Deferred advisories: starlette 0.41.3 (7), ecdsa 0.19.2 (1),
  python-jose PYSEC-2025-185 (no fix).

**No independent human review has been completed. This analysis is the
implementation author's and is not independent approval. The package is prepared
for a separate reviewer.** Gate B: **NOT GRANTED**.

---

## F-02a-1 correction 2026-11-15 (working tree, uncommitted)

**Status: F-02a-1 is FIXED in the working tree; it is not committed and not in
any image.** This section supersedes the "OPEN, not fixed" status above for the
source tree only.

File changed: `worker/app/rollup.py` (the only application file).

Correction: all three fenced `save()` call sites now capture the boolean and gate
their narration on it.

- completion path: the `Rollup completed ...` event and the `Skipped job ...`
  events are written only when the guarded UPDATE applied;
- merge-failure path: the `Failed: ...` event and the schedule-owner alert are
  written only when the guarded UPDATE applied;
- incomplete-spec path: the same treatment. This is the third site of the same
  defect — it was not named in the closure report but had the identical shape,
  so leaving it would have left F-02a-1 half-fixed.

No claim, transaction, fencing, retry or artifact semantics changed.

Tests (`worker/tests/test_rollup_ownership.py`, 13 tests):

| Test | Result |
|---|---|
| seven ownership scenarios (unchanged, incl. the PostgreSQL 16 race) | **PASS** |
| superseded rollup cannot announce success | **PASS** |
| superseded rollup cannot announce failure | **PASS** |
| superseded rollup cannot send a failure alert | **PASS** |
| superseded rollup with an incomplete spec cannot fail the new owner's job | **PASS** |
| current owner can still announce success | **PASS** |
| current owner can still announce a genuine failure and alert | **PASS** |

`python -m pytest tests/test_rollup_ownership.py` -> **13 passed, exit 0**.
Full worker suite -> **284 passed, exit 0**. The strict xfail was removed only
after the corresponding test passed against the corrected source; the same tests
fail against the uncorrected `84046b2` image (4 failed, 9 passed), which is what
makes them evidence rather than decoration.

Evidence: `release-artifacts/evidence-final-closure-84046b2/f02a1-rollup-ownership-source.log`,
`.../worker-suite-source-after-f02a1.log`, and the pre-fix run
`.../f02a1-rollup-ownership-prefix-image.log`.

**Image consequence.** The candidate images still contain commit `84046b2` and
therefore do not include this correction. They are stale with respect to the
working tree, and every image-based result recorded above remains true of
`84046b2` only. Rebuilding and republishing images was not authorised in this
pass, so any image-based review or deployment must use a later build.

**Still not done:** commit, push, PR, image rebuild, deployment, Gate B. Every
reviewer checkbox, name, date and signature in this document remains blank, and
Gate B remains NOT GRANTED.

---

## Authoritative candidate reconciliation - 7f2ac46-fix4 (2026-11-15)

This section is the current, authoritative statement. It supersedes every
candidate identity above, including the earlier "fixed in the working tree only"
status of the F-02a-1 correction.

### Candidate

| Item | Value |
|---|---|
| Branch | `release-1/p1-dispatch` |
| Commit | **`7f2ac46`** = `7f2ac468e21de16e2feee9f2bd81b8fe0669c89b` |
| Parent | `84046b2` |
| `main` | `6719568f` - unchanged |
| Ahead of main | 5 commits |
| Pushed | **No** - `origin/release-1/p1-dispatch` is `78fb0a7` |
| Worker image | `last9-worker:release-1-final-7f2ac46-fix4` = `sha256:f96fac9f2d16a0b3141578111cc110313f6de5488dcc6f80868767fbfe224fbb` |
| Worker config digest | `sha256:4a3ea343a668f789e60451ae128a9e735807318c783ae7441b0f73ec9d8a1be3` |
| API image | `last9-api:release-1-final-84046b2-fix3` = `sha256:78f7f987cf3bc5074e6f3aeb9b08c3816bf4e18d7ddb57b3b4772de21c6396bb` - not rebuilt |
| Web image | `last9-web:release-1-final-78fb0a7` = `sha256:6a6489dcc5d3d9ef76ef5c6cc0cc4ab11faa8fac376895a14f9974b0fd660ab1` - unchanged, still built with `http://localhost:8000` |
| Package | `release-artifacts/release-1-final-7f2ac46-fix4/` - 31 files (29 checksummed + `checksums.sha256` + `CHECKSUMS_SHA256.txt`) |
| Package checksums | `checksums.sha256` = `B6E5838031703811AD5A2010AE36784604384882A261E70DEA21CB91BBA8ABEA`; verified with an independent Python implementation: **PASS** |
| Build input | `git archive 7f2ac46` (tracked files only, LF) |
| Gate B | **NOT GRANTED** |

The worker tag resolves to a **manifest list** (BuildKit attestations), so its
ID is the index digest; the `84046b2` worker was a classic single-manifest image.
Both are addressed by digest. Provenance is commit-to-image verification, not a
claim of bit-identical rebuilds: the base image (`python:3.12-slim`) is a
floating tag and dependencies are pinned only at the top level.

### Findings

| ID | Status |
|---|---|
| F-02a | **CORRECTED** (`84046b2`), verified in `7f2ac46-fix4`: 7/7 ownership scenarios including the PostgreSQL 16 concurrent-claim race |
| F-04 | **CORRECTED** (`84046b2`), verified: 8/8 downgrade concurrency scenarios against the real `0034` migration on PostgreSQL 16, with `pg_stat_activity` confirming the waits |
| F-13 | **CORRECTED** (`84046b2`), verified: 9/9 including a real **70.0 s** blocked extraction; lease `13:58:27.097` -> `13:59:27.139` UTC; reconciler `expired=0` at ~30 s and ~70 s |
| F-02a-1 | **FIXED in the committed source (`7f2ac46`) and in the verified worker image.** All three fenced `save()` sites gate their events and alert on the write result |
| F-01 | corrected in `9aac582`; the renewal path it introduced is exercised by the F-13 evidence |

F-02a-1 detail: the completion event and gap events, the merge-failure event and
schedule-owner alert, and the incomplete-spec failure event and alert are now all
written only when the guarded UPDATE applied. No claim, transaction, fencing,
retry or artifact behaviour changed.

### Executed evidence for this candidate

| Check | Result |
|---|---|
| Worker suite, inside the built image | **284 passed**, exit 0 |
| Rollup ownership | **13 passed**, exit 0 |
| Targeted regression (9 files) | **84 passed**, exit 0 |
| F-13 blocked extraction | **9/9**, 70.0 s block, exit 0 |
| API suite, retained image | **289 passed**, exit 0 |
| F-04 downgrade concurrency, PostgreSQL 16 | **8/8**, exit 0 |
| Frontend / TypeScript | 8 passed / exit 0 |
| Source-to-image provenance | 37/37 application and 25/25 test files identical, 0 mismatches |
| Dependency inventory | identical to `84046b2` (0 differing lines) |
| Disposable smoke stack | `/health` ok, `/ready` ok, `/health/dispatch` ok, synthetic rollup completed in 0.048 s, outbox `published` |
| Negative control on the `84046b2` worker image | **4 failed, 9 passed** - the four F-02a-1 detection tests fail as intended |

The strict xfail was removed only because the F-02a-1 test passes on `7f2ac46`;
the same tests fail on the uncorrected image, which is what makes them evidence
rather than an assertion restated.

### Migration 0034 package-copy finding and its resolution

The frozen package `release-1-final-84046b2-fix3` shipped a **stale copy** of
`0034_job_dispatch_outbox.py`: 2,309 bytes, SHA-256
`5DFC32753A84696B8A471286467CD38FD871C8313426879474A7427975F7AEEC`, **without**
the `LOCK TABLE ... ACCESS EXCLUSIVE` statement. The commit `84046b2` and the
running API image both contained the lock; only the package copy was stale, and
that package's own checksums were consistent with the stale file. It was found
by comparing package files with `git show 84046b2:...`, not by inspection of the
package alone.

Resolution in `7f2ac46-fix4`: all four migration copies are taken from
`git show 7f2ac46:...` and compared with the commit. The correct `0034` is
3,693 bytes, SHA-256
`550ED5AEA4EEBB0ECEEAEE1D84E5B3A1DB30F3FBDD5A5D7AA289230860395F0B`, with the lock
at line 82, and it is byte-identical to the commit. The `fix3` package is
preserved unmodified as historical evidence and remains inconsistent with its own
commit; it must not be used as the migration reference.

### Still open - unchanged by this candidate

- **GB-08**: live Last9 extraction **NOT TESTED** - no non-production credential.
  The 70 s block used a controlled double and proves heartbeat independence only.
- **GB-01**: no independent reviewer named.
- **GB-05**: web image built with `http://localhost:8000`.
- **GB-02/03/04**: production-scale backup, restore and migration rehearsal.
- **GB-07/09/10**: real alert delivery, deployment rehearsal, on-call.
- **RK-19**: aggregation spec validated after the claim - **OPEN**, no evidence.
- **RK-20**: `completed_without_pointer` flags source-less rollups - **OPEN**, no evidence.
- Deferred advisories: starlette 0.41.3 (7), ecdsa 0.19.2 (1), python-jose PYSEC-2025-185 (no fix).
- Commit not pushed; package and evidence untracked (GX-04).

### Approval boundary

Technical evidence is not independent approval. No reviewer has been named, and
every reviewer name, date, signature and approval checkbox remains blank. No
production readiness is claimed. **Gate B: NOT GRANTED.**

---

## Non-production acceptance - 2026-11-15 (attested, unverified)

The product owner reports a successful manual acceptance run against a
non-production Last9 environment (login, credential test, region/index,
manual and scheduled extraction, download and validation, error handling and
retry). The attestation is recorded in
`RELEASE_1_NON_PRODUCTION_ACCEPTANCE_REPORT.md`.

The report could not be marked COMPLETE because no artifact from the run was
supplied or found: no job IDs, timestamps, row counts, screenshots, exported
CSV, log excerpts, or acceptance database/containers. All twelve use cases are
recorded there as **ATTESTED, not verified**.

This does not change any finding status in this report. F-02a, F-04, F-13 and
F-02a-1 remain as documented; extraction integration remains owner-attested and
technically unproven (GB-08).

No reviewer has been named and no signature is recorded. Gate B remains
**NOT GRANTED**.

---

## Non-production acceptance evidence - 2026-11-15T14:45Z

A real acceptance record now exists and was checked against the running system:
job **976**, completed, **15,423 rows**, 3/3 chunks, window 12:39:52–14:39:52 UTC,
finished 14:40:04.745; worker task succeeded in 8.0136 s; the exported archive
(309,505 bytes) was opened and parsed — 15,423 data rows, correct header, all
timestamps inside the window. Full detail is in
`RELEASE_1_NON_PRODUCTION_ACCEPTANCE_REPORT.md`.

**It was produced by the pre-Release-1 application, not by this candidate.**
The stack was `E:\last9_web_app` at `98d26ca`, dev images built 2026-11-12,
database schema **0031** (no lease, owner, completion-state or outbox columns).
The candidate is `7f2ac46`, schema `0034`, worker `f96fac9f…`, and has not run a
real extraction.

Consequences for this report:

- A4–A8 and A12 are **verified for the base application**; they do not
  constitute candidate acceptance.
- A9 (schedule), A10 (failure) and A11 (retry) are **not evidenced at all** — no
  schedule exists and no failed job was recorded.
- GB-08 is **PARTIAL**: the Last9 external dependency is proven; the candidate's
  runner path is not.

No finding in this report changes. No reviewer is named. Gate B remains
**NOT GRANTED**.

---

## Non-production acceptance - COMPLETE (candidate verified) - 2026-11-15T15:00Z

The candidate was exercised end to end against real Last9 data: commit
`7f2ac46`, schema `0034`, worker `f96fac9f…`, API `78f7f987…`, on a disposable
stack that was destroyed afterwards.

- login and credential test (`ok=true`, `valid`, `Connection successful`);
- manual extraction **job 1**: 14:58:35.508 → 14:58:39.092, **6,923 rows**, 1/1
  chunk, no error;
- download validated: 325,987-byte archive, **6,923 data rows**, header ok, every
  timestamp inside the requested window, count equals `rows_written`;
- scheduled run **job 2**: **7,192 rows**, completed 14:59:37.268;
- hard failure **job 3** (`token refresh returned HTTP 400`) and retry
  **job 4** failing identically;
- worker, beat and API logs captured.

A non-existent physical index was also tried: it yields the designed **partial**
completion with a recorded gap, not a hard failure.

The acceptance report is marked COMPLETE; GB-08 is PASS (technical). This does
not alter any finding in this document, does not name a reviewer, and does not
authorise production. **Gate B remains NOT GRANTED.**
