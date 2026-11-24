# Integration evidence and Last9 status

Final-image stack (isolated p1_e2e network, disposable PostgreSQL 16, isolated Redis):
  /ready                 {"status":"ok","checks":{"postgres":"ok","redis":"ok"}}
  /health/dispatch       status=warn, lock_present=1.0, beat_lock_ttl=90,
                         heartbeat_age=23.1s, worker_online=1.0, queue=0
  beat guard             "beat_guard: acquired logvault:beat:lock"
  worker                 registered, answering Celery control ping

Extraction against live Last9: NOT TESTED - LIVE LAST9 EXTRACTION VALIDATION
OUTSTANDING. No credentials are available to the isolated environment. Synthetic
job tests exercise dispatch, claim, fencing, outbox, recovery, checkpoint and
publication, but not the Last9 request path.
