
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
