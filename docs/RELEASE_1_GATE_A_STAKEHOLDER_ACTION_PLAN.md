# Release 1 Gate A Stakeholder Action Plan

Status: **SUPERSEDED for action-ID governance.** Use
`RELEASE_1_GATE_A_CANONICAL_REGISTER.md` as the authoritative action/evidence
source. This plan retains its historical detail. Gate A and Gate B remain
**NOT GRANTED**.

This package prepares the human approvals needed before Gate A. All approval
fields remain blank.

## 1. Review findings

### 1.1 Contradictions corrected

- The tracker previously marked G-01 **APPROVED** based on the status statement
  “Architecture decisions: CLOSED.” It is now **BLOCKED** until a signed D11
  record exists.
- G-07 is **BLOCKED** because it depends on D11.
- Active P1 documents now use the D11 record's REDUCED definition: exclude both
  `0035` and `0036`. Historical audit documents may still describe an earlier
  reduced variant; the D11 record is authoritative.

### 1.2 Missing approval fields

| Record | Missing fields |
|---|---|
| D11 business record | Business owner name, role, date, selected option, rationale, signature |
| Gate A ownership record | Primary owner, backup owner, engineering manager, branch name, worktree path, base commit, environment container/DSN |
| Production isolation confirmation | ISO-01..ISO-10 responses/evidence, security/infrastructure owner, role, date, signature |
| Gate A approval record | D11 reference/selection, scope, authorized by, owners, branch, environment, date, change record |

### 1.3 Unclear responsibilities

- **Business owner**: owns D11 only. Do not assume the project owner is the
  business owner.
- **Project owner**: assigns the primary/backup engineering owners and is the
  Gate A authorizer. The project owner does not sign D11 unless separately
  authorized as the business owner.
- **Engineering manager**: confirms engineering ownership and escalates
  blockers; does not grant Gate A.
- **Primary engineering owner**: implements within Gate A scope and owns the
  evidence package.
- **Backup engineering owner**: independent reviewer and continuity owner.
- **Security/infrastructure owner**: signs the production isolation
  confirmation; does not grant Gate A.

## 2. Business owner actions

### Action B-01 — D11 decision

Choose exactly one:

- [ ] **FULL** — authorize `0035` and `0036`.
  - `0035`: `schedule_windows` table, `jobs.schedule_window_id`,
    `jobs.attempt_no`, new-table indexes.
  - `0036`: S3 attempt columns; `down_revision="0035"`; no index.
  - `0035b`/`0036b` remain deferred to P7/P8.
- [ ] **REDUCED** — exclude both `0035` and `0036`.
  - P1 graph becomes `0031 -> 0032 -> 0032b -> 0033 -> 0034`.
  - No schedule-window table/columns and no S3 columns in P1.

Evidence required:

- Business owner name and role.
- Date.
- Selected option.
- Rationale.
- Signature.
- Decision recorded in the D11 record, decision register, authorization
  checklist, and tracker.

Consequences:

| Option | Benefit | Cost/risk |
|---|---|---|
| FULL | Complete P1 schema for ledger and S3; no later graph insertion for those columns | Larger Gate A scope; `0035` adds a brief `ACCESS EXCLUSIVE` lock; D11 business ownership |
| REDUCED | Smaller, faster Gate A; fewer locks | Ledger and S3 schema deferred; later revisions required; interval scope remains unresolved |

Owner/action: **Business owner** signs
[`RELEASE_1_D11_BUSINESS_APPROVAL_RECORD.md`](./RELEASE_1_D11_BUSINESS_APPROVAL_RECORD.md).

## 3. Project owner actions

### Action P-01 — Assign owners

Name:

- Primary engineering owner.
- Backup engineering owner.
- Engineering manager.
- Date assigned.

Evidence:

- Management/ownership record with names and roles.
- Acknowledgement from primary and backup owners.

Owner/action: **Project owner** records in
[`RELEASE_1_GATE_A_OWNERSHIP_RECORD.md`](./RELEASE_1_GATE_A_OWNERSHIP_RECORD.md).

### Action P-02 — Confirm Gate A scope

After D11 is signed:

- FULL: authorize `0032`, `0032b`, `0033`, `0034`, `0035`, `0036`.
- REDUCED: authorize `0032`, `0032b`, `0033`, `0034`.

Confirm:

- No P2 behavior.
- No production access/migration/deployment/config.
- No deferred indexes.
- No application/API/frontend behavior changes.
- No dependency changes.
- Work only in the dedicated branch/worktree.

Owner/action: **Project owner** completes
[`RELEASE_1_GATE_A_APPROVAL_RECORD.md`](./RELEASE_1_GATE_A_APPROVAL_RECORD.md).

### Action P-03 — Gate A decision

Do not grant Gate A until:

- D11 signed.
- Primary/backup owners named.
- Branch/worktree and environment recorded.
- Production isolation signed.
- Gate A record completed.

Owner/action: **Project owner** changes Gate A status only after evidence is
reviewed. This plan does not grant it.

## 4. Engineering actions

### Action E-01 — Dedicated branch/worktree

Record:

- Branch name.
- Worktree path.
- Base commit.
- Created by/date.

Requirements:

- Not `main`.
- No production credentials/deploy keys.
- No changes outside approved P1 scope.

### Action E-02 — Isolated PostgreSQL 16 environment

Record:

- Container/image.
- Container ID/name.
- Host/port.
- Database name.
- PG16 version.
- Owner/provisioned date.
- Confirmation of no production data and synthetic/sanitized fixtures only.

### Action E-03 — Implementation boundary acknowledgement

Acknowledge:

- Authorized revisions only (per D11).
- `0032` columns only.
- `0032b` indexes only.
- No deferred indexes.
- No P2 behavior.
- No application/API/frontend/dependency changes.
- No production access.

Owner/action: **Primary engineering owner**, with backup review.

## 5. Security/infrastructure actions

### Action S-01 — Production isolation attestation

Complete ISO-01..ISO-10:

- No production DB credentials.
- No production deployment permissions.
- No production S3/Redis/Celery credentials.
- Engineering worktree is not the production deployment branch.
- No production `.env`, secret, or deploy key.
- Disposable test database.
- Synthetic/sanitized data only.
- No P2 behavior.
- No production config changes.
- Production network access restricted/unavailable.

Evidence:

- Redacted secret/environment inventory.
- CI/deployment role list.
- Network policy/firewall/DNS evidence.
- Branch/worktree and environment records.
- Signed attestation.

Owner/action: **Security/infrastructure owner** signs
[`RELEASE_1_PRODUCTION_ISOLATION_CONFIRMATION.md`](./RELEASE_1_PRODUCTION_ISOLATION_CONFIRMATION.md).

## 6. Current status

| Item | Status |
|---|---|
| D11 | UNSIGNED |
| Primary owner | NOT ASSIGNED |
| Backup owner | NOT ASSIGNED |
| Branch/worktree | NOT CREATED |
| Isolated environment | NOT RECORDED |
| Production isolation | UNSIGNED |
| Gate A | NOT GRANTED |
| Gate B | NOT GRANTED |

## 7. Stop condition

This is an action plan. Do not create migrations, modify code or `env.py`/
`deploy.sh`, access production, or grant authorization. Await human signatures
and records.
