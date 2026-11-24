# Release 1 Gate A Final Authorization Checklist

Status: **NOT GRANTED.** No authorization is granted by this checklist. The
project owner must make the Gate A decision after the required evidence exists.

Gate B remains **NOT GRANTED**.

## 1. Gate A preconditions

| ID | Requirement | Status | Evidence required |
|---|---|---|---|
| A-01 | D11 signed FULL or REDUCED | **UNSIGNED** | Signed D11 record |
| A-02 | Primary engineering owner assigned | **NOT ASSIGNED** | Named owner/role/date |
| A-03 | Backup engineering owner assigned | **NOT ASSIGNED** | Named owner/role/date |
| A-04 | Engineering manager named | **NOT ASSIGNED** | Named manager/role/date |
| A-05 | Dedicated branch/worktree | **NOT CREATED** | Branch, worktree path, base commit |
| A-06 | Isolated PostgreSQL 16 environment | **NOT RECORDED** | Container ID/DSN, PG16 version, no production data |
| A-07 | No production DB credentials | **UNSIGNED** | Security/infrastructure attestation |
| A-08 | No production deployment permissions | **UNSIGNED** | Security/infrastructure attestation |
| A-09 | No production S3/Redis/Celery credentials | **UNSIGNED** | Redacted inventory/attestation |
| A-10 | Production network access restricted | **UNSIGNED** | Firewall/DNS/policy evidence |
| A-11 | No production `.env`/secret/deploy key | **UNSIGNED** | Redacted scan/attestation |
| A-12 | Disposable test DB + sanitized data | **NOT RECORDED** | Environment/data statement |
| A-13 | Gate A evidence package complete and independently reviewed | **HOLD** | EV-GATEA-PKG-01 |
| A-14 | Spec/test plan approved | **HOLD** | EV-SPEC-01: both paths, commit/version, individual SHA-256, approver/date |

**Gate A cannot be granted while A-01 through A-14 are unresolved.**

Canonical action/evidence source: `RELEASE_1_GATE_A_CANONICAL_REGISTER.md`.

## 2. Authorized scope

### D11 FULL

- `0032` — ownership/completion columns only.
- `0032b` — lease/owner/progress partial concurrent indexes.
- `0033` — artifact/checkpoint columns.
- `0034` — dispatch outbox table/indexes.
- `0035` — schedule_windows table + `jobs` window columns + new-table indexes.
- `0036` — S3 attempt columns; `down_revision="0035"`; no index.

### D11 REDUCED

- `0032` — ownership/completion columns only.
- `0032b` — lease/owner/progress partial concurrent indexes.
- `0033` — artifact/checkpoint columns.
- `0034` — dispatch outbox table/indexes.
- `0035` and `0036` are excluded.

No other revisions are authorized. `0035b`, `0036b`, `ix_jobs_retry_of`,
`ix_jobs_schedule_window_id`, and `ix_jobs_s3_uploading` remain deferred.

## 3. Prohibited regardless of scope

- P2 runtime behavior.
- Production database access or migration.
- Production schema change.
- Production deployment or configuration change.
- API/frontend/response changes.
- Dependency changes.
- Unapproved schema changes.
- Work outside the authorized branch/worktree.
- `alembic upgrade head` for P1 execution.

## 4. Gate A exit criteria

Gate A implementation is complete only when:

- [ ] All authorized revisions exist.
- [ ] Graph has exactly the expected single head.
- [ ] TPM is implemented and failure-boundary tested.
- [ ] All P1 migration tests pass.
- [ ] Failure injection passes.
- [ ] Invalid concurrent-index recovery passes.
- [ ] Old API and worker compatibility passes.
- [ ] Inert model declarations match the migration schema.
- [ ] No deferred index exists.
- [ ] No P2 behavior is activated.
- [ ] No production system was accessed or modified.
- [ ] Evidence is recorded and independently reviewed.

## 5. Final decision

**Current recommendation: DO NOT GRANT GATE A.**

Reason: the administrative prerequisites are unsigned or unassigned, and no P1
implementation evidence exists. Documentation completion is not implementation
or validation.

**Gate A: NOT GRANTED.**
**Gate B: NOT GRANTED.**

The project owner may make the Gate A decision only after A-01 through A-14 are
closed with actual evidence. This checklist does not grant authorization.
