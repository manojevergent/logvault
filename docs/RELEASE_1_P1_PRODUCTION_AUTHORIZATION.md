# Release 1 P1 Production Authorization

Status: **Gate B design only. Production P1 migration is NOT authorized.** No
production migration, schema change, deployment, or configuration change was
made.

## 0. Production operator and recovery runbook

Gate B requires the current approved
`docs/RELEASE_1_P1_FINAL_OPERATOR_RUNBOOK.md`. The superseded
`docs/RELEASE_1_P1_OPERATOR_RUNBOOK.md` must not be used for production.

Gate A is defined in
[`RELEASE_1_P1_ENGINEERING_AUTHORIZATION.md`](./RELEASE_1_P1_ENGINEERING_AUTHORIZATION.md).

## 1. Purpose

Gate B authorizes the P1 migration against the production database after Gate A
engineering implementation and validation are complete, and after production
recovery evidence is approved.

Gate B is separate from Gate A. Gate A success does not imply Gate B approval.

## 2. Gate B scope

Permitted only after explicit approval:

- Apply `0032`, `0032b`, `0033`, `0034`, `0035`, `0036` to production using the
  approved operator runbook.
- Pause/resume the backup sidecar around the window.
- Perform post-revision verification and health checks.
- Execute the approved rollback/forward-fix path if needed.

Still prohibited under Gate B:

- P2 behavior or implementation.
- Runtime reads of the new columns/tables by API/worker/scheduler.
- Outbox dispatch, schedule scanning, attempt paths, S3 publication, or fencing.
- Unapproved schema changes outside the six P1 revisions.
- Unapproved Redis/S3/Celery/deployment changes.
- `alembic upgrade head`.

## 3. Gate B preconditions

### 3.1 Engineering evidence

- [ ] Gate A approved and complete.
- [ ] TPM implemented and reviewed.
- [ ] Six revisions exist with the approved graph.
- [ ] P1 migration tests pass (`T-P1-001..T-P1-014`).
- [ ] `0032` columns only; `0032b` indexes only.
- [ ] No deferred indexes in P1.
- [ ] `0035` has no jobs indexes.
- [ ] `0036` depends on `0035` and has no index.
- [ ] Model/mirror declarations are inert and consistent.
- [ ] No runtime behavior activated.

### 3.2 Production-sized evidence

- [ ] Database size, table/index/TOAST size, and row counts recorded.
- [ ] Baseline transaction and lock behavior recorded.
- [ ] Per-revision duration and lock wait measured on a production-sized copy.
- [ ] Index build duration and `indisvalid=true` measured.
- [ ] API/worker impact measured.
- [ ] Final `lock_timeout` and `statement_timeout` approved.
- [ ] Window fits the measured duration.

### 3.3 Recovery evidence

- [ ] Fresh production `pg_dump -Fc` taken.
- [ ] Dump non-zero and `pg_restore --list` exit 0.
- [ ] SHA-256 recorded.
- [ ] Off-host copy exists; checksum matches.
- [ ] Isolated production-sized restore passed; RTO measured.
- [ ] `LAST9_ENCRYPTION_KEY` available outside the backup; decrypt check passed.
- [ ] RPO approved.
- [ ] RTO approved or explicitly waived for the schema-only path.
- [ ] PITR decision recorded; if enabled, PITR restore tested.
- [ ] Forward-fix/downgrade/restore rehearsal passed.
- [ ] Backup sidecar pause procedure approved.

### 3.4 Operational evidence

- [ ] Final operator runbook approved.
- [ ] Stop conditions and recovery actions approved.
- [ ] Named migration owner, DBA, and operations contacts.
- [ ] Change window approved.
- [ ] Monitoring for locks, connections, API errors, worker health ready.
- [ ] Rollback decision authority named.
- [ ] Communication plan approved.

### 3.5 Scope and behavior

- [ ] No P2 flag or behavior enabled.
- [ ] Old API/worker compatibility verified.
- [ ] API response schemas unchanged.
- [ ] New tables empty before the window.
- [ ] No process reads the new columns/tables during P1.
- [ ] No production settings changed beyond the approved migration action.

## 4. Approval authorities

| Authority | Approves |
|---|---|
| Business/product | D11 scope; RPO/RTO/PITR acceptance |
| Engineering | TPM, revisions, tests, model mirrors |
| DBA | Production measurement, index validity, restore, rollback |
| Operations | Window, backup pause, monitoring, runbook |
| Change management | Production change record |
| Final authorizer | Gate B production migration |

No single role may silently satisfy another's approval.

## 5. Gate B execution conditions

- Use individual revisions only; no `upgrade head`.
- Apply in order: `0032`, `0032b`, `0033`, `0034`, `0035`, `0036`.
- Verify after every revision.
- Stop on lock timeout, statement timeout, invalid index, long lock queue, API
  health degradation, or worker heartbeat loss.
- Do not continue to P2 in the same window.

## 6. Gate B exit evidence

- `alembic current=0036`.
- All P1 objects present; no deferred indexes.
- All P1 indexes `indisvalid=true`.
- `jobs` row counts/data unchanged except new columns.
- New tables empty.
- API/worker healthy.
- No P2 behavior.
- Evidence and operator sign-off recorded.

## 7. Gate B approval record

| Field | Value |
|---|---|
| Gate | B — production P1 migration |
| Authorized by | _pending_ |
| Date | _pending_ |
| Production environment | _pending_ |
| Change record | _pending_ |
| Migration window | _pending_ |
| Migration owner | _pending_ |
| DBA/operations | _pending_ |
| Revisions | `0032`, `0032b`, `0033`, `0034`, `0035`, `0036` |
| Rollback authority | _pending_ |
| Evidence reference | _pending_ |
| P2 | **prohibited** |

Until this record is completed, Gate B is not granted.

## 8. Stop conditions

Gate B is automatically NO-GO if:

- Gate A is incomplete.
- TPM is absent.
- A deferred index appears.
- `0032` or `0035` contains indexes.
- `0036` contains an index.
- Production-sized measurement is absent.
- Backup is missing, zero-byte, or fails `pg_restore --list`.
- Backup is not off-host.
- RPO/RTO/PITR decisions are unrecorded.
- Operator runbook is unapproved.
- Migration owner or window is unnamed.
- Any P2 behavior is planned in the same deployment.

## 9. Stop condition

This is a Gate B definition. Do not apply migrations to production, modify
production settings, or begin P2. Production P1 migration remains unauthorized.
