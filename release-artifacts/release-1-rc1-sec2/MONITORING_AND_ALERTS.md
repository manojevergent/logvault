# Monitoring and alerting

Endpoint: GET /health/dispatch (API). Low cardinality: counts and ages only,
no job, customer or request identifiers.

## Database gauges

| Metric | Warn | Critical | Operator action |
|---|---|---|---|
| outbox_oldest_pending_age_s | 60 | 300 | Check beat, dispatcher, broker |
| outbox_dead | 1 | 5 | Inspect last_error, replay or fail the job |
| leases_expired | 1 | 10 | Worker health, Redis, task time limits |
| jobs_running_without_lease | 1 | 5 | Reconciler/claim loop |
| partial_jobs_24h | 1 | 50 | Inspect gap_reason |
| completed_without_pointer_24h | 1 | 5 | Artifact drift, runner log |

## Broker gauges

| Metric | Warn | Critical | Operator action |
|---|---|---|---|
| celery_queue_depth | 100 | 1000 | Scale workers, check Redis memory |
| beat_heartbeat_age_s | 120 | 300 | Beat service, guard lock, Redis |
| beat_lock | - | absent | Start exactly one beat |
| beat_lock_ttl_s | < 30 | - | Guard renewals failing |
| worker_online | - | 0 | Worker containers, DB/Redis connectivity |

Unavailable telemetry reports `unknown`, never a healthy zero.
worker_online is a Celery control ping with a 1.5 s timeout.
