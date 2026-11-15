# Release 1 — Non-Production Acceptance Report

**Status: COMPLETE — verified on the Release 1 candidate with real Last9 data.**
**Gate B: NOT GRANTED.**

Candidate: commit `7f2ac468e21de16e2feee9f2bd81b8fe0669c89b` (`7f2ac46`)
Worker image: `last9-worker:release-1-final-7f2ac46-fix4` = `sha256:f96fac9f…f224fbb`
API image: `last9-api:release-1-final-84046b2-fix3` = `sha256:78f7f987…6396bb`
Package: `release-artifacts/release-1-final-7f2ac46-fix4/`
Executed: 15 November 2026, 14:58–15:00 UTC
Author: implementation author. **No independent reviewer has been named.**

---

## 1. How it was run

A disposable stack was created from the candidate images and destroyed
afterwards:

- PostgreSQL 16 and Redis 7, fresh volumes;
- database migrated to **schema `0034`** with the candidate API image;
- API (`78f7f987…`), worker and beat (`f96fac9f…`) from the candidate images;
- the existing configured Last9 connection (org `evergentapse1`, index
  `UMServices`, region `ap-southeast-1`) was copied into the disposable database
  inside a container, re-encrypted with the disposable key; the plaintext token
  was never printed or written to a file, and the database volume was deleted at
  the end;
- no production system was contacted other than the Last9 query API that the
  application already uses for these credentials.

The test was driven through the candidate **API** with the same endpoints the
web UI calls (`/auth/login`, `/credentials/{id}/test`, `/indexes`, `/jobs`,
`/schedules`, signed `/jobs/{id}/download`). The web container was not started.

## 2. Evidence

| ID | Evidence | Detail |
|---|---|---|
| E1 | Login | `POST /auth/login` 200, role `admin` |
| E2 | Credential test | `ok=true`, `token_status=valid`, message `Connection successful` |
| E3 | Index created | id 1, `ap-southeast-1`, `physical_index:UMServices` |
| E4 | Manual job | **job 1**, created 14:58:35.508, queued → running |
| E5 | Events | `Job started` 14:58:35.656; `Chunk 1/1 done` 14:58:39.076; `Job completed` 14:58:39.092 |
| E6 | Completion | **completed**, **6,923 rows**, 1/1 chunk, no error, finished 14:58:39.092 |
| E7 | Download | signed URL fetched; archive **325,987 bytes**; **6,923 data rows**; header first column is the timestamp column; every row's timestamp inside `13:58:35–14:58:35 UTC`; row count equals `rows_written` |
| E8 | Schedule | schedule id 1 (`every hour / last hour`); beat `scan-schedules` 14:59:33; **job 2** created 14:59:33.210, completed 14:59:37.268, **7,192 rows** |
| E9 | Failure + retry | invalid-credential job **3** failed 14:59:39.896 with `token refresh returned HTTP 400`; retry created **job 4**, failed 14:59:42.812 with the same error |
| E10 | Logs | worker log: `run_job` received/succeeded for all four jobs; beat log: scan-schedules tick; API access log |

Evidence files: `release-artifacts/evidence-final-7f2ac46-fix4/candidate-*`
(summary JSON, job JSON, events JSON, jobs table, worker/beat/API logs, run log).

## 3. Use-case results

| # | Use case | Result | Evidence |
|---|---|---|---|
| A1 | Application login | **PASS** | E1 |
| A2 | Credential configuration + connection test | **PASS** | E2 |
| A3 | Region and index configuration | **PASS** | E3 |
| A4 | Manual extraction started | **PASS** | E4 |
| A5 | Dispatch and execution | **PASS** | E5, E10 |
| A6 | Status and progress monitoring | **PASS** | E5 (started → chunk → completed); API status per poll |
| A7 | Successful completion | **PASS** | E6 |
| A8 | CSV/ZIP download and validation with real Last9 records | **PASS** | E7 |
| A9 | Scheduled extraction | **PASS** | E8 |
| A10 | Expected failure handling | **PASS** | E9 |
| A11 | Manual retry | **PASS** | E9 |
| A12 | Application and worker logs during execution | **PASS** | E10 |

## 4. Additional observation — partial completion

During a first pass, a job pointed at a **non-existent physical index** did not
fail. Last9 returned HTTP 400 for the ID batch; the runner retried, skipped the
batch and completed the job as **partial** with
`1 ID batch(es) skipped after repeated HTTP 400 — up to 100 IDs are missing from
this output`. That is the designed partial-completion path (gap recorded on the
job, not hidden as success), and it is why the hard-failure test in E9 uses an
invalid credential instead. Log:
`candidate-acceptance-run-partial-observation.log`.

## 5. What this proves and what it does not

Proven on the candidate: login, credential validation against Last9, index
configuration, manual extraction, outbox dispatch, worker claim and execution,
status/progress events, completion, download and data-window validation,
scheduled execution, a hard failure with a clear message, and manual retry —
with the fix4 worker and schema `0034`.

The org used (`evergentapse1`) is the one already configured in this workspace.
The owner classifies this activity as non-production; that classification is the
owner's and is not independently verified here.

Not covered by this run:

- the **web UI** on the candidate (the retained web image is still built with
  `http://localhost:8000`; GB-05 remains blocked). The UI flow was separately
  observed on the pre-Release-1 dev stack (job 976), which is not candidate
  evidence;
- S3 / BigQuery destinations, Google sign-in, real alert-email delivery;
- more than one org/index/region;
- production-scale behaviour.

**This is non-production functional acceptance, not production readiness.
Gate B remains NOT GRANTED**; GB-01, GB-02/03/04, GB-05, GB-07, GB-09, GB-10,
GB-11, RK-19, RK-20, RK-24 and the deferred advisories are unchanged.

## 6. Sign-off

No independent reviewer, date or signature is recorded. The implementation
author executed and observed this run; that is not an independent acceptance
review.

```
Independent reviewer : ______________________________
Date                 : ______________________________
Outcome              : ______________________________
```
