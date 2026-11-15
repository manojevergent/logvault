# Monitoring fix evidence (release-1-rc1-monitoring-fix1)

Command: curl http://<api>/health/dispatch  (image, no source mounts)

status=warn
lock_present=1.0  lock_ttl=90.0
heartbeat_age_s=28.97  worker_online=1.0  queue=0.0
broker: queue ok, heartbeat ok, lock ok, worker ok
db: outbox_age ok, outbox_dead warn, leases ok, running_without_lease ok,
    partial_24h warn, completed_without_pointer warn

status=warn reflects residual test data in the disposable database
(dead outbox rows, partial jobs, completed jobs without pointers). It is not
suppressed.
