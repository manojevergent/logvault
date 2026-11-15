# Release 1 — Gate B Evidence Register

> **Authoritative candidate: `7f2ac46` (`7f2ac468e21de16e2feee9f2bd81b8fe0669c89b`).**
> Worker image `last9-worker:release-1-final-7f2ac46-fix4`
> (`sha256:f96fac9f…f224fbb`), package
> `release-artifacts/release-1-final-7f2ac46-fix4/`.
> Everything below is the historical `78fb0a7` → `84046b2` review record; the
> reconciliation at the end of this document supersedes its candidate identity.
> Reviewer fields remain blank and Gate B remains NOT GRANTED.


Commit reviewed: `78fb0a7`. Gate B is **NOT GRANTED**. IDs GB-01..GB-11 are
preserved exactly as previously defined; no meaning or numbering changed.

| Gate ID | Requirement | Evidence expected | Evidence available | Verification | Gap | Owner | Status |
|---|---|---|---|---|---|---|---|
| GB-01 | Independent technical review | signed checklist from a named reviewer | `RELEASE_1_INDEPENDENT_REVIEW_REPORT.md` (author's self-critical analysis, **not independent**), `RELEASE_1_REVIEW_CHECKLIST.md` (unmarked) | Not verified — no independent reviewer named | A human reviewer must perform and sign | Reviewer (unnamed) | **PENDING** |
| GB-02 | Production backup | `pg_dump` log + integrity listing | disposable dump only (439 ms / 51,978 bytes) | Not verified for production | Production access approval | Production owner | **PENDING** |
| GB-03 | Verified restore at scale | restore log, row-count comparison, RTO/RPO | disposable restore (586 ms, counts matched) | Not verified at production volume | Depends on GB-02 | Production owner | **PENDING** |
| GB-04 | Migration rehearsal at volume | per-revision timings, lock report | 4.2 s on an empty disposable DB | Not verified at volume | Representative dataset | Production owner | **PENDING** |
| GB-05 | Production web image | image ID + provenance, built with approved URL | candidate built with `http://localhost:8000` | **Not production-configured** | Approved `NEXT_PUBLIC_API_BASE_URL` | Production owner | **BLOCKED** |
| GB-06 | Image distribution | transfer log, verified IDs after load | none — images local only | Not performed | Registry or transfer authorisation | Production owner | **PENDING** |
| GB-07 | Monitoring connected to real alert channel | channel config + delivery record | `/health/dispatch` exists; no channel defined in repo | Not verified | Alert channel + escalation names | Production owner | **PENDING** |
| GB-08 | Last9 extraction test | test log from a non-prod credential | none | **NOT TESTED** | Credential + network access | Platform owner | **BLOCKED** |
| GB-09 | Deployment rehearsal | rehearsal log | none at production shape | Not performed | Window | Production owner | **PENDING** |
| GB-10 | On-call and escalation | named list | none | Not defined | Staffing decision | Production owner | **PENDING** |
| GB-11 | Gate B decision | signed authorisation after GB-01..GB-10 | none | **NOT GRANTED** | All of the above | Production owner | **NOT GRANTED** |

## Additional requirements discovered during review

Not in the original register, reported separately and not renumbered:

| ID | Requirement | Why | Status |
|---|---|---|---|
| GX-01 | Fix F-01 (heartbeat not wired) and add the lease-lifetime test | the release's central guarantee does not hold in the real runner | **OPEN — blocking** |
| GX-02 | Trace and fence `db.update_job` job-state callers (F-02) | unfenced writes bypass the ownership model | **OPEN — blocking** |
| GX-03 | Define the drain-gate/downgrade atomicity procedure (F-04) | gates are not atomic with the destructive step | **OPEN** |
| GX-04 | Commit or archive the release packages | evidence exists only on one machine | **OPEN** |

## Grant conditions

Gate B cannot be granted while GB-01 is PENDING, because GB-01 is the only
control that would catch GX-01 if the author's analysis is wrong.

A technical PASS from an independent reviewer is not Gate B approval. Gate B is a
separate production-authorisation decision by the authorised owner.

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

### GX-01 update

GX-01 (fix F-01 + lease test): **PARTIAL**. Chunk and row-flow renewal are
implemented and tested; the yield-driven gap (F-13) remains. Gate B should not
be granted while F-13 is unaccepted.

### Candidate identity

| Item | Value |
|---|---|
| Commit | `9aac582676d51df8c13d6817400b7b6c528d3207` |
| API image | `sha256:1fe369ff71f190aee64a31c805aebd333c66e76744a32e20c85cca8f033fcb25` |
| Worker image | `sha256:010008e2e6a8841431e147839ee698306077ac0e63c10cb04b08189ba7a80b87` |
| Web image | `sha256:6a6489dcc5d3d9ef76ef5c6cc0cc4ab11faa8fac376895a14f9974b0fd660ab1` |
| Package | `release-1-final-78fb0a7-fix1`, 30 files, manifest `AB4577EC…` |

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

### Gate B register update for commit 84046b2

IDs GB-01..GB-11 keep their original definitions and numbering. Only the
evidence references change. **No gate is granted by technical test completion.**

| Gate ID | Status for 84046b2 | Evidence reference |
|---|---|---|
| GB-01 | **PENDING** - no independent reviewer named | `RELEASE_1_INDEPENDENT_REVIEW_REPORT.md` (author analysis, not independent), `RELEASE_1_REVIEW_CHECKLIST.md` (unmarked), new logs in `evidence-final-closure-84046b2/` |
| GB-02 | **PENDING** - disposable dump only | unchanged |
| GB-03 | **PENDING** - disposable restore only | unchanged |
| GB-04 | **PENDING** - not at production volume | upgrade 0023->0034 exit 0 on a fresh disposable PG16 in this pass |
| GB-05 | **BLOCKED** - no approved `NEXT_PUBLIC_API_BASE_URL` | unchanged; web image untouched |
| GB-06 | **PENDING** - images local only | unchanged |
| GB-07 | **PENDING** - no real alert channel | `/health/dispatch` answered in the smoke run with beat heartbeat 11.9 s and worker online; no delivery record |
| GB-08 | **BLOCKED - NOT TESTED** | the F-13 block used a controlled double, which proves heartbeat independence only |
| GB-09 | **PENDING** | smoke stack ran against a disposable database, not a production-shaped rehearsal |
| GB-10 | **PENDING** | unchanged |
| GB-11 | **NOT GRANTED** | requires GB-01..GB-10 |

### Discovered-requirement updates

| ID | Requirement | Status after this pass |
|---|---|---|
| GX-01 | Fix F-01 and add the lease-lifetime test | **CLOSED (technical)** - timer-driven `LeaseKeeper`, 4 keeper tests, and a real 70.0 s blocked extraction with the reconciler reporting `expired=0` |
| GX-02 | Trace and fence `db.update_job` job-state callers | **PARTIAL** - rollup callers fenced and tested; administrative callers remain and are listed in RK-05 |
| GX-03 | Drain-gate/downgrade atomicity | **CLOSED (technical)** - ACCESS EXCLUSIVE before the counts; 8/8 PG16 scenarios, including a downgrade waiting out an in-flight dispatcher |
| GX-04 | Commit or archive the release packages | **OPEN** - packages and the new evidence directory are still untracked |
| GX-05 | F-02a-1: refused rollup completion still announces success | **OPEN** - recorded in the risk register as RK-18; no fix applied |

Gate B remains **NOT GRANTED**. A technical PASS from an independent reviewer
would still not be Gate B approval; GB-11 is a separate production-authorisation
decision by the authorised owner.

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


### GX-05 status update after the correction

| ID | Requirement | Status |
|---|---|---|
| GX-05 | F-02a-1: refused rollup completion still announces success | **CLOSED (technical, working tree)** - the fenced write's result now gates the completion event, the failure event, the failure alert and the third site in the incomplete-spec path. 13/13 ownership tests, 284/284 worker suite. |

This closure is **uncommitted** and **not in the `84046b2` images**. GB-01
remains PENDING, GB-08 remains NOT TESTED, GB-05 remains BLOCKED, and GB-11
remains **NOT GRANTED**. A technical closure here is not a gate decision.

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


### Gate B register status for 7f2ac46-fix4

IDs GB-01..GB-11 keep their original meaning. No gate status changes in this
pass; only evidence pointers are added.

| Gate ID | Status | Evidence pointer |
|---|---|---|
| GB-01 | **PENDING** - no independent reviewer named | author's analysis only; every reviewer field blank |
| GB-02 | **PENDING** | disposable dump only |
| GB-03 | **PENDING** | disposable restore only |
| GB-04 | **PENDING** - not at production volume | `alembic upgrade head` 0023->0034 exit 0 on a fresh disposable PG16 |
| GB-05 | **BLOCKED** | web image unchanged, still `http://localhost:8000` |
| GB-06 | **PENDING** | images local only |
| GB-07 | **PENDING** | `/health/dispatch` answered in the smoke run; no real alert delivery |
| GB-08 | **BLOCKED - NOT TESTED** | no non-production Last9 credential; the 70 s block used a controlled double |
| GB-09 | **PENDING** | disposable smoke only |
| GB-10 | **PENDING** | unchanged |
| GB-11 | **NOT GRANTED** | requires GB-01..GB-10 |

Discovered-requirement updates:

| ID | Status after 7f2ac46-fix4 |
|---|---|
| GX-01 | **CLOSED (technical)** - timer-driven keeper plus the real 70.0 s blocked call |
| GX-02 | **PARTIAL** - rollup callers fenced and tested; administrative callers remain |
| GX-03 | **CLOSED (technical)** - 8/8 downgrade concurrency scenarios |
| GX-04 | **OPEN** - commit not pushed; package and evidence untracked |
| GX-05 | **CLOSED (technical, committed and image-verified)** - F-02a-1 |
| GX-06 | **NEW - OPEN** - package copies can drift from the commit (the `fix3` `0034` copy did); `fix4` verifies every package file against the commit, the process risk remains |

Gate B remains **NOT GRANTED**. A technical PASS is not a production
authorisation; GB-11 requires the named owner's decision, and GB-01 requires a
human reviewer who has performed the review.

---

## GB-08 status review - 2026-11-15 (owner attestation, evidence pending)

The product owner reports that all planned non-production use cases passed,
including a downloaded and validated CSV. That attestation is recorded in
`RELEASE_1_NON_PRODUCTION_ACCEPTANCE_REPORT.md`.

No supporting artifact was found in this workspace: no acceptance containers,
volumes or database, no job identifiers, timestamps, screenshots or exported CSV
attributable to the run, and no evidence was supplied with the attestation.

**GB-08 remains OPEN - ATTESTED, UNEVIDENCED.** The requirement is a test log
from a non-production credential; an assertion is not a test log. The exact
artifacts needed to close it are listed in section 5 of the acceptance report.
When they are supplied and checked, GB-08 can move to PASS and this section must
be superseded, not edited.

**GB-11 remains NOT GRANTED.** Non-production technical testing is not a
production authorisation, and GB-01 still has no independent reviewer.

---

## GB-08 evidence review #2 - 2026-11-15T14:45Z (real extraction, non-candidate build)

Evidence was supplied and independently checked against the running system
(details in `RELEASE_1_NON_PRODUCTION_ACCEPTANCE_REPORT.md`):

- job **976**, `completed`, 15,423 rows, 3/3 chunks, window
  `2026-11-15 12:39:52–14:39:52 UTC`, created 14:39:56.570, finished
  14:40:04.745 (live `jobs` row and `job_events`);
- worker task received 14:39:56.738, succeeded in 8.0136 s;
- exported archive 309,505 bytes, opened and parsed: 15,423 data rows, header
  `timestamp,sessionToken,channelPartnerID,api_name`, every timestamp inside the
  requested window;
- credential id 9 (`Singapore`, org `evergentapse1`), index id 4
  (`UMS_singapore`, `ap-southeast-1`).

**But that run used the pre-Release-1 application**: source `E:\last9_web_app`
at `98d26ca`, dev images built 2026-11-12, database schema **0031**, no
`lease_token`/`owner_id`/`completion_state`, no `job_dispatch_outbox`. The
candidate is `7f2ac46`, schema **0034**, worker `f96fac9f…`, and was not
exercised. A9 (schedule), A10 (failure) and A11 (retry) have no record: the
`schedules` table is empty and there is no failed job in the last two days.

**GB-08 remains OPEN - PARTIAL.** The external Last9 dependency (token type,
org, index, query, CSV) is now proven from this host, which is the largest part
of the risk. What remains is the candidate path itself: one A4–A8 run on
`7f2ac46`/schema `0034`/worker `f96fac9f…`, plus A9–A11. This supersedes the
earlier "attested, unevidenced" note; nothing else in the register changes.

**GB-11 remains NOT GRANTED.** Non-production technical testing is not a
production authorisation.

---

## GB-08 closure - 2026-11-15T15:00Z (candidate verified)

A real extraction was executed on the candidate itself: commit `7f2ac46`,
schema `0034`, worker `sha256:f96fac9f…f224fbb`, API `sha256:78f7f987…6396bb`,
on disposable PostgreSQL 16 and Redis (destroyed afterwards). The org used,
`evergentapse1`, was confirmed by the product owner on 15 November 2026 as the
authorised org for non-production testing (owner attestation, not independently
verified).

| Check | Result |
|---|---|
| A1/A2 login + credential test | 200; `ok=true`, `token_status=valid`, `Connection successful` |
| A3 index | `UMServices`, `ap-southeast-1` |
| A4–A7 manual extraction | **job 1** created 14:58:35.508, completed 14:58:39.092, **6,923 rows**, 1/1 chunk, no error; events started → chunk → completed |
| A8 download + validation | signed URL fetched; **325,987-byte** archive; **6,923 data rows**; header ok; every timestamp inside 13:58:35–14:58:35 UTC; count equals `rows_written` |
| A9 schedule | schedule 1 ran on the next 60 s scan; **job 2** completed 14:59:37.268 with **7,192 rows** |
| A10/A11 failure + retry | invalid credential → **job 3** failed `token refresh returned HTTP 400`; retry → **job 4** failed identically |
| A12 logs | worker, beat and API logs captured |

Observation: a non-existent physical index produces the designed **partial**
completion (skipped ID batch, gap recorded on the job) rather than a hard
failure; the hard-failure test therefore used an invalid credential.

**GB-08: PASS (technical).** The "Last9 extraction NOT TESTED" gap is closed for
this candidate. Full evidence: `RELEASE_1_NON_PRODUCTION_ACCEPTANCE_REPORT.md`
and `evidence-final-7f2ac46-fix4/candidate-*`.

This is non-production functional evidence only. **GB-11 remains NOT GRANTED.**
GB-01, GB-02/03/04, GB-05, GB-07, GB-09 and GB-10 remain open, and no production
authorisation is implied.
