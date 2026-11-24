# Release 1 - Release notes

Candidate: `7f2ac46-fix4`
Commit: `7f2ac46` (parent `84046b2`), branch `release-1/p1-dispatch`
Status: **PREPARED FOR INDEPENDENT REVIEW - NOT APPROVED FOR PRODUCTION**

## Included

- Transactional dispatch outbox, fenced claim, progress heartbeat, timer-driven
  `LeaseKeeper`, lease reconciler, attempt artifacts, guarded publication,
  strict checkpoint validation, partial-completion reporting.
- Dedicated beat service with a Redis singleton guard.
- `GET /health/dispatch` with database and broker gauges.
- Frontend partial-completion badge and banner.
- Migrations `0032`, `0032b`, `0033`, `0034`. Schema head `0034`; new code must
  not run on `0031`.
- **New in this candidate:** F-02a-1 correction in `worker/app/rollup.py` - a
  rollup whose fenced write is refused no longer announces success, failure or
  sends a failure alert on behalf of a job another worker owns.

## Not included

- Migrations `0035`/`0036` (REDUCED scope, D11 unsigned).
- Task failure/retry metrics.
- A production web image: it is still built with
  `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` (GB-05).

## Evidence summary

Worker suite 284 passed; rollup ownership 13 passed (4 of the same tests fail on
`84046b2`); targeted regression 84 passed; F-13 9/9 with a real 70.0 s blocked
call; API 289 passed; F-04 downgrade concurrency 8/8 on PostgreSQL 16; frontend
8/8 and `tsc` clean; source-to-image 37/37 application and 25/25 test files
identical; dependency inventory unchanged; disposable smoke stack completed a
synthetic rollup through the outbox.

## Approvals

Gate A and Gate B: **NOT GRANTED**. No approval, reviewer name, date or
signature is recorded in this package. Live Last9 extraction, production-scale
backup/restore, migration rehearsal at volume and real alert delivery remain
outstanding.
