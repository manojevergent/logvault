# F-01 lease renewal fix - evidence

Defect: heartbeat.py existed but the real runner never renewed the lease. Claim
TTL 60s. Every job longer than a minute held an expired lease; the reconciler
fenced and redispatched a healthy worker.

Fix (worker/app/runner.py):
  line 673  chunk commit: renew before the checkpoint write, same transaction
  line 702  row-flow status check (~20s, inside the TTL)
  both check the return value and raise if the lease is gone

Test (worker/tests/test_runner.py):
  test_progress_extends_the_lease_so_a_long_chunk_is_never_reaped
  asserts renewal happened with the job's own token

Integration (real PostgreSQL 16, no mocked clock):
  renewal extends lease_expires_at; reconciler leaves the job alone
  silence -> reconciler fences (token+1, owner cleared)
  stale renewal with the old token returns False
  concurrent claims -> one winner

Limitation: no test drives the full runner for longer than the TTL in real time;
the integration test exercises the same functions the runner calls.
