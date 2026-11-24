# Remediation evidence - candidate 7f2ac46-fix4

Four findings are covered by this candidate. Each entry names the defect, the
correction, and the executed evidence. No finding is closed by inspection alone.

## F-02a - rollup ownership

Defect: `run_rollup` set state with an unguarded `db.update_job`; two deliveries
could both run a rollup, and a superseded worker could overwrite newer state.

Correction (`worker/app/rollup.py`): atomic `db.claim_job` at entry, early return
when the claim is lost, and five state writes routed through a fenced `save()`.
One entry point only (`worker/app/tasks.py:174`).

Evidence: seven ownership scenarios pass on SQLite plus a real PostgreSQL 16
claim race (`test_rollup_ownership.py`), inside the built image.

## F-04 - downgrade atomicity

Defect: the `0034` downgrade counted pending/leased/dead obligations and then
dropped the table; nothing held the table between the count and the `DROP`.

Correction (`api/migrations/versions/0034_job_dispatch_outbox.py`):
`LOCK TABLE job_dispatch_outbox IN ACCESS EXCLUSIVE MODE` before both counts,
held to the end of the transaction; the guard raises instead of destroying
intent.

Evidence: eight concurrency scenarios against the real `upgrade()`/`downgrade()`
on disposable PostgreSQL 16, with `pg_stat_activity` confirming that the
dispatcher and the claim actually blocked behind the migration's lock. The guard
refuses for pending, leased and non-terminal-dead rows, and allows the drop only
when drained.

## F-13 - timer-driven heartbeat

Defect: renewal was yield-driven, so a blocking extraction call longer than the
60 s lease let a healthy worker be fenced.

Correction (`worker/app/heartbeat.py`, `worker/app/runner.py`): `LeaseKeeper`
daemon thread renewing on a wall-clock interval, its own short transaction per
tick, stopping on a failed renewal or a non-running job; the runner aborts when
ownership is lost. A real bug was fixed on the way: `self._stop` shadowed
`Thread._stop()`, so `join()` raised `TypeError`; renamed to `self._stopped`.

Evidence: real `run_extraction` plus real `LeaseKeeper` on disposable PostgreSQL
16, with a controlled blocking extraction that yields no rows for **70.0 s**.
The reconciler reported `expired=0` at ~30 s and ~70 s, the lease moved from
13:58:27 to 13:59:27 UTC, the runner then completed, and the keeper thread
exited. A superseded-token scenario proves the keeper self-stops and the runner
cannot publish. This proves heartbeat independence, not Last9 integration.

## F-02a-1 - rollup narration after a refused write

Defect: `run_rollup` ignored the boolean from its fenced `save()` and appended a
completion event, a failure event and (in the failure paths) sent a failure
alert even when the guarded UPDATE matched zero rows. A superseded rollup could
therefore tell the job feed - and possibly the schedule owner's inbox - about an
outcome it did not own.

Correction (`worker/app/rollup.py`, commit `7f2ac46`): all three fenced save
sites capture `applied` and gate their narration on it - the completion event and
gap events, the merge-failure event and alert, and the incomplete-spec failure
event and alert. No claim, transaction, fencing, retry or artifact semantics
changed.

Evidence (inside the built image):

| Test | Result |
|---|---|
| superseded rollup cannot announce success | PASS |
| superseded rollup cannot announce failure | PASS |
| superseded rollup cannot send a failure alert | PASS |
| superseded incomplete spec cannot fail the new owner's job | PASS |
| current owner can still announce success | PASS |
| current owner can still announce a genuine failure and alert | PASS |
| seven ownership scenarios | PASS |

Full suite 284 passed. Against the uncorrected `84046b2` worker image the same
file gives **4 failed, 9 passed**, so the tests detect the defect rather than
merely agreeing with the fix.

Still open and **not** addressed here: RK-19 (aggregation spec validated after
the claim) and RK-20 (`completed_without_pointer` flags rollups with no raw
sources). No evidence exists to close either.
