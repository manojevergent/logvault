
---

## GB-08 closure - 2026-11-15T15:00Z (candidate verified)

A real extraction was executed on the candidate itself: commit `7f2ac46`,
schema `0034`, worker `sha256:f96fac9f…f224fbb`, API `sha256:78f7f987…6396bb`,
on disposable PostgreSQL 16 and Redis (destroyed afterwards).

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
