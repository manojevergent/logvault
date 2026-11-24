# Release 1 Gate A Evidence Checklist

Status: **SUPERSEDED for evidence-ID governance.** Use
`RELEASE_1_GATE_A_CANONICAL_REGISTER.md`. This checklist retains its historical
detail. Gate A is **NOT GRANTED**.

An item is complete only when the named evidence exists and is signed/approved by
the responsible human owner.

## 1. Pre-Gate-A administrative evidence

| ID | Evidence | Required content | Owner | Pass criterion | Current status |
|---|---|---|---|---|---|
| EV-D11-01 | Signed D11 record | Business owner, role, date, FULL/REDUCED, rationale, signature | Business owner | Record is signed and matches scope | **UNSIGNED** |
| EV-OWN-01 | Primary engineering owner | Name, role, date, acknowledgement | Project owner | Named and accepted | **NOT ASSIGNED** |
| EV-OWN-02 | Backup engineering owner | Name, role, date, acknowledgement | Project owner | Named and accepted | **NOT ASSIGNED** |
| EV-OWN-03 | Engineering manager | Name, role, date | Project owner | Named | **NOT ASSIGNED** |
| EV-BR-01 | Branch/worktree | Branch name, worktree path, base commit, creator/date | Engineering | Dedicated branch, not `main` | **NOT CREATED** |
| EV-ENV-01 | Isolated PG16 environment | Image, container ID, host/port, DB name, PG16 version, owner/date | Engineering | Disposable, no production data | **NOT RECORDED** |
| EV-ISO-01 | No production DB credentials | Redacted inventory/attestation | Security/infrastructure | No production DB credential available | **UNSIGNED** |
| EV-ISO-02 | No production deployment permissions | CI/role evidence/attestation | Security/infrastructure | No production deploy permission | **UNSIGNED** |
| EV-ISO-03 | No production S3/Redis/Celery credentials | Redacted inventory/attestation | Security/infrastructure | None available | **UNSIGNED** |
| EV-ISO-04 | No production network access | Firewall/DNS/network policy evidence | Security/infrastructure | Production network restricted | **UNSIGNED** |
| EV-ISO-05 | No production `.env`/secret/deploy key | Redacted scan/attestation | Security/infrastructure | None mounted/available | **UNSIGNED** |
| EV-ISO-06 | Disposable test DB | Container/DB details | Engineering/security | Separate from production | **NOT RECORDED** |
| EV-ISO-07 | Synthetic/sanitized data | Data-source statement | Engineering/security | No unmasked production data | **NOT RECORDED** |
| EV-ISO-08 | No P2 behavior | Configuration/static scan | Engineering | No P2 flags/reads | **NOT VERIFIED** |
| EV-ISO-09 | No production config change capability | Role/access evidence | Security/infrastructure | No production config access | **UNSIGNED** |
| EV-GATEA-01 | Gate A approval record | D11 reference/selection, scope, authorized by, owners, branch, env, date, change record | Project owner | Signed and status GRANTED | **NOT GRANTED** |
| EV-SPEC-01 | Specification/test approval | Implementation spec and test spec accepted | Project owner/engineering | Approved | **EVIDENCE READY (docs)** |
| EV-TRACK-01 | Tracker consistency | G-01/G-07 BLOCKED; counts match evidence | Engineering | No unsupported APPROVED/VERIFIED | **CORRECTED (6/28)** |

## 2. Gate A implementation evidence

Required at Gate A exit; none is complete yet.

| ID | Evidence | Required content | Owner | Pass criterion | Current status |
|---|---|---|---|---|---|
| EV-IMP-01 | TPM implementation | `transaction_per_migration=True` review | Engineering | Prior revision commits when later fails | **NOT STARTED** |
| EV-IMP-02 | Revision files | `0032`, `0032b`, `0033`, `0034` (+ `0035`/`0036` if FULL) | Engineering | Files match spec | **NOT STARTED** |
| EV-IMP-03 | Graph validation | `alembic history`/`heads` | Engineering | One expected head; exact dependencies | **NOT STARTED** |
| EV-IMP-04 | Schema evidence | Columns/types/defaults/indexes | Engineering | Matches spec; no deferred indexes | **NOT STARTED** |
| EV-IMP-05 | Model/mirror consistency | API ORM + worker Core | Engineering | P1 columns match; no reads | **NOT STARTED** |
| EV-TEST-01 | Fresh DB test | Baseline 0031 + P1 revisions | Engineering | All apply; current expected head | **NOT STARTED** |
| EV-TEST-02 | Existing 0031 upgrade | Sanitized copy | Engineering | Data unchanged except new columns | **NOT STARTED** |
| EV-TEST-03 | TPM failure-boundary | Controlled later failure | Engineering | Prior committed; failing rolled back | **NOT STARTED** |
| EV-TEST-04 | Concurrent index validity | `pg_index.indisvalid` | Engineering | All authorized indexes valid | **NOT STARTED** |
| EV-TEST-05 | Invalid-index recovery | Drop/rebuild drill | Engineering | Rebuild valid; version correct | **NOT STARTED** |
| EV-TEST-06 | Migration interruption | Process kill/lock timeout | Engineering | Prior version intact; recovery works | **NOT STARTED** |
| EV-TEST-07 | Statement timeout | Controlled slow statement | Engineering | Only current revision aborts | **NOT STARTED** |
| EV-TEST-08 | Old API/worker compatibility | Old images against migrated copy | Engineering | No response/schema/task failure | **NOT STARTED** |
| EV-TEST-09 | No P2 activation | Static scan/flag inventory | Engineering | No runtime reads/behavior | **NOT STARTED** |
| EV-TEST-10 | No production access | Evidence of isolation throughout | Engineering/security | No production connection/log | **NOT STARTED** |

## 3. Evidence acceptance rules

- A checked box without an artifact is not evidence.
- A rehearsal on synthetic revisions does not satisfy P1-specific tests.
- A document saying “no production access” is not a security attestation.
- A branch on `main` is not a dedicated engineering branch.
- An image being present is not a provisioned isolated environment.
- Gate A cannot be granted on partial administrative evidence.
- Gate B cannot be granted on Gate A evidence alone.

## 4. Current summary

| Area | Status |
|---|---|
| D11 | UNSIGNED |
| Owners | NOT ASSIGNED |
| Branch/worktree | NOT CREATED |
| Isolated environment | NOT RECORDED |
| Production isolation | UNSIGNED |
| Gate A approval | NOT GRANTED |
| Implementation evidence | NOT STARTED |
| Gate A exit | NOT READY |

## 5. Stop condition

This is an evidence checklist. Do not create migrations, modify code, access
production, or grant authorization.
