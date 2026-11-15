# Release 1 Production Isolation Confirmation

Status: **UNSIGNED.** No isolation is confirmed by this record. Gate A remains
**NOT GRANTED**.

This record must be completed by the responsible security/infrastructure owner
before Gate A is granted.

Canonical mapping: `RELEASE_1_GATE_A_CANONICAL_REGISTER.md`.
ISO-01..ISO-10 map to SEC-PRE-01..08 and SEC-POST-01..06. S-00 certifies
planned controls only; S-01 certifies the actual environment. Security P2
configuration is EV-SEC-P2-01; engineering P2 behavior is EV-ENG-P2-01.

## 1. Confirmations

| ID | Confirmation | Yes/No | Evidence |
|---|---|---|---|
| ISO-01 | Engineering environment has no production database credentials | | |
| ISO-02 | Engineering environment has no production deployment permissions | | |
| ISO-03 | Engineering environment has no production S3/Redis/Celery credentials | | |
| ISO-04 | Engineering worktree is not the production deployment branch | | |
| ISO-05 | No production `.env`, secret, or deploy key is mounted/available | | |
| ISO-06 | Test database is disposable and separate from production | | |
| ISO-07 | Test data is synthetic or sanitized | | |
| ISO-08 | No P2 runtime behavior is enabled | | |
| ISO-09 | No production configuration can be changed from the engineering environment | | |
| ISO-10 | Production network access is restricted/unavailable from the engineering environment | | |

## 2. Evidence required

- Redacted environment/secret inventory showing no production credentials.
- CI/deployment role list showing no production deploy permission.
- Network policy/firewall/DNS evidence showing production network access is
  restricted from the engineering environment.
- Branch/worktree path and base commit.
- Isolated environment container ID/DSN.
- Security/infrastructure attestation.

Do not attach actual secrets or credentials.

## 3. Responsible owner

| Field | Value |
|---|---|
| Security/infrastructure owner | ______________________________ |
| Role/title | ______________________________ |
| Date | ______________________________ |
| Signature | ______________________________ |

## 4. Effect

Until all applicable confirmations are YES and signed:

- Gate A must not be granted.
- No production migration, deployment, or configuration change is permitted.
- Engineering work remains limited to isolated test infrastructure.

## 5. Status

**UNSIGNED — production isolation is not confirmed.**
