# Gate B readiness checklist

Gate B is a separate production authorisation. It is NOT GRANTED.
Nothing below has been executed against production.

## Completed on disposable infrastructure

| Check | Evidence | Status |
|---|---|---|
| Database backup | pg_dump -Fc, 439 ms, 51,978 bytes | DONE (disposable) |
| Restore into isolated instance | pg_restore 586 ms, version 0034, jobs/outbox/pointers 24/19/10, 0 invalid indexes | DONE (disposable) |
| Migration upgrade 0031 -> 0034 | executed, head 0034 | DONE |
| Migration downgrade 0034 -> 0031 | executed, 4 revisions | DONE |
| Lock timeout | LockNotAvailable, version unchanged, no partial columns | DONE |
| Statement timeout | QueryCanceled, version unchanged | DONE |
| Rollback drain drill | four gates 0/0, downgrade clean, 4 non-terminal jobs recoverable | DONE |
| Application deployment rehearsal | isolated stack, /ready ok, dispatch health ok | DONE (disposable) |
| Worker recovery | SIGKILL, reconcile, reclaim with higher token, 12 unique records | DONE |
| Rollback rehearsal | drain + downgrade on disposable only | DONE (disposable) |

## Requires production infrastructure or separate approval

| Check | Why it cannot be done now |
|---|---|
| Production-scale backup | needs production database access (forbidden) |
| Restore timing at production volume | needs production-sized dataset |
| Migration duration and lock impact at scale | needs production-scale rehearsal |
| Monitoring/alert delivery to the real alerting channel | needs production endpoints |
| Deployment window | needs operational scheduling |
| Go/no-go with named owners | requires people to be named and available |

## Go/no-go criteria for the production window

1. Signed Gate B authorisation.
2. Verified backup with recorded restore test from that same backup.
3. Migration plan timed on production-scale data.
4. Rollback decision tree agreed, drain gate understood.
5. On-call owner and escalation contact named.
6. Monitoring receiving /health/dispatch.
