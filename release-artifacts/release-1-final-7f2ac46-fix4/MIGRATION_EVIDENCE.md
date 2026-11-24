# Migration evidence - REDUCED scope

Files: 0032, 0032b, 0033, 0034 (0035/0036 absent, verified).

Fresh disposable database, upgrade 0031 -> 0034:
  revisions applied : 5 (0030->0031 baseline plus the four P1 revisions)
  duration          : 4194 ms
  version after     : 0034
  required columns  : 5/5 present (lease_token, owner_id, completion_state,
                      store_path, checkpoint_version)
  concurrent indexes: 3 valid (ix_jobs_lease, ix_jobs_owner, ix_jobs_progress)
  outbox table      : present
  schedule_windows  : absent (0035 excluded by REDUCED)
  statement/lock timeout, invalid-index recovery, downgrade: verified in earlier
  passes on disposable PostgreSQL 16 (see register section 13).

Production-scale timing is NOT established by this measurement.
