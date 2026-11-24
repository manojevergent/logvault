# Controlled extraction, artifact and pointer validation - access request

Status: BLOCKED. No Last9 credentials are available to the isolated environment,
so extraction success, artifact creation and pointer resolution remain NOT TESTED.

Required input (one of):
  A. a disposable Last9 credential scoped to a small index, valid for the test
     window; or
  B. a recorded fixture of Last9 responses replayed through the client.

Test steps once access exists:
 1. Seed credential + index target in the disposable database (id >= 900000).
 2. Create a job through the API for a narrow window (<= 1 hour, few thousand rows).
 3. Verify the outbox row, broker publication, worker claim and fencing token.
 4. Verify chunk checkpoints and completed_chunks increments.
 5. Verify the artifact exists under job_<id>/a<token>/ on the shared volume.
 6. Verify output_file_path is set and the file opens.
 7. Kill the worker mid-chunk; verify reconcile, reclaim with a higher token,
    resume from the checkpoint, and no duplicate or missing records.
 8. Verify completion_state='complete' and gap_count=0.
 9. Verify the frontend shows the job as completed and downloadable.

Data rules: synthetic or sanitized only; no customer data; no production bucket;
credentials revoked after the test.
