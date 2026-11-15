# Release 1 - Handover package for independent review

Candidate: `7f2ac46-fix4`
Branch: `release-1/p1-dispatch`
Commit: `7f2ac468e21de16e2feee9f2bd81b8fe0669c89b` (parent `84046b2`)
Date: 15 November 2026
Status: **PREPARED FOR INDEPENDENT REVIEW - NOT PRODUCTION APPROVED**

## What is handed over

| Artifact | Tag | Immutable ID |
|---|---|---|
| Worker | `last9-worker:release-1-final-7f2ac46-fix4` | `sha256:f96fac9f2d16a0b3141578111cc110313f6de5488dcc6f80868767fbfe224fbb` |
| API | `last9-api:release-1-final-84046b2-fix3` | `sha256:78f7f987cf3bc5074e6f3aeb9b08c3816bf4e18d7ddb57b3b4772de21c6396bb` |
| Web | `last9-web:release-1-final-78fb0a7` | `sha256:6a6489dcc5d3d9ef76ef5c6cc0cc4ab11faa8fac376895a14f9974b0fd660ab1` |
| Beat | worker image + `python -m app.beat_guard` | `sha256:f96fac9f2d16a0b3141578111cc110313f6de5488dcc6f80868767fbfe224fbb` |

Database: REDUCED scope, head `0034` (`0032`, `0032b`, `0033`, `0034`); `0035`/`0036`
excluded. New code must not run on schema `0031`.

## What changed since `84046b2-fix3`

One application file, `worker/app/rollup.py`: the three fenced `save()` calls in
`run_rollup` now gate their completion event, gap events, failure event and
failure alert on the write result (F-02a-1). One new test file,
`worker/tests/test_rollup_ownership.py` (13 tests). No schema, API, frontend,
lease or fencing change. The worker image was rebuilt from the commit; the API
and web images were not rebuilt.

## Verified for this candidate

- Worker suite **284 passed** (exit 0), inside the built image.
- Rollup ownership **13 passed**; the same tests fail **4/13** against `84046b2`.
- Targeted regression **84 passed**; F-13 **9/9** with a real 70.0 s block.
- API suite **289 passed**; F-04 downgrade concurrency **8/8** on PostgreSQL 16.
- Frontend **8 passed**; `tsc` exit 0.
- Source-to-image: 37/37 application and 25/25 test files identical; 0 mismatches.
- Dependency inventory identical to `84046b2`; disposable smoke stack completed a
  synthetic rollup through the outbox.

## Exceptions a reviewer must weigh

1. Live Last9 extraction was **not** tested - no non-production credential
   (GB-08). The 70 s F-13 test proves heartbeat independence only.
2. Production-scale backup, restore and migration rehearsal were not performed
   (GB-02/03/04).
3. The web image is built with `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`
   (GB-05). It must be rebuilt with the approved URL before any deployment.
4. Deferred advisories: starlette 0.41.3 (7), ecdsa 0.19.2 (1), python-jose
   PYSEC-2025-185 (no fix).
5. Single-person control: implementation, verification and evidence were produced
   by the same individual. This is recorded as a limitation, not endorsed.
6. RK-19 (rollup validates its spec after the claim) and RK-20
   (`completed_without_pointer` flags source-less rollups) remain open and
   unmitigated in this candidate.
7. Provenance means commit-to-image verification, not bit-reproducible builds:
   the base image is a floating tag and dependencies are pinned only at the
   top level.

## Sign-off

No independent reviewer has been named and no reviewer name, date, signature or
approval is recorded in this package. The implementation author performed the
integrity checks described in `PROVENANCE.md`; that is not independent review.

Decision: **PREPARED FOR INDEPENDENT REVIEW. Gate B NOT GRANTED. No deployment
is authorised by this handover.**
