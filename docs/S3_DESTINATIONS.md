# S3 destinations

Completed extractions can be uploaded to Amazon S3 (or any S3-compatible store)
in addition to being kept locally for download and retention.

## Concepts

- **S3 profile** — a reusable destination: bucket, region, optional key prefix,
  optional S3-compatible endpoint, and optional credentials. Profiles live
  under **Manage → S3 destinations**.
- **Default destination** — a saved search and a schedule can each select one
  profile. Jobs created from them inherit it automatically.
- **Snapshot** — when a job is created, the profile's bucket/region/prefix is
  copied onto the job (`s3_destination`). Editing or deleting the profile later
  never rewrites where a historical run says it went.

## Credentials

Leave the access key fields blank to use the worker's IAM role (or any other
default AWS credential chain). Supplying keys encrypts them with
`LAST9_ENCRYPTION_KEY`, the same key used for Last9 and New Relic secrets.

For MinIO/Ceph/LocalStack, set the endpoint and enable **Force path-style
addressing**. The **Test** button writes and removes a small object under the
prefix, proving the bucket is writable.

## Object layout

```
s3://<bucket>/<prefix>/<customer>/<search>_<job id>_<timeframe>.csv.zip
s3://<bucket>/<prefix>/<customer>/<search>_<job id>_<timeframe>_summary.csv.zip
s3://<bucket>/<prefix>/<customer>/<search>_<job id>_<timeframe>_counts.csv.zip
```

The customer segment is omitted when a search has no customer. Artifacts are
uploaded exactly as stored (zipped when `ZIP_EXPORTS` is on), so the S3 copy
matches the downloadable file byte for byte.

## When it runs

- **Scheduled runs** — each day's/interval's job uploads on completion, using
  the schedule's selected profile.
- **One-off and batch runs** — a job created from a saved search inherits that
  search's profile. The wizard also lets you pick or override a destination.
- **Previews** — `Test filter` runs are never uploaded.
- **BigQuery-format runs** — uploaded as the BigQuery CSV, after the BQ load.

The local file stays in place: S3 is an additional copy. A failed upload never
fails the extraction — the job still completes and stays downloadable.

## Failure handling and retry

An upload failure is recorded on the job:

- `s3_error` — the reason, per artifact where applicable
- a `warn` event in the job's live feed
- a failure alert if the job belongs to a schedule with alert recipients

The job detail page shows an **S3 delivery** card with status, destination, and
artifact URIs. **Retry upload** queues `logvault.upload_job_s3`, which re-sends
the existing local files without re-querying Last9.

## Retention interaction

`EXPORT_RETENTION_DAYS` eventually deletes local files. Uploaded artifacts are
unaffected — S3 lifecycle rules, not LogVault, govern how long they live.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/s3-profiles` | List profiles (secrets masked). |
| `POST` | `/s3-profiles` | Create a profile (admin). |
| `PUT` | `/s3-profiles/{id}` | Update bucket/prefix/keys (admin). |
| `DELETE` | `/s3-profiles/{id}` | Delete an unused profile (admin). |
| `POST` | `/s3-profiles/{id}/test` | Write+remove a probe object. |
| `POST` | `/jobs/{id}/s3-upload` | Retry delivery for a completed job. |

Exports (`/jobs/{id}/export`, `/schedules/{id}/export`) reference a profile by
name, so a config can be imported where profile ids differ.

## Setup

1. Create the bucket and any IAM policy that allows `s3:PutObject` (plus
   `s3:DeleteObject` if you want the test cleanup to succeed).
2. **Manage → S3 destinations → New S3 profile**, then **Test**.
3. On the saved search or schedule, choose the profile under
   **S3 destination**. New runs upload automatically.

## Operational notes

- Each artifact upload is a single `upload_file` call with botocore's standard
  retry mode (5 attempts). Very large extracts rely on boto3's managed
  multipart transfer, so memory use stays bounded.
- Uploads run inside the job's Celery task, before the job is marked complete.
  A long upload therefore delays the completion timestamp but not the row data.
- If the worker runs with an IAM role, no credentials need to be stored at all.
