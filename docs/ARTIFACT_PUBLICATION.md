# Artifact Publication

Status: design proposal for Release 1. Not implemented.

Scope: local CSV/JSONL, summary, counts, unmatched, the distinct-value store,
and S3 delivery. Companion: [`LEASE_AND_FENCING.md`](./LEASE_AND_FENCING.md)
for the ownership guards.

Legend: **[V]** verified current behavior, **[P]** proposed, **[A]** unverified
assumption, **[D]** decision needed.

## 1. The problem

Database fencing stops a stale worker from changing the job row. It does not
stop it from:

- appending to the same local CSV;
- writing the same distinct-value SQLite file;
- uploading to the same S3 key;
- renaming a shared canonical file after a newer attempt published it.

Current code writes directly to canonical paths:

- `job_<id>.csv` / `.jsonl` / `.bq.csv`;
- `job_<id>.summary.csv`;
- `job_<id>.counts.csv`;
- `job_<id>.unmatched.csv`;
- `job_<id>.distinct.sqlite`.

**[V]** (`worker/app/runner.py:151-180`; `last9/distinct_store.py:266-267`).

Two workers on one job therefore share every byte they write. The conditional
claim prevents most overlap, but pause/resume, reconnect, and reclaim can still
leave two processes alive **[V, structural]**.

## 2. Design principle

> The database pointer is the publication commit. The bytes are written to an
> attempt-specific path. A stale attempt may write bytes; it cannot change the
> pointer.

This applies to local files and S3. It does not require a filesystem rename
transaction.

## 3. Attempt identity

- Local attempt token: the `lease_token` returned by the claim.
- S3 attempt token: `jobs.s3_attempt_token`, incremented atomically when an
  upload attempt is claimed. It is separate because S3 retries happen after the
  job lease is gone.
- Path token: a short decimal or zero-padded string, e.g. `a000123`.

Token monotonicity is per job. The path is unique per attempt.

## 4. Local artifact layout

### 4.1 Proposed paths

| Kind | Current | Proposed |
|---|---|---|
| raw CSV | `job_<id>.csv` | `job_<id>.a<token>.csv` |
| raw JSONL | `job_<id>.jsonl` | `job_<id>.a<token>.jsonl` |
| raw BQ CSV | `job_<id>.bq.csv` | `job_<id>.a<token>.bq.csv` |
| summary | `job_<id>.summary.csv` | `job_<id>.a<token>.summary.csv` |
| counts | `job_<id>.counts.csv` | `job_<id>.a<token>.counts.csv` |
| unmatched | `job_<id>.unmatched.csv` | `job_<id>.a<token>.unmatched.csv` |
| distinct store | `job_<id>.distinct.sqlite` | `job_<id>.a<token>.distinct.sqlite` |

Zip variants append `.zip` after the same stem. Customer directories are
unchanged.

The API download name is computed from job id/label/timeframe, not from the
path **[V]** (`jobs.py:139-174`). The on-disk name is therefore opaque and can
change without affecting downloads.

### 4.1a Existing canonical-path assumptions to fix

Attempt paths are not a drop-in until these are updated:

| Location | Current assumption | Required change |
|---|---|---|
| `api/app/routers/customers.py:73-86` | Deletes conventional `job_<id>.*` names plus recorded paths. | Also scan attempt names or record every attempt path; do not leak preview/attempt orphans. |
| `worker/app/rollup.py:285` | `_concat_raw` writes `job_<id>.csv`. | Use the rollup attempt path and publish it under the lease. |
| `worker/app/scheduler.py:322` | Cleanup reads canonical `job_<id>.distinct.sqlite`. | Use `jobs.store_path`; scan unreferenced attempt stores. |
| `worker/app/rollup.py:130` | Source store path is canonical. | Use `jobs.store_path` with legacy fallback. |
| `worker/app/s3.py:97-107` | S3 object key is based only on job/label/timeframe. | Add the attempt prefix; never write a shared canonical key. |

This is a concrete implementation dependency, not an optional cleanup detail.

### 4.2 Pointer columns

| Artifact | Published pointer |
|---|---|
| raw | `jobs.output_file_path` |
| summary | `jobs.summary_file_path` |
| counts | `jobs.counts_file_path` |
| unmatched | `jobs.unmatched_file_path` |
| distinct store | `jobs.store_path` (new) |

Only a lease-guarded write sets these. A stale worker's file is not referenced.

### 4.3 Publication timing

- **On claim/setup:** the worker sets `output_file_path` to its attempt path in
  a guarded progress write. The file may be empty or contain a header; the
  download is not yet meaningful.
- **On each checkpoint:** the worker may update `output_file_path` to the
  current attempt path (already set) and writes `checkpoint.file_offset`.
- **On pause/cancel/terminal:** the worker sets the final pointers in the
  pause/terminal guarded write. This is the publication commit.
- **On failure:** the worker sets the pointers only if the partial artifact is
  consistent (checkpoint committed). If the failure happened before any
  checkpoint, it may leave the pointers null or point to a zero-row file; the
  UI can show no output. Do not publish an unverified file.

### 4.4 Why not rename to a canonical path

A rename is not atomic with the database, and a stale worker can rename after
the new owner. Using the attempt path as the pointer avoids the shared
namespace entirely. The cost is orphan files, handled by cleanup.

### 4.5 Download consistency

The file may contain bytes beyond the last committed `checkpoint.file_offset`
if the worker crashed or was fenced mid-chunk. The publication rule is:

- The **worker** may truncate its own attempt file to `file_offset` and close it
  before publishing pause/cancel/terminal. This is safe because it owns the
  file.
- The **reaper** must not truncate a file that a live worker may still be
  writing. If it must force-finalize a cancel, it copies the first
  `checkpoint.file_offset` bytes to a new "recovered" attempt path, publishes
  that path in a guarded update, and leaves the old file for cleanup. If the
  copy fails, it hides the artifact pointer and records an error.
- The download route is unchanged; it reads the published pointer.

**Review requirement:** tests must assert the published file length equals the
committed offset for a normal pause/cancel, and that a forced reaper
finalization never publishes an uncommitted suffix.

## 5. Resume seeding

### 5.1 Checkpoint additions

Add to the `checkpoint` JSON (no schema change):

```json
{
  "completed_chunks": 12,
  "rows_written": 123456,
  "current_chunk_start": 1710000000,
  "next_chunk_start": 1710003600,
  "skipped_batches": 0,
  "file_offset": 45678901,
  "unmatched_offset": 2345,
  "chunk_hours": 1.0,
  "attempt_token": 7,
  "artifact_path": "/data/exports/customer/job_42.a7.csv",
  "store_path": "/data/exports/customer/job_42.a7.distinct.sqlite"
}
```

Legacy checkpoints lack the new keys. Fallbacks:

- `artifact_path` -> `jobs.output_file_path`;
- `store_path` -> canonical `job_<id>.distinct.sqlite` if it exists;
- `attempt_token` -> unknown.

### 5.1a Validity and recoverability

A checkpoint is recoverable only when all of the following hold:

1. `completed_chunks >= 0` and `next_chunk_start` (if set) is between
   `start_epoch` and `end_epoch`.
2. `artifact_path` (or legacy `output_file_path`) exists, is not a zip, and
   `0 <= file_offset <= file size`.
3. The artifact belongs to the same job and a prior/current attempt; it is not
   another job's file.
4. The DB checkpoint was committed **after** the artifact was flushed and
   `fsync`ed. The DB commit is the recovery marker.
5. For aggregation, `store_path` exists and its
   `last_chunk_committed >= completed_chunks - 1` (the store may be one chunk
   ahead). If it is behind or missing, the checkpoint is not recoverable for
   aggregation.
6. `is_preview=true` checkpoints are not resumable as full runs.

If any condition fails, reset to a fresh run (section 5.2) and record
`gap_reason='checkpoint_invalid'`. Never resume at `next_chunk_start` with an
empty/new file; that produces a tail-only artifact.

### 5.2 New attempt algorithm

1. Claim; get new token `T`.
2. Read checkpoint. If none, start fresh at `start_epoch`.
3. Determine `source_artifact` and `file_offset`.
4. Validate:
   - source exists;
   - not a `.zip` (a paused/failed raw file should be plain; if zipped, cannot
     seek -> reset);
   - `0 <= file_offset <= size`.
5. Create `job_<id>.aT.<ext>`.
6. Copy exactly `file_offset` bytes from `source_artifact` into the new file.
7. Set `checkpoint.file_offset = 0` for the local write? **No** — the copied
   file already contains `file_offset` bytes. Keep `file_offset` as the current
   end. The CSV writer appends after the copy.
8. Set the new attempt's `checkpoint.artifact_path` to the new path.
9. Continue from `next_chunk_start`.
10. On each chunk, truncate/append as usual; the file offset advances.
11. On terminal/pause, publish the new path.

If validation fails:

- Reset checkpoint to empty (`completed_chunks=0`, `next_chunk_start=None`,
  `file_offset=0`, `skipped_batches=0`), delete/ignore the invalid source, and
  re-extract from `start_epoch`.
- Insert a warn event: "Previous artifact unavailable/inconsistent; restarting
  the extraction from the beginning."
- Do not silently start at `next_chunk_start` with an empty file; that would
  publish only the tail of the window.

### 5.3 Same-attempt resume

If the process dies and the same attempt is somehow restarted (e.g., direct
call in tests), the checkpoint's `artifact_path` is its own file. It can open
`r+`, seek to `file_offset`, and truncate. This is the existing behavior
**[V]** (`runner.py:403-410`), now scoped to the attempt file.

### 5.4 Unmatched file

The unmatched offset is copied with the same `file_offset` rule. If the
unmatched file is missing, start a new one; the raw CSV still has the committed
prefix. The summary/counts are derived at the end, not resumed.

## 6. Distinct-value store

### 6.1 Why it needs attempt scoping

`DistinctStore` is a SQLite file. It buffers one chunk and commits at chunk
boundaries **[V]** (`last9/distinct_store.py:63-180`). Two writers to one file
can corrupt it or double-count occurrence counts. DB fencing does not stop the
SQLite writes.

### 6.2 Proposed behavior

1. At claim, create `job_<id>.aT.distinct.sqlite` (fresh).
2. If resuming and a previous store exists:
   - merge the previous store into the new one (`merge_from`);
   - preserve the previous store's `last_chunk_committed` marker in the new
     store.
3. Continue `aggregator.flush(chunk_index)`.
4. On finalization, set `jobs.store_path` to the new store path.
5. On pause/cancel, also set `store_path` if the store is consistent.
6. Cleanup deletes unreferenced stores after retention.

### 6.3 The marker problem

`merge_from` intentionally ignores `last_chunk_committed` because a chunk
marker is meaningless across different files **[V]**
(`last9/distinct_store.py:203-205`). For resume, it is not meaningless: the
previous store may contain a chunk that the DB checkpoint did not commit
because the crash happened between the store commit and the DB commit.

If the new store doesn't know the marker, replaying that chunk will add its
occurrence counts again, inflating totals.

Required fix in the design:

- Add a `seed_from_store(path)` helper that merges rows and copies the
  `last_chunk_committed` meta value.
- Or pass the marker explicitly from the checkpoint (`checkpoint.store_last_chunk`)
  and set it after merge.
- Test the crash window: store committed, DB checkpoint not; resume; assert the
  counts are not doubled and the CSV contains the replayed rows.

If the previous store is missing/unreadable:

- Do not resume aggregation from a partial store.
- Reset the checkpoint to zero and re-extract from the beginning, or fail the
  job with a clear error. Recommend reset + re-extract for a full artifact;
  failing is acceptable if the window is too expensive.

### 6.4 Rollup store

- Rollup destination store is attempt-scoped (`job_<id>.aT.distinct.sqlite`).
- Source stores are read from `jobs.store_path`; fallback canonical for legacy.
- On completion, publish `store_path`.
- On cancel/failure, do not publish; cleanup the attempt store.

## 7. S3 publication

### 7.1 Current behavior

`upload_job_artifacts(job, profile)` builds one object key per artifact from
label/job id/timeframe and uploads concurrently **[V]**
(`worker/app/s3.py:97-179`). There is no attempt id. A retry writes the same
keys. The API retry endpoint has no lock **[V]** (`jobs.py:488-507`).

### 7.2 Proposed key layout

```
<prefix>/<customer>/job_<id>/attempt_<token>/<artifact-name>
<prefix>/<customer>/job_<id>/attempt_<token>/manifest.json
```

Examples:

```
exports/AHA/job_42/attempt_000003/AHA_42_2026-08-30.csv.zip
exports/AHA/job_42/attempt_000003/manifest.json
```

- `<token>` is `jobs.s3_attempt_token`, zero-padded for readability.
- The artifact name remains the human-readable name; the attempt is a path
  segment.
- A legacy stable path is not used for new attempts. If an external consumer
  needs a stable location, publish a manifest pointer at a stable key only
  after a DB fence; see 7.7.

### 7.3 Attempt claim

**Recommended: post-completion delivery (no job lease).** The worker finalizes
the local job first, commits, then claims an S3 attempt. This is the Release 1
path described in section 8.

```sql
UPDATE jobs
SET s3_attempt_token = s3_attempt_token + 1,
    s3_uploading_at = now(),
    s3_error = NULL
WHERE id = :job_id
  AND status = 'completed'
  AND s3_profile_id IS NOT NULL
  AND (s3_uploading_at IS NULL OR s3_uploading_at < now() - :stale_upload)
RETURNING s3_attempt_token, output_file_path, summary_file_path, counts_file_path;
```

The same SQL is used by the API retry endpoint and by the worker's immediate
post-finalize upload. The only difference is who calls it.

**Optional: pre-finalize delivery.** If the team decides to keep S3 before the
terminal status, the attempt claim must also require the live lease:

```sql
UPDATE jobs
SET s3_attempt_token = s3_attempt_token + 1,
    s3_uploading_at = now(),
    s3_error = NULL
WHERE id = :job_id
  AND s3_profile_id IS NOT NULL
  AND status IN ('running','canceled')
  AND owner_id = :owner
  AND lease_token = :token
  AND lease_expires_at > now()
RETURNING s3_attempt_token, output_file_path, summary_file_path, counts_file_path;
```

Do not mix the two modes for one job. The recommended mode is post-completion,
because it releases the job lease before a potentially long S3 upload and
matches the separation of execution and delivery.

- 0 rows: an upload is already in progress (409/conflict) or the job is not
  eligible.
- The task receives `job_id`, `attempt_token`, and the artifact path snapshot.
  It does not re-read mutable paths mid-upload.
- Backward compatibility: keep the task signature
  `upload_job_s3(job_id, attempt_token=None, artifacts=None)`. A legacy message
  with only `job_id` claims an attempt itself before uploading. Do not require
  the new arguments on the old task name.

### 7.4 Upload

- Upload each artifact to its attempt key.
- Write `manifest.json` last (inside the attempt prefix), containing:
  - job id, attempt token, artifact kind, key, size, content type, created_at;
  - source local path basename (not the full host path);
  - optional checksum/etag.
- Do not write a shared canonical key. If a stale attempt uploads, its objects
  are unique and ignored.

### 7.5 Publication

After all expected artifacts succeed:

```sql
UPDATE jobs
SET s3_uri = :raw_uri,
    s3_summary_uri = :summary_uri,
    s3_counts_uri = :counts_uri,
    s3_manifest_uri = :manifest_uri,
    s3_error = NULL,
    s3_uploaded_at = now(),
    s3_published_attempt = :attempt_token,
    s3_uploading_at = NULL
WHERE id = :job_id
  AND status = 'completed'
  AND s3_attempt_token = :attempt_token
  AND s3_uploading_at IS NOT NULL;
```

- The `s3_attempt_token` match is the publication fence. A newer attempt makes
  the old update affect 0 rows.
- If some artifacts fail:
  - set `s3_error` with the joined errors;
  - set `s3_uploading_at=NULL`;
  - do **not** advance `s3_published_attempt`;
  - optionally store successful URIs for diagnostics, but mark the attempt
    partial. The UI derives `s3_partial`.
- If the DB update is 0 rows, the attempt is superseded. Leave objects for
  cleanup; do not retry blindly.

### 7.6 Atomicity

S3 has no multi-object transaction. The design's commit point is the single
Postgres row update. The manifest is audit, not the source of truth. Consumers
read the DB URIs/manifest pointer.

### 7.7 Stable external path (optional)

If a downstream consumer requires `.../job_<id>/latest/...`:

- Do not have workers write it.
- A separate publisher, after the DB `s3_published_attempt` commit, copies or
  promotes the winning manifest to the stable key.
- A stale worker cannot be the publisher because the DB fence decides.
- This adds a second write; a crash between DB commit and stable promotion
  leaves the stable path stale. A reconciliation task can repair it.
- For Release 1, recommend **no stable key**; external consumers should follow
  the DB/API or the published manifest prefix.

### 7.8 Cleanup

- Delete attempt prefixes where `attempt_token != s3_published_attempt` and the
  job is older than retention (or the attempt is older than a short grace).
- Never delete `s3_published_attempt`.
- For abandoned multipart uploads, configure an S3 lifecycle rule
  `AbortIncompleteMultipartUpload` or run a cleanup task that calls
  `list_multipart_uploads`/`abort_multipart_upload`.
- If `s3_published_attempt IS NULL` and legacy `s3_uri` exists, keep the legacy
  objects; do not treat them as unpublished.

### 7.9 Partial success UI

Current UI: `s3_error ? "upload failed" : s3_uri ? "uploaded" : "pending"`
**[V]** (`jobs/[id]/page.tsx:552-554`). Proposed derived states:

- `s3_pending`: profile set, no publishing attempt, no error.
- `s3_uploading`: `s3_uploading_at` non-null.
- `s3_partial`: some artifacts uploaded, `s3_error` set, not published.
- `s3_published`: `s3_published_attempt` non-null.
- `s3_failed`: error, no published attempt.
- `s3_published_with_error`: a prior attempt is published, but the latest retry
  failed. Keep the published pointer and show the latest error separately; do
  not label the job "not uploaded".
- `legacy`: no attempt fields but `s3_uri` set.

## 8. Publication ordering vs job completion

Recommendation: **finalize the local job first, then deliver S3.**

1. Worker writes/flushes/fsyncs the local attempt artifacts.
2. Worker finalizes the job row under the lease (`completed`/`canceled`).
3. After commit, claim an S3 attempt and upload.
4. Publish S3 pointers.
5. If the process dies after step 2, the job is completed with S3 pending; a
   reconciliation task or the retry endpoint can upload.

Why:

- S3 is delivery, not execution. The job should not stay `running` (and hold a
  lease) during a slow upload.
- A fenced worker cannot finalize, so it cannot enqueue a stale S3 attempt.
- The S3 attempt has its own token/lock after the lease is gone.
- This matches the canonical separation of execution and delivery.

Behavior change: S3 failure no longer delays completion. It shows as
`s3_error`/`s3_pending`. Existing code already completes the job despite S3
errors **[V]** (`runner.py:830-839`), so this is mostly a timing change.

## 9. Cleanup of abandoned local artifacts

Add a cleanup task (or extend `cleanup_exports`) that:

1. Selects terminal jobs older than retention.
2. Deletes the published paths (`output`, `summary`, `counts`, `unmatched`,
   `store_path`) and nulls them (existing behavior, extended to `store_path`).
3. Scans for `job_<id>.a*` files whose job is terminal/old and whose path is not
   in the published set; deletes them.
4. Never deletes a path referenced by a non-terminal job.
5. Records an event for published deletions; orphan deletions can be logged
   without a job event.

Naming convention makes the scan bounded. If the exports directory is huge,
add a `job_artifact_attempts` table later (not Release 1 unless needed).

## 10. Data-loss scenarios and mitigations

| Scenario | Mitigation |
|---|---|
| Cleanup deletes a referenced pause artifact | Compare against all published pointers; only delete unreferenced. |
| Resume copies the wrong file | Validate path/offset/size/zip; fall back to full restart with an event. |
| Store merge double counts | Preserve `last_chunk_committed`; test the store-commit/DB-crash window. |
| Store missing | Reset/re-extract or fail clearly; never resume with a partial store. |
| S3 cleanup deletes the winner | Never delete the `s3_published_attempt` prefix. |
| Stale S3 attempt overwrites | Unique attempt prefix; DB pointer is the only publication. |
| DB pointer updated but file missing | Finalization verifies the file exists and is closed; if not, clear/fail. |
| Reaper force-clears a cancel with uncommitted bytes | Copy the committed prefix to a recovered attempt path and publish it; otherwise hide the path. Never truncate a live worker's file. |
| Rollback to old rollup | Old code reads canonical store; run a copy/link shim for `store_path`. |

## 11. Acceptance criteria

1. Two attempts for one job write to different local paths and S3 prefixes.
2. A stale attempt's DB pointer update affects 0 rows.
3. The published local file contains exactly the committed prefix plus new
   committed rows; no uncommitted suffix.
4. A crash at each checkpoint step resumes with at most one chunk replay and no
   duplicate rows.
5. Distinct-store counts are not inflated by a replayed chunk.
6. S3 publication is decided by one DB update; stale attempts cannot change it.
7. Cleanup never deletes a published path.
8. Downloads use the DB pointer and are unaffected by the on-disk name.

## 12. Open decisions

- D4: approve attempt-scoped local paths.
- D5: approve `store_path` and attempt-scoped stores.
- D7: approve unique S3 prefixes + DB pointer (vs stable canonical key).
- Whether to add `job_artifact_attempts` in Release 1 for cleanup/audit, or use
  naming-convention scanning. Recommendation: naming scan in Release 1; table
  later if the directory grows.
- Whether to publish the partial artifact on `failed` before any checkpoint.
  Recommendation: no; leave the pointer null and the error visible.
- Whether to keep legacy `job_<id>.csv` as a hard link/copy for external
  consumers. Recommendation: no; use the API/DB pointer.
