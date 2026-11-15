# Disposable environment evidence - test residue reset

Date: 2026-11-15
Database: p1test on last9_p1_pg16 (disposable, isolated p1_e2e network)
Purpose: clear test-created `running` rows so /health/dispatch would not report a
critical state caused by test data rather than a real defect.

Before:
  SELECT count(*) FROM jobs WHERE status='running' AND lease_expires_at IS NULL;  -- 204
  SELECT min(id)||'-'||max(id) FROM jobs WHERE status='running' AND lease_expires_at IS NULL;
  -- 950001-991002

Action (one statement, bounded to the disposable test id range):
  UPDATE jobs SET status='failed',
         error_message='test residue: abandoned running row',
         finished_at=now()
   WHERE status='running' AND lease_expires_at IS NULL AND id >= 900000;
  -- UPDATE 204

After:
  SELECT count(*) FROM jobs WHERE status='running' AND lease_expires_at IS NULL;  -- 0

Scope statement: this reset was applied ONLY to the disposable test database. It
must NOT be repeated against any shared, staging or production database. On a
real deployment, rows in this state are handled by the lease reconciler and the
rollback gates in the deployment runbook, not by an ad-hoc UPDATE.
