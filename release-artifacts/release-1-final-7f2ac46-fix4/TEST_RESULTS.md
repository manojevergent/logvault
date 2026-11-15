# Test results - candidate 7f2ac46-fix4

Source: commit `7f2ac468e21de16e2feee9f2bd81b8fe0669c89b`
Worker image: `last9-worker:release-1-final-7f2ac46-fix4`
API image: `last9-api:release-1-final-84046b2-fix3` (unchanged)

All worker tests ran inside the built image against its own `/app/tests`
(no source mount). `pytest` was installed inside the throwaway container from
the image's `requirements-dev.txt`; the image itself was not modified.

Infrastructure: disposable PostgreSQL 16 (`last9_p1_pg16`, database `p1test`),
throwaway Redis container for the smoke stack. No production system was used.

| # | Suite | Command location | Result | Exit |
|---|---|---|---|---|
| 1 | Full worker suite | new worker image, `python -m pytest tests` | **284 passed** in 8.18s | **0** |
| 2 | Rollup ownership | new worker image, `pytest tests/test_rollup_ownership.py -v` | **13 passed** in 1.76s | **0** |
| 3 | Targeted regression (9 files) | new worker image | **84 passed** in 7.78s | **0** |
| 4 | F-13 blocked extraction | new worker image, real runner + LeaseKeeper, controlled blocking double | **9/9 PASS**, wall 100.2s, actual block **70.0s** | **0** |
| 5 | API suite | API image, own `/app/tests` | **289 passed** in 6.23s | **0** |
| 6 | F-04 downgrade concurrency | API image, its own `0034` migration, disposable PG16 | **8/8 PASS** | **0** |
| 7 | Frontend units | host `npm test` | **8 passed**, 0 failed | **0** |
| 8 | TypeScript | host `npx tsc --noEmit` | no output | **0** |
| 9 | Negative control on the old worker image | `84046b2` image + the new test file | **4 failed, 9 passed** | **1** (expected) |
| 10 | Source-to-image provenance | image extract vs `git archive 7f2ac46` | 37/37 app, 25/25 test files, **0 mismatches** | n/a |
| 11 | Dependency inventory | `pip freeze` new vs old worker image | **identical**, 0 differing lines | n/a |
| 12 | Disposable smoke stack | API + beat + new worker image | `/health` ok, `/ready` ok (postgres, redis), `/health/dispatch` ok, synthetic rollup **completed** in 0.048s, outbox **published** | **0** |

## The F-02a-1 tests

`worker/tests/test_rollup_ownership.py` holds 13 tests: the seven ownership
scenarios plus six that pin the correction.

| Test | New image | `84046b2` image |
|---|---|---|
| seven ownership scenarios (1-7, including the PG16 claim race) | PASS | PASS |
| `test_superseded_rollup_cannot_announce_success` | PASS | **FAIL** |
| `test_superseded_rollup_cannot_announce_failure` | PASS | **FAIL** |
| `test_superseded_rollup_cannot_send_a_failure_alert` | PASS | **FAIL** |
| `test_superseded_incomplete_spec_cannot_fail_the_new_owners_job` | PASS | **FAIL** |
| `test_current_owner_can_announce_success` | PASS | PASS |
| `test_current_owner_can_announce_failure_and_alert` | PASS | PASS |

The strict xfail was removed because the test passes against the corrected
source; the same tests fail against the uncorrected image, which is what makes
them evidence. No assertion was weakened.

## F-13 detail

- claim: 60 s lease, token 1, owner `worker:1`
- blocked call: no rows, no `on_chunk_complete`, **70.0 s** measured wall clock
- lease moved `2026-11-15 13:58:27.097` -> `13:59:27.139` UTC while blocked
- reconciler at ~30 s and ~70 s: `expired=0`
- after release: job `completed`; keeper thread gone; no failure/fencing event
- superseded-token scenario: keeper self-stops, runner cannot publish

This proves **heartbeat independence**, not Last9 integration. The Last9 HTTP
path remains untested (GB-08).

## Smoke detail

Fresh database, `alembic upgrade head` 0023 -> 0034 (exit 0), API and beat from
the unchanged API/worker-format images, worker from
`last9-worker:release-1-final-7f2ac46-fix4`.

```
/health            {"status":"ok"}
/ready             {"status":"ok","checks":{"postgres":"ok","redis":"ok"}}
/health/dispatch   overall=ok; beat_heartbeat_age_s=2.55; worker_online=1.0
job 1001           completed, owner=rollup, token=1, summary+counts present
outbox             published
worker log         run_job succeeded in 0.048s
```

At the first poll (before the beat's first heartbeat) `/health/dispatch`
reported `unknown`, not `ok`; it moved to `ok` once the heartbeat key existed.
That is the documented "unavailable telemetry reports unknown" behaviour.

## Log files

All under `release-artifacts/evidence-final-7f2ac46-fix4/`:
`worker-build.log`, `in-image-content.txt`, `provenance.txt`,
`sbom-worker-diff.txt`, `test-worker-full.log`, `test-rollup-ownership.log`,
`test-targeted-regression.log`, `test-f13.log`, `test-api-full.log`,
`test-f04.log`, `test-frontend.log`, `test-tsc.log`,
`test-negative-control-old-image.log`, `smoke-*.{log,txt,json}`,
`old-image-digests.txt`, `new-worker-digest.txt`, `build-env.txt`.

## Not tested

- Live Last9 extraction (no non-production credential) - GB-08.
- Production-scale backup, restore and migration rehearsal - GB-02/03/04.
- Real alert-channel delivery - GB-07.
- Production deployment rehearsal - GB-09.
- Web image with a production API URL - GB-05.

Gate B remains **NOT GRANTED**.
