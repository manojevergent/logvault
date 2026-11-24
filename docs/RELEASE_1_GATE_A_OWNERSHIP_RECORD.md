# Release 1 Gate A Ownership Record

Status: **UNSIGNED / NOT GRANTED.** No engineering owner, branch, or environment
is authorized by this record.

This record assigns the people and isolated environment for Gate A engineering
implementation. It does not grant Gate A by itself.

Canonical mapping: `RELEASE_1_GATE_A_CANONICAL_REGISTER.md`.
Section 2 fields describe the planned branch/worktree for S-00. Actual branch,
worktree, and base commit are recorded under E-03 after S-00 passes. Section 3
fields describe planned environment details for S-00; actual container and
database details are recorded under E-04.

## 1. Ownership

| Field | Value |
|---|---|
| Primary engineering owner | ______________________________ |
| Backup engineering owner | ______________________________ |
| Engineering manager | ______________________________ |
| Date assigned | ______________________________ |

Responsibilities:

- Primary owner: implement TPM, revisions, inert model declarations, and tests;
  maintain the evidence package; stop on any scope violation.
- Backup owner: take over if the primary is unavailable; independently review
  the migration graph, TPM behavior, and evidence.
- Engineering manager: confirm ownership and escalate blockers.

## 2. Branch/worktree

| Field | Value |
|---|---|
| Repository | `E:\last9_web_app` (or approved remote) |
| Branch name | ______________________________ |
| Worktree path | ______________________________ |
| Base commit | ______________________________ |
| Created by | ______________________________ |
| Date | ______________________________ |

Requirements:

- Dedicated branch/worktree, not `main`.
- No production credentials, deploy keys, or production DB URL.
- No application source changes outside the approved P1 scope.
- All work remains isolated until Gate B.

## 3. Isolated PostgreSQL 16 test environment

| Field | Value |
|---|---|
| Runtime | PostgreSQL 16.x |
| Container/image | `postgres:16-alpine` or approved equivalent |
| Container ID/name | ______________________________ |
| Host/port | ______________________________ |
| Database name | ______________________________ |
| Owner | ______________________________ |
| Provisioned date | ______________________________ |
| Production data present? | No |
| Sanitized fixtures only? | Yes |

Requirements:

- Disposable database/container.
- Never the production PostgreSQL instance.
- No production backup or restore credentials.
- Test data is synthetic or sanitized.
- Environment recorded in the Gate A approval record.

## 4. Isolation attestation

- [ ] Primary owner has no production DB credentials.
- [ ] Backup owner has no production DB credentials.
- [ ] Engineering worktree has no production deployment permissions.
- [ ] Engineering environment has no production `.env`/secret values.
- [ ] Test database is disposable and separate from production.
- [ ] No P2 behavior is enabled.

## 5. Evidence required

- Named primary and backup owners (management record).
- Branch/worktree path and base commit.
- Isolated environment container ID/DSN.
- Isolation confirmation signed by security/infrastructure.
- No-production-access evidence referenced in
  [`RELEASE_1_PRODUCTION_ISOLATION_CONFIRMATION.md`](./RELEASE_1_PRODUCTION_ISOLATION_CONFIRMATION.md).

## 6. Status

**UNSIGNED.** Gate A remains **NOT GRANTED**.
