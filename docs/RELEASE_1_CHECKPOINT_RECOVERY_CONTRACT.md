# Release 1 Checkpoint Recovery Contract

Status: specification only. Not implemented.

This is the authoritative D3 contract. It supersedes the shorter D3 discussion
in the readiness review and the retry sections of the architecture documents.

## 1. Scope

Define when a failed/canceled/interrupted job may resume from a checkpoint,
when it must restart, and when it must stop for manual intervention.

The contract is deliberately conservative: **checkpoint existence is not
evidence of recoverability.**

## 2. Required checkpoint schema (v1)

Store this JSON in `jobs.checkpoint`. No new column is required.

```json
{
  "version": 1,
  "source_job_id": 42,
  "lineage_root_id": 42,
  "attempt_token": 7,
  "spec_fingerprint": "sha256:...",
  "start_epoch": 1710000000,
  "end_epoch": 1710086400,
  "chunk_hours": 1.0,
  "completed_chunks": 12,
  "rows_written": 123456,
  "current_chunk_start": 1710043200,
  "next_chunk_start": 1710046800,
  "skipped_batches": 0,
  "file_offset": 45678901,
  "unmatched_offset": 2345,
  "artifact_path": "/data/exports/customer/job_42.a7.csv",
  "store_path": "/data/exports/customer/job_42.a7.distinct.sqlite",
  "store_last_chunk": 11,
  "artifact_format": "csv",
  "suppress_raw_output": false
}
```

### 2.1 Identity

| Field | Meaning | Validation |
|---|---|---|
| `version` | Checkpoint schema | Must be `1`; unknown -> manual fail. |
| `source_job_id` | Job that produced this checkpoint | Must equal current job id, or current `retry_of` must equal it. |
| `lineage_root_id` | First job in the retry chain | Must be stable across copies; no cross-job use. |
| `attempt_token` | Lease token that wrote it | Diagnostic only; a new attempt has a new lease token. |
| `spec_fingerprint` | Hash of immutable extraction config | Must match current job; mismatch -> restart. |
| `start_epoch`/`end_epoch` | Window | Must match current job exactly. |
| `chunk_hours` | Effective chunk size at checkpoint | Restored on resume; may differ from job default. |
| `completed_chunks` | Number of chunks committed | Must be >=0. |
| `next_chunk_start` | Exact epoch to resume | Must be > start, <= end; if 0 chunks, null/start. |
| `current_chunk_start` | Start of last committed chunk | Must be < next. |
| `rows_written` | Rows committed | >=0; not a substitute for artifact validation. |
| `file_offset` | CSV/JSONL byte offset | >=0, <= file size. |
| `unmatched_offset` | Unmatched file byte offset | >=0, <= file size if file expected. |
| `artifact_path` | Current attempt artifact | Must be inside storage root and belong to lineage. |
| `store_path` | Current attempt SQLite store | Must be inside storage root and belong to lineage. |
| `store_last_chunk` | Store's committed chunk marker | >= completed_chunks - 1. |
| `suppress_raw_output` | Parse-only job with no raw artifact | If true, no raw file/offset is required. |

### 2.2 Spec fingerprint

Hash a canonical JSON of:

- `region_code`
- `index_target_id`
- `start_epoch`, `end_epoch`
- `filter_spec` (phrases/ids/exact/excludes/message types/customer/label)
- `aggregation` config
- `chunk_hours` (initial), `id_batch_size`
- `output_format`
- `suppress_raw_output` / aggregation `skip_raw_output`

Do **not** include `credential_id`: a deleted credential may be re-pointed to
the index's current credential for the same source. Do include
`index_target_id`/region. If the source index, window, filter, format or
aggregation changed, the fingerprint changes and resume is refused.

### 2.3 Lineage rules

- Same-row pause/resume/reclaim: `source_job_id == job.id`.
- Retry: new job has `retry_of = source_job_id`; copied checkpoint must set
  `source_job_id = new_job.id` and preserve `lineage_root_id`.
- A retry of a retry may copy only from the immediate source; the checkpoint's
  `source_job_id` is rewritten to the new job.
- Any other lineage mismatch -> restart (or manual fail if the checkpoint
  appears corrupted).

## 3. Committed chunk identity

A chunk is committed only when all of the following happened in order:

1. Rows were written to the attempt CSV/JSONL.
2. The file was flushed and `fsync`ed.
3. The distinct store was flushed with that chunk index (if aggregation).
4. The job row's `completed_chunks`, `next_chunk_start`, `rows_written`,
   `current_chunk_start`, `checkpoint`, and the chunk event were committed in
   one database transaction.

`completed_chunks=N` means chunks `0..N-1` are committed. `next_chunk_start` is
the exact resume cursor. `store_last_chunk` must be `>= N-1` for aggregation.

**Zero committed chunks:** if `completed_chunks == 0`, restart from the
beginning. A row with zero committed chunks is not evidence of recoverable work;
the partial artifact/store may contain uncommitted bytes and must be discarded.

## 4. Artifact and store validity

### 4.1 Raw artifact

- If `suppress_raw_output=false`, `artifact_path` must exist.
- It must not end in `.zip` (paused/failed raw files are plain).
- `0 <= file_offset <= file_size`.
- The suffix after `file_offset` is ignored/truncated; it may be uncommitted.
- The path must be under the configured storage root and contain the job id and
  lineage/attempt marker.
- A missing/short/corrupt/zip artifact -> restart (manual fail only for
  permission/IO or path escape).

### 4.2 Unmatched artifact

- If `unmatched_offset > 0` or the job has `rows_unmatched > 0`, the unmatched
  artifact must exist and `unmatched_offset <= size`.
- If it is missing, restart; otherwise the published unmatched artifact would
  be incomplete.
- If no unmatched rows were expected, a missing file is allowed.

### 4.3 Distinct store

- If aggregation is enabled:
  - `store_path` must exist, be readable SQLite, and belong to the lineage.
  - `store_last_chunk >= completed_chunks - 1`.
  - If behind -> restart.
  - If ahead by one -> resume; the replay's chunk marker drops duplicate counts.
  - If unreadable/locked after bounded retries -> restart; do not resume.
- If aggregation is disabled, no store validation is required.

### 4.4 Summary/counts

They are regenerated at finalization; they are not resume state. Missing
summary/counts do not block resume.

## 5. Duplicate and missing chunk prevention

- Chunks are non-overlapping `[start,end)`.
- The CSV is truncated to `file_offset`; the committed prefix is copied to the
  new attempt.
- The distinct store marker makes a replayed chunk's occurrence counts
  idempotent.
- `next_chunk_start` is the single source of truth for the next chunk.
- Missing chunks are detected by:
  - non-monotonic/invalid `next_chunk_start`;
  - `completed_chunks` vs `store_last_chunk` mismatch;
  - file size shorter than the offset;
  - a checkpoint/artifact lineage mismatch.
- A checksum of the committed prefix is **not** available in Release 1; a
  torn/corrupt prefix that preserves size is not detectable. This is an
  accepted limitation; add a rolling hash in Release 2 if required.

## 6. Crash recovery

| Crash point | State | Recovery |
|---|---|---|
| Before CSV row write | old checkpoint | Replay chunk. |
| During CSV write | old checkpoint | Truncate to old offset; replay. |
| After CSV write before fsync | old checkpoint | Replay; suffix ignored. |
| After fsync before store flush | old checkpoint; store behind | Store behind -> restart (or regenerate store for completed chunks if feasible; not Release 1). |
| After store flush before DB commit | old checkpoint; store ahead | Merge store + marker; replay rows; counts dropped. |
| During DB commit | old or new (atomic) | Old -> replay; new -> next. |
| After DB commit | new | Resume next chunk. |
| After DB commit before event | impossible; same transaction | - |
| After final DB commit before S3 | completed | S3 retry/cleanup; no resume. |

## 7. Decision matrix

| Condition | Resume | Restart | Manual fail | Reason |
|---|---|---|---|---|
| No checkpoint; no artifact | - | Yes | - | Nothing to resume. |
| Checkpoint row exists but `completed_chunks=0` | - | Yes | - | No committed chunk to preserve. |
| Valid checkpoint, artifact, store, fingerprint, lineage, no gaps | **Yes** | - | - | All invariants hold. |
| Valid checkpoint; artifact missing | - | Yes | - | Prefix unavailable. |
| Valid checkpoint; artifact shorter than offset | - | Yes | - | Committed bytes missing. |
| Valid checkpoint; artifact corrupt/zip | - | Yes | - | Not safely seekable. |
| Artifact exists; checkpoint missing | - | Yes | - | Boundary unknown. |
| Checkpoint newer than artifact | - | Yes | - | Missing committed suffix. |
| Artifact newer than checkpoint | **Yes** | - | - | Copy committed prefix; replay suffix. |
| Store missing/behind | - | Yes | - | Aggregation counts incomplete. |
| Store one chunk ahead | **Yes** | - | - | Marker makes replay idempotent. |
| Fingerprint mismatch | - | Yes | - | Source/window/config changed. |
| Lineage mismatch | - | Yes | - | Checkpoint belongs elsewhere. |
| `skipped_batches>0`/partial | - | Yes | - | Resume would freeze gaps. |
| Unmatched artifact expected but missing | - | Yes | - | Incomplete unmatched output. |
| Preview -> full | - | Yes | - | Preview is capped. |
| Unknown checkpoint version | - | - | **Yes** | Do not guess schema. |
| Artifact path outside storage root | - | - | **Yes** | Security/integrity. |
| Storage permission/IO error | - | - | **Yes** | Do not retry over broken storage. |
| Source data mutable in completed prefix | - | Yes | - | No point-in-time guarantee. |

## 8. Retry vs resume

- Same-row pause/resume/reclaim: resume if valid.
- A failed/canceled terminal job: retry creates a new row.
- New row copies checkpoint only when:
  - `retry_of` lineage is valid;
  - fingerprint matches;
  - no gaps/partial;
  - artifact/store valid.
- Otherwise new row starts fresh with a `retry_fallback_reason` event.
- Rollup retry always restarts the merge; a rollup checkpoint is not a
  merge-resume cursor.
- Preview promotion is a new full run; never resumes a preview.

## 9. Source-data and configuration changes

- Config/filter/window/format changes -> fingerprint mismatch -> restart.
- Source data changes inside an already committed prefix -> resume produces a
  mixed snapshot. Release 1 assumes historical log data is append-only for the
  selected window. If that is false, restart is required. This is an
  **[A]/business decision**, not a proven invariant.
- Credential re-pointing for the same index is allowed; the source/window/
  filter fingerprint decides.

## 10. Acceptance criteria

1. No resume creates a tail-only file.
2. No resume duplicates a committed row or occurrence count.
3. Every crash point recovers with at most one chunk replay.
4. A missing/corrupt artifact/store yields restart, never a truncated success.
5. A partial/gapped job restarts instead of resuming its gaps.
6. Unknown schema/path/IO issues fail for manual intervention.
7. Retry lineage is recorded and cannot adopt another job's checkpoint.
8. Tests T7-T10 and the D3 matrix pass on Postgres and the filesystem profile.

## 11. Required tests

- Valid resume; artifact newer; artifact missing/shorter/corrupt/zip.
- Store missing/behind/ahead/unreadable.
- Crash at each checkpoint point.
- Fingerprint/lineage mismatch.
- Skipped batches/partial.
- Missing unmatched artifact.
- Unknown version/path escape/IO.
- Retry of a retry.
- Source data mutability (documented behavior).

## 12. Open questions

- Whether source log data in a completed window is immutable in practice.
- Whether a committed-prefix checksum is required for Release 1 or Release 2.
- Whether a store behind the checkpoint can be regenerated without re-querying
  source data (not planned for Release 1).
