# Release 1 — Independent Risk Register

> **Authoritative candidate: `7f2ac46` (`7f2ac468e21de16e2feee9f2bd81b8fe0669c89b`).**
> Worker image `last9-worker:release-1-final-7f2ac46-fix4`
> (`sha256:f96fac9f…f224fbb`), package
> `release-artifacts/release-1-final-7f2ac46-fix4/`.
> Everything below is the historical `78fb0a7` → `84046b2` review record; the
> reconciliation at the end of this document supersedes its candidate identity.
> Reviewer fields remain blank and Gate B remains NOT GRANTED.


Commit reviewed: `78fb0a7`. Prepared by the implementation author as critical
input to an independent review, not as an independent assessment. No risk is
marked accepted; acceptance requires a named authorised owner.

| ID | Risk | Area | Severity | Likelihood | Evidence | Existing mitigation | Residual | Required action | Owner | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| RK-01 | Heartbeat not wired into runner: lease expires 60 s into any real job; reconciler fences and redispatches a live worker | 4 | **Critical** | **High** | `runner.py` has no `Heartbeat`/`progress` reference; `db.py:241` TTL 60 s; `runner.py:546` event-only | none | Duplicate execution, wasted work, false `retry_exhausted` | Wire `Heartbeat`, call `.progress()` at chunk and event boundaries, stop on lease loss; regression test at 5× TTL | Eng | **OPEN** |
| RK-02 | Live Last9 extraction never tested | 12 | **High** | High | `INTEGRATION_EVIDENCE.md`; no credential | synthetic jobs only | First production job could fail on auth, pagination, rate limits or S3 | Supply non-prod credential and run the 14-step extraction test | Platform | **OPEN** |
| RK-03 | Single-person control: implementer = reviewer = custodian = security certifier = Gate A approver | 12 | **High (governance)** | Certain | closure sheet, register §13 | documented | No independent control has validated anything | Name an independent reviewer; complete the checklist | Project Owner | **OPEN** |
| RK-04 | Production-scale backup and restore unproven | 12 | **High** | Medium | disposable-only evidence | runbook exists | Restore may fail or exceed RTO at real size | GB-02/GB-03 with production access | Production owner | **OPEN** |
| RK-05 | `db.update_job` unfenced, still used for job state (`rollup.py:85,96,153,186,228`; `tasks.py:128,192,198,215`) | 3 | **High** | Medium | grep at reviewed commit | fenced helpers exist but not used here | A stale worker could overwrite state via these paths | Trace each caller; fence them or prove no race | Eng | **OPEN** |
| RK-06 | Production web image not built: `NEXT_PUBLIC_API_BASE_URL` is `http://localhost:8000` | 11 | **Blocking** | Certain | `BUILD_LOG.md` | none | Frontend cannot reach the production API | Supply URL; rebuild | Production owner | **OPEN** |
| RK-07 | Production migration timing unknown (toy-size only) | 8 | Medium | Medium | 4.2 s on empty DB | lock/statement timeouts documented | Long lock could block the app | GB-04 rehearsal at volume | Production owner | **OPEN** |
| RK-08 | Drain gates not atomic with downgrade | 8 | Medium | Medium | runbook §5 | four gate queries | Obligation created between gate and downgrade is lost | Stop API and dispatcher before gating; re-check after | Eng | **OPEN** |
| RK-09 | starlette 0.41.3 — 7 advisories | 11 | Medium | Low-Med | `SECURITY_RESCAN.md` | none | ASGI-layer exposure | FastAPI 1.x upgrade as a separate change | Security Owner | **DEFERRED** |
| RK-10 | ecdsa 0.19.2 — PYSEC-2026-1325, no fix | 11 | Low-Med | Low | scan | none | only if ECDSA JWTs are enabled | Remove with python-jose replacement | Security Owner | **DEFERRED** |
| RK-11 | python-jose PYSEC-2025-185, no fix | 11 | Low-Med | Low | scan | none | JWT handling edge case | Replace library | Security Owner | **DEFERRED** |
| RK-12 | Fenced write failures ignored in runner loop | 3 | Medium | Medium | `runner.py` checkpoint updates | fence prevents corruption | worker burns CPU on a lost lease | Check return values; abort on false | Eng | **OPEN** |
| RK-13 | Orphaned attempt artifacts never cleaned | 7 | Low | High over time | `artifacts.py` has no cleanup | retention job is legacy-only | Disk growth | Add attempt cleanup | Eng | **OPEN** |
| RK-14 | Real alert channel untested | 12 | Medium | High | no channel in repo | endpoint exists | Failures go unnoticed | GB-07 + one delivered alert | Production owner | **OPEN** |
| RK-15 | Release artifacts untracked (packages only local) | 12 | Medium | Medium | `git status` | commit holds source | Evidence lost with the machine | Commit or archive packages | Project Owner | **OPEN** |
| RK-16 | Shared-volume resume while a fenced old worker may still hold files open | 6/7 | Low-Med | Low | fence + shared path | token fence stops writes | interleaved file state on resume | Confirm truncate-before-append under kill | Eng | **OPEN** |

## Blocking set

RK-01, RK-02, RK-03, RK-05, RK-06 block Gate B. RK-04, RK-07, RK-14 block
deployment even if Gate B were granted.

## Acceptance boundaries

- RK-09/10/11 may be accepted by the Security Owner with a review date.
- No technical risk may be accepted on the owner's behalf by engineering.
- RK-03 cannot be accepted; it can only be remediated by an independent review.

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

| RK-17 | Renewal is yield-driven: a blocking extraction call longer than the TTL expires the lease and a healthy worker is fenced | 4 | **High** | Medium | `runner.py:695-704` | fence prevents corruption | work lost and redispatched mid-request | timer-driven heartbeat, or accept with impact | Eng | **OPEN** |

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

### Risk register update for the closure pass

Entry IDs continue from RK-17. No earlier row is edited or deleted. Every new
entry is unassigned: no risk acceptance has been recorded or implied.

| ID | Risk | Area | Severity | Likelihood | Evidence | Residual | Required action | Owner | Status |
|---|---|---|---|---|---|---|---|---|---|
| RK-18 | F-02a-1: a superseded rollup appends `Rollup completed` after its fenced completion matched zero rows, and its failure branch can append `Failed: ...` and alert the schedule owner | 3 | Medium | Medium | `rollup.py:196-224`, `:243-256`; strict-xfail test `test_a_refused_completion_must_not_announce_success` | misleading job feed; a false failure email during a takeover window | branch on the fenced write's result, as `runner.py` already does; or accept with the impact recorded | Unassigned - no acceptance recorded | **OPEN** |
| RK-19 | F-02a-2: the aggregation spec is validated after the claim and outside the try, so an invalid spec leaves the row `running` until the lease expires and the retry cap is reached | 3 | Low | Low | `rollup.py:154-162`; smoke attempts 13:15:45 / 13:17:30 UTC | churn and delay, no data loss | validate before the claim, or route construction through the failure path | Unassigned | **OPEN** |
| RK-20 | OBS-01: `completed_without_pointer_24h` counts `status=completed AND output_file_path IS NULL`, so a rollup with no raw sources raises a warning | 11 | Low | Medium | `api/app/dispatch_health.py`; smoke run | alert noise on legitimate rollups | count `summary_file_path`/`counts_file_path` too, or exclude rollups | Unassigned | **OPEN** |
| RK-21 | Dedicated rollup ownership tests were missing | 3 | - | - | seven scenarios executed on SQLite + PG16 | - | none | - | **CLOSED BY EVIDENCE** |
| RK-22 | PostgreSQL downgrade concurrency proof was missing | 8 | - | - | eight scenarios executed against the real migration on PG16 | operational drain procedure still required | none technical | Production owner | **CLOSED BY EVIDENCE** |
| RK-23 | Wall-clock blocked-extraction proof was missing (F-13 / RK-17) | 4 | - | - | 70.0 s block, lease renewed 13:12:51 -> 13:13:51 UTC | the Last9 HTTP path itself remains unproven | GB-08 | Platform owner | **CLOSED FOR HEARTBEAT, OPEN FOR LAST9** |

Still open from the table above, with unchanged severity:

| Existing ID | Risk | Status after this pass |
|---|---|---|
| RK-02 | Live Last9 extraction never tested | **OPEN** - no credential; the 70 s block used a controlled double |
| RK-03 | Single-person control; no independent reviewer | **OPEN** - unchanged, cannot be self-remediated |
| RK-04 | Production-scale backup and restore unproven | **OPEN** |
| RK-05 | `db.update_job` unfenced callers | **PARTIAL** - the rollup callers are fenced; `runner.py:214`, `scheduler.py:239`, `tasks.py:130,194,200,217` remain, classified administrative |
| RK-06 | Production web image built with `http://localhost:8000` | **OPEN (blocking GB-05)** |
| RK-07 | Production migration timing unknown | **OPEN** - upgrade 0023->0034 ran on a fresh PG16 in this pass, still at toy size |
| RK-09 / RK-10 / RK-11 | starlette 0.41.3 (7), ecdsa 0.19.2 (1), python-jose PYSEC-2025-185 (no fix) | **DEFERRED** |
| RK-12 | Fenced write failures ignored in the runner loop | **OPEN** |
| RK-13 | Orphaned attempt artifacts never cleaned | **OPEN** |
| RK-14 | Real alert channel untested | **OPEN** |
| RK-15 | Release artifacts untracked | **OPEN** - the new evidence directory is untracked as well |

### Blocking set after this pass

- **Blocking Gate B:** RK-02 (GB-08), RK-03 (GB-01), RK-06 (GB-05).
- **Condition for acceptance:** RK-18 must be fixed or explicitly accepted by a
  named owner before Gate B, because it makes the job feed state something that
  did not happen.
- **Blocking deployment, not Gate B:** RK-04, RK-07, RK-14.
- RK-09/10/11 may only be accepted by the Security Owner with a review date.
- No technical risk may be accepted on the owner's behalf by engineering.

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


### RK-18 status update after the correction

| ID | Risk | Status |
|---|---|---|
| RK-18 | F-02a-1 false completion event / false failure alert from a superseded rollup | **CLOSED BY EVIDENCE (working tree)** - all three fenced save sites gate their events and alert on the write result; 6 dedicated tests, 13/13 in the file, 284/284 worker suite. Closure is uncommitted and not present in the `84046b2` images. |

The earlier RK-18 row is preserved unedited as the pre-correction record. RK-19
and RK-20 remain open and untouched by this pass.

Blocking set is now: RK-02 (GB-08), RK-03 (GB-01), RK-06 (GB-05) block Gate B;
RK-04, RK-07, RK-14 block deployment. RK-18 is no longer a condition for
acceptance in the source tree, but an image built from `84046b2` still carries
it.

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


### Risk register status after 7f2ac46

| ID | Status after this candidate | Basis |
|---|---|---|
| RK-18 | **CLOSED BY EVIDENCE** - F-02a-1 is fixed in commit `7f2ac46` and in the verified worker image | 6 dedicated tests, 13/13 ownership, 284/284 suite, and 4 failed / 9 passed on the `84046b2` image |
| RK-19 | **OPEN** - no new evidence | rollup still validates its aggregation spec after the claim |
| RK-20 | **OPEN** - no new evidence | the gauge still flags rollups with no raw sources |
| RK-21 / RK-22 / RK-23 | remain **CLOSED BY EVIDENCE** | rollup tests, downgrade concurrency, blocked extraction |
| RK-24 | **NEW - OPEN**: release packages are assembled by hand and can drift from the commit. The `fix3` package's stale `0034` copy is proof. Mitigated for `fix4` by copying migrations from `git show` and verifying every file against the commit; the process risk itself is not closed, no owner is assigned and no acceptance is recorded. | package file differs from `git show 84046b2:...` |

Blocking set unchanged: RK-02 (GB-08), RK-03 (GB-01) and RK-06 (GB-05) block
Gate B; RK-04, RK-07 and RK-14 block deployment. RK-18 is no longer a condition
for acceptance of the source or of the `fix4` image, but an image built from
`84046b2` still carries the defect and must not be deployed.

---

## RK-02 status - 2026-11-15 (owner attestation, evidence pending)

RK-02 is "live Last9 extraction never tested". The product owner now reports that
the application passed a manual non-production acceptance run, including a
downloaded and validated CSV. The attestation is recorded in
`RELEASE_1_NON_PRODUCTION_ACCEPTANCE_REPORT.md`.

RK-02 therefore changes basis but **not status**:

- **ATTESTED** - the owner states A1-A12 passed on real Last9 data.
- **UNVERIFIED** - no job IDs, timestamps, row counts, screenshots, exported CSV
  or log excerpts were supplied or found in this workspace, and no acceptance
  containers/volumes/database exist to inspect.

**RK-02 remains OPEN.** It closes when the acceptance evidence listed in section
5 of that report is supplied and checked. No risk acceptance is recorded, and no
owner is named for that acceptance beyond the product owner's statement.

RK-19, RK-20 and RK-24 are untouched by this attestation and remain OPEN.

---

## RK-02 evidence update - 2026-11-15T14:45Z

RK-02 ("live Last9 extraction never tested") has moved from attestation to
**partial evidence**:

- job 976 completed with 15,423 real rows, 3/3 chunks, in 8 s; the exported
  archive was parsed and its rows all fall inside the requested window
  (detail in `RELEASE_1_NON_PRODUCTION_ACCEPTANCE_REPORT.md`);
- the Last9 org/index/credential path works from this host:
  credential 9 (`Singapore`, `evergentapse1`), index 4 (`UMS_singapore`).

**However**, the run used the pre-Release-1 application (`E:\last9_web_app`,
schema `0031`, dev images from 2026-11-12), not the candidate (`7f2ac46`,
schema `0034`, worker `f96fac9f…`). Scheduled extraction, failure handling and
retry are also unevidenced.

**RK-02 remains OPEN.** Severity is unchanged; likelihood of an extraction
failure in the candidate is now materially lower because the external
dependency is proven. Closure requires the candidate run described in the
acceptance report.

RK-19, RK-20 and RK-24 remain OPEN and are unaffected.

---

## RK-02 closure - 2026-11-15T15:00Z

RK-02 ("live Last9 extraction never tested") is **CLOSED BY EVIDENCE**.

On the candidate (`7f2ac46`, schema `0034`, worker `f96fac9f…`) a real extraction
completed with **6,923 rows**, and the downloaded archive was validated (6,923
data rows, header ok, all timestamps inside the requested window, count equals
`rows_written`). A scheduled run produced **7,192 rows**. An invalid credential
failed with a clear message and the retry failed identically. Detail:
`RELEASE_1_NON_PRODUCTION_ACCEPTANCE_REPORT.md` and
`evidence-final-7f2ac46-fix4/candidate-*`.

Residual scope, not risk status: the candidate web UI (GB-05), S3/BigQuery
destinations, and multiple orgs/regions were not exercised. RK-19, RK-20 and
RK-24 are unchanged and remain OPEN.
