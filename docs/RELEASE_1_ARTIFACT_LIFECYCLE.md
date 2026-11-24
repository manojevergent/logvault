# Release 1 Artifact Lifecycle

Status: specification only. Not implemented.

## 1. Goals

- One attempt cannot overwrite another attempt's bytes.
- The database pointer is the publication commit.
- Cleanup never deletes active, published, rollup-needed, or checkpoint-needed
  data.
- Existing canonical-path assumptions are removed.

## 2. Artifact classes

| Kind | Local path | DB pointer | S3 |
|---|---|---|---|
| raw CSV/JSONL | `job_<id>.a<token>.<ext>` | `output_file_path` | attempt prefix raw |
| summary | `job_<id>.a<token>.summary.csv` | `summary_file_path` | attempt prefix summary |
| counts | `job_<id>.a<token>.counts.csv` | `counts_file_path` | attempt prefix counts |
| unmatched | `job_<id>.a<token>.unmatched.csv` | `unmatched_file_path` | not currently uploaded |
| distinct store | `job_<id>.a<token>.distinct.sqlite` | `store_path` | not uploaded |

`<token>` is the job lease token for local artifacts; S3 uses
`s3_attempt_token`. Zip variants append `.zip`.

The API download name is computed from label/job/timeframe, not the path
(**[S]** `api/app/routers/jobs.py:139-174`), so the on-disk name is opaque.

## 3. Ownership

| Phase | Owner | May write | May publish pointer? |
|---|---|---|---|
| Claim | Worker lease | create attempt paths | No |
| Running | Worker lease | append/fsync, store flush, checkpoint | Yes, guarded |
| Paused | Worker lease until ack | finalize current chunk | Yes, guarded |
| Canceling | Worker lease until final/reaper | finalize partial | Yes, guarded |
| Completed/failed/canceled | No owner | none | No |
| S3 delivery | S3 attempt token | attempt prefix/manifest | DB pointer via attempt token |
| Cleanup | System | delete unreferenced old | No |

The DB pointer update is the only publication commit. A stale attempt can write
bytes, but not change the pointer.

## 4. Creation and publication

1. Claim -> attempt token `T`.
2. Create attempt paths.
3. On each chunk: fsync, store flush, DB checkpoint/pointer guarded by
   `owner_id`, `lease_token`, `lease_expires_at > now()`, allowed status.
4. On pause/cancel/terminal: worker truncates its own file to committed
   `file_offset`, closes, and publishes pointers under the lease.
5. If the guard affects 0 rows: close/abandon, no pointer/S3.
6. S3 (post-completion recommended): claim `s3_attempt_token`, upload unique
   prefix, write manifest, publish DB pointer with token.
7. A stale S3 attempt's publish affects 0 rows; objects are orphan candidates.

## 5. Retry and resume

- New job has `retry_of`; copied checkpoint has `source_job_id`/lineage/
  fingerprint.
- New attempt seeds its own file from the checkpoint's committed prefix (copy
  exactly `file_offset`), or restarts.
- New attempt uses its own path; old attempt remains.
- The checkpoint contract is in
  [`RELEASE_1_CHECKPOINT_RECOVERY_CONTRACT.md`](./RELEASE_1_CHECKPOINT_RECOVERY_CONTRACT.md).

## 6. Rollup reads

- Source store = `jobs.store_path`; legacy fallback canonical
  `job_<id>.distinct.sqlite`.
- Source raw = `jobs.output_file_path`; if missing, skip concat.
- Rollup destination uses its own attempt paths.
- Source selection uses the successful attempt/window (D11), not every terminal
  retry.
- Rollup must not delete source stores.

## 7. Downloads

- Download reads the DB pointer (`output_file_path`/summary/counts/unmatched).
- Missing/path-expired -> 404; job may remain terminal.
- `download_url` is withheld while `is_finalizing` (paused/canceled owner).
- Partial jobs remain downloadable; the API/UI must label them partial.
- No filename/path change is required for attempt paths.

## 8. Deletion rules

### Never delete

- Any path referenced by a non-terminal job.
- Any path referenced as published by a terminal job.
- A store needed by a valid checkpoint (paused/failed/retry-resumable).
- A source store referenced by an active/pending rollup.
- The S3 prefix equal to `s3_published_attempt`.
- A path referenced by a pending outbox/window job.

### May delete

- Unreferenced attempt paths older than retention/grace.
- Unpublished S3 attempt prefixes older than retention/grace.
- Terminal job files after retention (then null pointers).
- Orphan files from fenced/crashed attempts.

### Job files delete (`DELETE /jobs/{id}/files`)

- Reject active/paused jobs.
- Reject while `s3_uploading_at` is recent or coordinate after upload.
- Delete recorded paths and zip/plain twin; null all four pointers; add event.
- Do not delete S3 objects; document that S3 copy remains.

### Customer delete

- Reject if any active job for the customer.
- Cancel/retain schedule windows and outbox rows; do not leave dangling
  `current_job_id`.
- Delete recorded attempt paths + reference scan; update/remove ledger rows per
  policy; delete jobs/events.
- Do not delete published S3 objects unless explicitly requested.

### Low-disk/retention cleanup

- Null all four local paths, including `unmatched_file_path`.
- Delete referenced attempt paths and unreferenced attempt files; preserve
  `store_path` until store retention.
- Mark `expired` derived; do not change terminal status.
- Never touch an active attempt.

## 9. Existing code corrections

| Location | Current | Required |
|---|---|---|
| `worker/app/runner.py:151-180` | canonical path builders | accept attempt token |
| `worker/app/rollup.py:285` | `_concat_raw` canonical `job_<id>.csv` | rollup attempt path |
| `worker/app/rollup.py:130` | canonical source store | `jobs.store_path` + fallback |
| `worker/app/scheduler.py:322` | canonical cleanup store | `store_path`/scan |
| `api/app/routers/customers.py:73-86` | conventional names | recorded paths + attempt scan + ledger/outbox policy |
| `api/app/routers/jobs.py:868-910` | delete files without S3 coordination | gate on S3 attempt/terminal age |
| `worker/app/s3.py:97-179` | shared keys | attempt prefix + manifest |
| `worker/app/tasks.py:180-228` | no attempt token | token/lock/publish fence |

## 10. Dangling-path prevention

- Every published path is set in the same guarded terminal/checkpoint
  transaction.
- Cleanup selects paths from the row and scans only unreferenced attempt files.
- Before deleting a path, re-read the row and compare; if changed, skip.
- A path outside the storage root is rejected at publication and cleanup.
- `store_path` is published only when the store is consistent.
- Retention nulls all pointers and records an event.
- A reconciliation task can compare recorded paths vs files and report
  mismatches; it must not delete published files.

## 11. Crash/failure cases

| Case | Expected |
|---|---|
| Worker crash after file write before checkpoint | Old checkpoint; new attempt copies old prefix; old suffix orphan. |
| Worker crash after checkpoint | New checkpoint; resume next. |
| Pointer update 0 rows | Stale attempt; abandon; no S3. |
| S3 upload succeeds, DB publish fails | Objects under attempt prefix; no pointer; retry/cleanup. |
| DB publish succeeds, worker crashes | Published pointer/URIs remain; download works. |
| Cleanup runs during active attempt | Active path skipped; only unreferenced old paths deleted. |
| Cleanup runs while rollup reads store | Store referenced by pending/running rollup protected. |
| Customer delete during pending window | Window/outbox handled; no dangling job id. |
| Low-disk purge | All four local paths nulled; store policy respected. |

## 12. Acceptance criteria

1. Attempts never share a local path or S3 key.
2. A stale attempt cannot change a published pointer.
3. Cleanup never deletes active/published/rollup-needed/checkpoint-needed data.
4. Downloads/deletes use the DB pointer; canonical filename is not required.
5. Customer/schedule deletion leaves no dangling window/outbox references.
6. S3 cleanup never deletes the published attempt.
7. Orphan growth is observable and bounded.

## 13. Required tests

T9-T11, T22, plus:
- customer delete with attempt paths/windows/outbox;
- rollup with `store_path`;
- low-disk purge with unmatched;
- cleanup while S3 retry/active attempt;
- stale pointer update;
- path traversal rejection;
- partial download labeling.

## 14. P0 evidence

P0-10 passed attempt-scoped file isolation. P0-11 passed the unique-key/DB
pointer/cleanup model using a P0 HTTP S3 stub. P0-17 passed the cleanup
ownership selection model. Real S3 provider behavior (multipart, conditional
writes, IAM, versioning, listing) remains blocked until staging.
