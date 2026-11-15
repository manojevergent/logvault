
---

## Local rehearsal evidence - 2026-11-15T15:30Z (GB-02/03/04/09 partial)

A rehearsal was run on a **copy of the local development database** (841 jobs,
4 credentials, 6 index targets). It is not production and not production volume.

| Gate | What was executed | Result |
|---|---|---|
| GB-02 | `pg_dump -Fc` of the local database | 2,904,264 bytes, exit 0 |
| GB-03 | restore into a scratch database | 0.89 s; schema 0031, 841 jobs, 4 credentials, 6 indexes preserved |
| GB-04 | `alembic upgrade head` on that copy with the candidate API image | 2.15 s; head **0034**; 841 jobs / 4 credentials / 6 indexes preserved; lease, owner, completion-state columns and `job_dispatch_outbox` present |
| GB-09 | candidate API `78f7f987…` + worker/beat `f96fac9f…` against the upgraded copy | login ok; credential test valid; **job 1010 completed with 6,451 rows**; signed download 301,131 bytes, 6,451 rows, all timestamps inside the 1-hour window |

GB-02/03/04/09 move from **PENDING to PARTIAL**: the procedure is proven on real
data at local size. Production volume, production access and a production-shaped
deployment rehearsal are still required before they can be PASS.

**GB-01:** the product owner states they have checked the package. That is a
self-check by the project owner, not a review independent of the implementation.
No reviewer name, date or signature is recorded, so **GB-01 remains PENDING**.

GB-05 (production web URL), GB-06 (image distribution), GB-07 (real alert
delivery) and GB-10 (on-call names) are unchanged and cannot be validated
without their external inputs. GB-08 remains **PASS (technical)**. **GB-11
remains NOT GRANTED.**

Evidence: `evidence-final-7f2ac46-fix4/rehearsal-*` (dump, migration log, run log,
summary JSON, script).
