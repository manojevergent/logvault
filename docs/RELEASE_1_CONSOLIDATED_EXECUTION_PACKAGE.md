# Release 1 - Consolidated Execution Package

Generated: 2026-11-14. Single package for scope closure, human approvals, and
technical execution tracking. Supersedes no existing record; it indexes them.

**Nothing in this package is an approval.** Every item is classified:

| Class | Meaning |
|---|---|
| PREPARED | Artifact exists and is ready for a human decision. No authority conveyed. |
| AWAITING HUMAN ACTION | Signature, assignment, or review required. |
| APPROVED | Signed by the named authority. **None.** |
| IMPLEMENTED | Code merged in an authorized environment. **None.** |
| TESTED | Test executed with captured output. **None.** |
| INDEPENDENTLY REVIEWED | Engineering Manager signed findings. **None.** |
| BLOCKED | Depends on an unsatisfied prerequisite. |
| NOT AUTHORIZED | Prohibited until an identified decision is recorded. |

Current overall state: **RELEASE 1 P1 IS 100% PREPARED, 0% IMPLEMENTED.**

---

## 1. Verified repository baseline

Verified by direct inspection, not assumed from prior documents.

| Item | Value |
|---|---|
| Branch | `main` (unmodified) |
| HEAD | `6719568f6fe7233e74aa151e3ba3531b2d6cb99d` |
| Tracked working-tree changes | **none** |
| Untracked files | **70** (`docs/`, `p0/`, `p1_rehearsal/`) |
| Alembic head | `0031_extraction_groups.py` |
| P1 migration files (`0032`-`0036`) | **0** |
| `transaction_per_migration` in `api/migrations/env.py` | absent |
| Production access used | **none** |

Pinned dependency versions (verified in `api/requirements.txt`,
`worker/requirements.txt`):

| Package | Version | Relevance |
|---|---|---|
| SQLAlchemy | 2.0.36 | `sa.BigInteger`, `sa.JSON`, `sa.text` all valid |
| Alembic | 1.14.0 | `autocommit_block()`, `postgresql_concurrently`, `postgresql_where` all supported |
| psycopg | 3.2.3 | PG16 driver |
| Celery | 5.4.0 | `acks_late`, `reject_on_worker_lost` present |
| redis | 5.2.1 | beat lock backend |
| pytest | 8.3.4 | test runner |

Authoritative documents re-verified this session:

| Document | Verified state |
|---|---|
| `RELEASE_1_GATE_A_CANONICAL_REGISTER.md` | Authoritative. B-01/P-01/P-03/P-04/P-05/M-01/A14-01/E-01/E-02/S-00/E-03/E-04/S-01/SEC-P2-01/ENG-P2-01 all HOLD. |
| `RELEASE_1_D11_BUSINESS_APPROVAL_RECORD.md` | **UNSIGNED** |
| `RELEASE_1_GATE_A_OWNERSHIP_RECORD.md` | **UNSIGNED / NOT GRANTED** |
| `RELEASE_1_GATE_A_APPROVAL_RECORD.md` | **NOT GRANTED** |
| `RELEASE_1_PRODUCTION_ISOLATION_CONFIRMATION.md` | **UNSIGNED** |
| `RELEASE_1_P1_IMPLEMENTATION_SPECIFICATION.md` | 231 lines, schema-only, A14-01 HOLD |
| `RELEASE_1_P1_IMPLEMENTATION_TEST_SPEC.md` | 175 lines, A14-01 HOLD |

Frozen specifications (FREEZE-1, 2026-11-14). Both are untracked; neither is
approved. These are the versions submitted to M-01 and the versions A14-01 must
cite if the review produces no changes.

| File | Frozen SHA-256 | Pre-freeze SHA-256 |
|---|---|---|
| `docs/RELEASE_1_CONSOLIDATED_IMPLEMENTATION_SPECIFICATION_DRAFT.md` | `7BFD48D70B3E66F6CBEB4696B0DC266C90D1618D58ED816CBEE0C0EF1A915BF3` | `7C6E2850...124CAE6` |
| `docs/RELEASE_1_CONSOLIDATED_TEST_SPECIFICATION_DRAFT.md` | `FC3C7CD6B0CE7513C08B81AD0266484FA81E9E1FE33604558EF2466926F8F308` | `F65B6536...34E03A18` |

Governance record amended this cycle:
`RELEASE_1_GATE_A_CANONICAL_REGISTER.md` §12 (attestation separation, C-3).

---

## 2. Authorization matrix

| Action | Scope | Owner | State | Evidence |
|---|---|---|---|---|
| B-01 | D11 FULL/REDUCED | Business Owner | HOLD - UNSIGNED | EV-D11-01 |
| P-01 | Primary/backup engineers, manager | Project Owner | HOLD - NOT ASSIGNED | EV-OWN-01/02/03 |
| P-02 | Gate A scope confirmation matching D11 | Project Owner | HOLD - BLOCKED by B-01 | EV-SCOPE-01 |
| P-04 | Records custodian | Project Owner | HOLD - NOT ASSIGNED | EV-REC-01 |
| P-05 | A-14 approval authority | Project Owner | HOLD - UNCONFIRMED | EV-A14-AUTH-01 |
| M-01 | Technical review of both specs | Engineering Manager | HOLD - NOT STARTED | EV-A14-REV-01 |
| A14-01 | Both specifications approved | Project Owner | HOLD - NOT APPROVED | EV-SPEC-01 |
| E-01 / E-02 | Engineer acknowledgements | Primary / Backup | HOLD | EV-ACK-01/02 |
| S-00 | Pre-provisioning isolation | Security | HOLD - NOT STARTED | SEC-PRE-01..08 |
| E-03 | Branch/worktree | Primary | HOLD - blocked by S-00 | EV-BR-01 |
| E-04 | Disposable PG16 | Primary | HOLD - blocked by S-00 | EV-ENV-01 |
| S-01 | Post-provisioning isolation | Security | HOLD - blocked by E-04 | SEC-POST-01..06 |
| SEC-P2-01 | Security P2 attestation | Security | HOLD | EV-SEC-P2-01 |
| ENG-P2-01 | Engineering P2 attestation | Engineering | HOLD | EV-ENG-P2-01 |
| A-13 | Evidence package + independent review | P-04 / M-01 | HOLD | EV-GATEA-PKG-01 |
| P-03 | Gate A decision | Project Owner | **NOT GRANTED** | EV-GATEA-01 |
| Gate B | Production migration/deployment | Separate authority | **NOT GRANTED** | - |

**No action in this table is satisfied.** Nothing may be inferred from the
Project Owner's authorization to proceed with engineering: that authorization
permits this package and the single Gate A decision, and nothing else.

---

## 3. Consolidated Release 1 technical scope

Fourteen capabilities, treated as one interdependent outcome. Full detail with
DDL, invariants, and SQL guards: `RELEASE_1_CONSOLIDATED_IMPLEMENTATION_SPECIFICATION_DRAFT.md`.

| # | Capability | Component | Former phase |
|---|---|---|---|
| 1 | Transactional dispatch outbox | R1-C01 writer, R1-C02 dispatcher | schema + P6 |
| 2 | Database worker ownership | R1-C03 | P2 |
| 3 | Monotonic lease-token fencing | R1-C03, R1-C04 | P2 |
| 4 | Progress-aware heartbeat | R1-C05 | P2 |
| 5 | Lease-expiry detection and redispatch | R1-C06 | P2/P6 |
| 6 | Duplicate-dispatch protection | R1-C07 | P2 |
| 7 | Safe retry and recovery | R1-C08 | P2/P9 |
| 8 | Attempt-specific artifact paths | R1-C09 | P4 |
| 9 | Strict checkpoint validation | R1-C11 | P4 |
| 10 | Atomic publication pointer | R1-C10 | P4/P8 |
| 11 | Partial-completion reporting | R1-C12 | P2/P3 |
| 12 | Dedicated Celery beat | R1-C13 | P7 |
| 13 | Schema and migrations | R1-C14 | P1 |
| 14 | Integration and failure-recovery tests | R1-C15 | P1-P8 |

Deliverable size, from the drafts: 4 migrations (6 if FULL), 1 edit to
`api/migrations/env.py`, 6 new worker modules, 9 existing modules touched,
14 migration tests carried forward + 40 new runtime tests.

---

## 4. Scope conflicts requiring a formal decision

These are not stylistic. Each one blocks a specific downstream action.

### C-1 - A14-01 evidence names the two schema-only files

`EV-SPEC-01` requires these exact paths:
`RELEASE_1_P1_IMPLEMENTATION_SPECIFICATION.md` and
`RELEASE_1_P1_IMPLEMENTATION_TEST_SPEC.md`. Those files contain the
schema-only scope. The consolidated scope lives in two new draft files. As
written, A14-01 cannot approve the consolidated scope and satisfy its own
evidence definition.

Two resolutions. **Recommendation: adopt in place.**

| Option | Action | Consequence |
|---|---|---|
| **A-1 (recommended)** | Replace the two HOLD files' content with the consolidated drafts; delete the drafts | EV-SPEC-01 paths stay valid; no register amendment; single authoritative spec per purpose |
| A-2 | Amend `EV-SPEC-01` to name the draft paths | Requires a register edit and a re-issued evidence definition |

Either option is legal because neither HOLD file has ever been approved, so no
approval is invalidated by the change. Requires Project Owner decision.

### C-2 - The P1 specification states the opposite of the consolidated scope

`RELEASE_1_P1_IMPLEMENTATION_SPECIFICATION.md` §12 reads: "P1 owns additive
columns/tables/indexes... P2 owns: claim/fencing; heartbeat/progress renewal;
stale-worker rejection; cancel/pause semantics; lease-expiry reconciler; any
read of the new state." Section 14 says "Stop condition... Do not create
migrations or modify code."

Approving the consolidated scope **supersedes §12 and §14**. That supersession
must be recorded explicitly, or an auditor will find two contradictory
authorities. The consolidated draft already carries the schema contract forward
unchanged, so this is a wording supersession, not a technical change.

### C-3 - The P2 exclusion attestations contradict the consolidated scope

`ENG-P2-01` / `EV-ENG-P2-01` is defined as: "Engineering attests no P2 code
paths, reads, tasks, runtime behavior; P2 excluded." `ISO-08` is "No P2 runtime
behavior is enabled."

If the consolidated scope authorizes claim, fencing, heartbeat, and
redispatch - the behaviors the register calls P2 - then this attestation is
**impossible to sign truthfully** after implementation. Two meanings of "P2"
have collided:

- **P2-as-security/config** (the credential, flag, and production-configuration
  exclusion) - must remain attested, and the consolidated scope does not touch it.
- **P2-as-dispatch-runtime** - now authorized inside this scope, so its absence
  can no longer be attested.

Required correction before A14-01: re-scope `ISO-08`, `SEC-PRE-08`,
`SEC-POST-06`, `EV-SEC-P2-01`, and `EV-ENG-P2-01` to mean the security and
configuration exclusion only, and add one new engineering attestation covering
the authorized dispatch runtime (presence of the authorized components, absence
of anything else). **Without this, Gate A's A-13 package cannot be completed
honestly.** This is the single most consequential finding in this package.

### C-4 - D11 is not a preference, it changes `0036`'s definition

`0036.down_revision = "0035"` under FULL. Under REDUCED, `0035` does not exist,
so `0036` cannot exist in that form at all. Authoring `0036` before the D11
signature would produce a file that must be deleted or rewritten. Also,
`RELEASE_1_D11_BUSINESS_APPROVAL_RECORD.md` §5 requires the tracker to show
G-01 and G-07 as BLOCKED until signature.

### C-5 - No commit exists to anchor the evidence chain

`EV-SPEC-01` requires "Git commit SHA or approved document version". All 70
governance documents are untracked; `main` is at `6719568f6...` and contains
none of them. A hash of an untracked file is reproducible but the file is not
versioned. Options:

| Option | Action |
|---|---|
| B-1 | Record "approved document version + individual SHA-256" in EV-SPEC-01, accepting no commit anchor |
| B-2 | Commit the governance documents on a non-`main` branch under separate approval, then cite that commit |

Recommendation: **B-2**, because it makes hashes auditable and reversible. It
requires a separate commit approval that has not been granted, and it must not
use `git add .`.

---

### 4.6 Decision log

| ID | Decision | Owner statement | Applied as |
|---|---|---|---|
| C-1 | APPROVED WITH MODIFICATION | Adopt consolidated specs as authoritative after review and approval; retain drafts as superseded historical; keep paths, versions, hashes | Freeze-1 recorded in §1; adoption clause written into both spec headers; no file deleted |
| C-3 | APPROVED WITH MODIFICATION | Two separate attestations: security capabilities absent; engineering matches approved scope. Neither authorizes more P2. Record definition; update dependencies | `RELEASE_1_GATE_A_CANONICAL_REGISTER.md` §12 amendment; original wording preserved |
| C-5 | DECIDED | Dedicated governance docs branch, separate from engineering branch; exact-path verification; no `git add .`; no `main` change; record commit SHA and both hashes; plan first | §10.2 commit plan prepared, not executed |
| D11 | **OPEN** | Business Owner selects FULL or REDUCED | Not applied. Cannot be |
| P-01 | **OPEN** | Names not yet supplied (placeholders in the Project Owner response) | Not applied. Names must not be invented |

C-1 note: because the Project Owner directed that the consolidated specifications
be adopted, and `EV-SPEC-01` names the two existing canonical paths, A14-01's
hash record must cite either (a) the two frozen files above, with `EV-SPEC-01`
amended to name them, or (b) the two canonical files after content adoption.
This is the last open sub-question of C-1 and it is resolved at A14-01, not now.

## 5. Outstanding human approval requests

Each request below is executable as written. No stakeholder must read a long
document to act.

### 5.1 Business Owner - B-01, D11 decision

Decision required: authorize the schedule-window ledger and S3 attempt schema,
or not.

| | FULL | REDUCED |
|---|---|---|
| Migrations | `0032`, `0032b`, `0033`, `0034`, `0035`, `0036` | `0032`, `0032b`, `0033`, `0034` |
| Schedule ledger (`schedule_windows`, `jobs.schedule_window_id`, `attempt_no`) | included | excluded |
| S3 attempt columns (`s3_attempt_token`, `s3_uploading_at`, `s3_published_attempt`, `s3_manifest_uri`) | included | excluded |
| Schedule duplicate-job prevention | constraint-backed in the database | must rely on `last_run_at` comparison, weaker under concurrent beat |
| S3 retry lineage | recorded per attempt | not recorded in the schema |
| Deferred either way | `0035b`, `0036b`, and all non-listed indexes | same, plus `0035`/`0036` entirely |
| Migration count | 6 | 4 |
| Reversibility | `0036` -> `0035` -> `0034` -> `0033` -> `0032b` -> `0032` | shorter chain |
| Business effect | schedule windows become an auditable database record; partial S3 attempts traceable | neither is recorded; a repeated schedule tick depends on application logic alone |

Technical position, stated once: the message-dispatch runtime in scope does not
depend on D11. Both options deliver a reliable dispatcher. FULL adds the
schedule ledger and S3 attempt lineage; REDUCED defers them and leaves schedule
deduplication to the scheduler.

Fill in `RELEASE_1_D11_BUSINESS_APPROVAL_RECORD.md` §2 and sign. Fields:

```text
Business owner name : ______________________
Role/title          : ______________________
Date                : ______________________
Selected option     : FULL / REDUCED
Rationale           : ______________________
Signature           : ______________________
```

Evidence: `EV-D11-01`. Owner must be the authorized Release 1 business owner.
The engineering agent cannot sign.

### 5.2 Project Owner - P-01, assignments

Fill `RELEASE_1_GATE_A_OWNERSHIP_RECORD.md` §1:

```text
Primary engineering owner : ______________________
Backup engineering owner  : ______________________
Engineering manager       : ______________________
Date assigned             : ______________________
```

Acceptance criteria per role:

| Role | Must accept |
|---|---|
| Primary | Implements TPM, revisions, model declarations, tests; maintains evidence; halts on any scope violation |
| Backup | Takes over if primary unavailable; independently verifies migration graph, TPM behavior, evidence |
| Manager | Confirms ownership; performs M-01; escalates blockers |

Evidence: `EV-OWN-01`, `EV-OWN-02`, `EV-OWN-03`.

### 5.3 Project Owner - P-04, records custodian

```text
Records custodian : ______________________
Date assigned     : ______________________
```

Duties: hold the signed D11; propagate the selected scope into
`RELEASE_1_FINAL_DECISION_REGISTER.md`,
`RELEASE_1_GATE_A_FINAL_AUTHORIZATION_CHECKLIST.md`, and
`RELEASE_1_P1_EXECUTION_TRACKER.md`; keep evidence references consistent; obtain
Backup Engineer verification. Evidence: `EV-REC-01`.

### 5.4 Project Owner - P-05, A-14 authority

```text
A-14 approval authority : ______________________
Confirmation            : Y / N
Date                    : ______________________
```

Question to answer: is the named person authorized to approve A14-01 on behalf
of the Project Owner, and do they accept? Evidence: `EV-A14-AUTH-01`.

### 5.5 Security - S-00, pre-provisioning verification

Planned environment for verification (no provisioning performed):

| Planned item | Value |
|---|---|
| Repository | `E:\last9_web_app` |
| Intended branch | `release-1/p1-dispatch` (proposed, not created) |
| Intended worktree | `..\last9_web_app-p1` (proposed, not created) |
| Base commit | `6719568f6fe7233e74aa151e3ba3531b2d6cb99d` |
| PostgreSQL | `postgres:16-alpine`, disposable container, non-default port |
| Database name | `last9_p1_test` |
| Redis | disposable container, separate port and DB index |
| Celery broker | same disposable Redis; no shared keyspace |
| S3 | local stub or MinIO container; no real bucket or credentials |
| Test data | synthetic or sanitized only |
| Production DB | not reachable, not referenced |
| Production credentials | none available |
| Production deploy permissions | none |
| Cleanup | container and volume destroyed after evidence capture |

Verify `SEC-PRE-01`..`SEC-PRE-08` against the plan above and sign
`RELEASE_1_PRODUCTION_ISOLATION_CONFIRMATION.md` §1/§3. Nine controls:

| ID | Control to verify |
|---|---|
| SEC-PRE-01 | No production DB credentials |
| SEC-PRE-02 | No production deployment permissions |
| SEC-PRE-03 | No production S3/Redis/Celery credentials |
| SEC-PRE-04 | No production network access |
| SEC-PRE-05 | No production `.env`, secret, or deploy key |
| SEC-PRE-06 | PG16 disposable; synthetic/sanitized data only |
| SEC-PRE-07 | Branch/worktree is not production |
| SEC-PRE-08 | No production P2 configuration or flags |

### 5.6 Engineering Manager - M-01, review

Review package in §6 below. Output required: APPROVED / APPROVED WITH
CONDITIONS / REJECTED, with conditions and required corrections.
Evidence: `EV-A14-REV-01`.

### 5.7 Project Owner - A14-01, specification approval

After M-01 and C-1/C-3/C-5 are resolved. `EV-SPEC-01` is complete only with all
eight fields:

| Field | Required value |
|---|---|
| Specification path | per C-1 decision |
| Specification SHA-256 | individual hash at approval time |
| Test-specification path | per C-1 decision |
| Test-specification SHA-256 | individual hash at approval time |
| Commit/version | per C-5 decision |
| D11 scope | FULL or REDUCED, matching EV-D11-01 |
| Approver | Project Owner |
| Reviewer | Engineering Manager |
| Approval date | date of signature |

### 5.8 Engineers - E-01 / E-02 acknowledgements

```text
Primary engineer acknowledgement : ______________________  date ______
Backup engineer acknowledgement  : ______________________  date ______
```

Acknowledgement means: scope understood, isolation duties accepted, halt
authority accepted, no production access claimed. Evidence: `EV-ACK-01`,
`EV-ACK-02`.

### 5.9 Project Owner - P-03, Gate A decision

Not requestable yet. Requires every prerequisite in §7 satisfied. Final output:
GRANTED or NOT APPROVED, recorded against `EV-GATEA-01`. A-13 does not depend
on P-03.

---

## 6. M-01 review package

Read these two files only:

- `RELEASE_1_CONSOLIDATED_IMPLEMENTATION_SPECIFICATION_DRAFT.md` (664 lines,
  DDL in §22)
- `RELEASE_1_CONSOLIDATED_TEST_SPECIFICATION_DRAFT.md` (477 lines)

Optional context: §4 of this package for the scope conflicts.

### 6.1 Executive summary

The specification replaces message-based execution with database-authoritative
execution. A Celery message is demoted to a hint. A worker must win a
row-level conditional update that increments a per-job `lease_token`, and every
subsequent write carries that token. A stale worker's write affects zero rows,
so it stops instead of corrupting state. Dispatch intent is written in the same
transaction as the job, so a broker outage cannot lose work. Artifact
publication commits through one guarded pointer update. Heartbeats only extend a
lease when real progress occurred, so a hung worker is detected rather than
kept alive.

Scope: 4 migrations (6 if D11 FULL), 6 new worker modules, 9 touched modules,
61 tests (14 carried forward + 47 new). Nothing is implemented.

### 6.2 Eight-point review checklist

Answer each APPROVE / CONDITION / REJECT. Preliminary positions below are
mine, offered to accelerate the review, not to substitute for it.

| # | Question | Preliminary position |
|---|---|---|
| 1 | Is the job state machine technically correct? | Likely correct. Six persisted statuses, nine guarded transitions, terminal states absorbing, cancel dominant. **Review point:** `paused -> queued` increments the token, so resume is a new attempt; confirm that is acceptable for checkpoint append semantics. |
| 2 | Are lease ownership and monotonic fencing correct? | Likely correct. Claim is one conditional `UPDATE ... RETURNING`. Token increments on claim, on resume, and on reconciler redispatch. **Review point:** unguarded `db.update_job` must be removed for job rows or the whole fence is bypassable. |
| 3 | Are migration sequence and transaction boundaries safe? | Likely correct. TPM per revision; three `autocommit_block`s in `0032b`; new-table indexes non-concurrent by design; no `upgrade head`. **Review point:** TPM must be active before `0032b`, else the autocommit block commits preceding revisions. |
| 4 | Are concurrent-index and invalid-index recovery adequate? | Likely correct. `IF NOT EXISTS` deliberately avoided; validity asserted via `pg_index.indisvalid`; invalid index dropped concurrently before rebuild; failure raises. **Review point:** confirm the operator path (`DROP INDEX CONCURRENTLY`, re-run) is acceptable without a wrapper script. |
| 5 | Do tests cover duplicate delivery, crashes, and stale writes? | Likely yes. T-R1-001/002 duplicate; 010/011/012 crash points; 006/007 stale and absorbing writes. **Review point:** T-R1-012 needs a deterministic kill point between upload and pointer update; confirm an injectable failure hook is acceptable. |
| 6 | Is backward compatibility addressed? | Partially. Four-stage rollout A-D with a drain window. **Review point:** during stage C an old worker holds no lease, so the reconciler could preempt a healthy old worker. The drain window is named but not bounded by a mechanism. This is the weakest area and may warrant a condition. |
| 7 | Are rollback and recovery adequate? | Likely yes for the isolated environment; migrations reversible in exact reverse order; published pointers never deleted. **Review point:** rollback of `0032b` after code depends on the indexes must be ordered after the code revert. |
| 8 | Missing requirements or unacceptable risks? | Three risks to weigh: (a) progress-only lease renewal means a legitimately silent phase is treated as stalled - mitigation is mandatory progress emission at 15s; (b) the C-3 attestation conflict must be resolved before Gate A; (c) dispatcher publishes outside a transaction, so publish-then-crash is recoverable only via `locked_until` expiry. |

### 6.3 Review output record

```text
Reviewer            : ______________________
Date                : ______________________
Commit / spec hash  : ______________________
Verdict             : APPROVED / APPROVED WITH CONDITIONS / REJECTED
Conditions          : ______________________
Required corrections: ______________________
Signature           : ______________________
```

---

## 7. Gate A evidence checklist

A-13 requires all of the following. Nothing here is complete.

| Criterion | Evidence | Source action | State |
|---|---|---|---|
| A-01 D11 signed | EV-D11-01 | B-01 | NOT MET |
| A-02 Primary owner | EV-OWN-01 | P-01 | NOT MET |
| A-03 Backup owner | EV-OWN-02 | P-01 | NOT MET |
| A-04 Engineering manager | EV-OWN-03 | P-01 | NOT MET |
| A-05 Branch/worktree | EV-BR-01 | E-03 | NOT MET |
| A-06 Disposable PG16 | EV-ENV-01 | E-04 | NOT MET |
| A-07 No prod DB credentials | SEC-PRE-01 / SEC-POST-02 | S-00 / S-01 | NOT MET |
| A-08 No prod deploy permissions | SEC-PRE-02 / SEC-POST-02 | S-00 / S-01 | NOT MET |
| A-09 No prod S3/Redis/Celery creds | SEC-PRE-03 / SEC-POST-02 | S-00 / S-01 | NOT MET |
| A-10 Production network restricted | SEC-PRE-04 / SEC-POST-03 | S-00 / S-01 | NOT MET |
| A-11 No prod `.env`/secret/deploy key | SEC-PRE-05 / SEC-POST-02 | S-00 / S-01 | NOT MET |
| A-12 Disposable DB, sanitized data | SEC-PRE-06 / SEC-POST-01,04 | E-04 / S-01 | NOT MET |
| A-13 Package complete + independent review | EV-GATEA-PKG-01 | P-04 / M-01 | NOT MET |
| A-14 Specs approved | EV-A14-AUTH-01, EV-A14-REV-01, EV-SPEC-01 | P-05 / M-01 / A14-01 | NOT MET |
| SEC-P2-01 | EV-SEC-P2-01 | Security | NOT MET |
| ENG-P2-01 | EV-ENG-P2-01 | Engineering | NOT MET - see C-3 |
| Scope matches D11 | EV-SCOPE-01 | P-02 | NOT MET |
| Register consistency | EV-TRACK-01 | Custodian | NOT MET |

Additional evidence produced this session: repository baseline (§1), the two
specification drafts, and this package. None of them satisfies an A-criterion.

---

## 8. Implementation dependency graph

```text
B-01 D11
  |-- P-02 scope confirmation
  |-- P-04 custodian --> propagation into 3 records --> EV-TRACK-01
  '-- C-1/C-3/C-5 resolution --> A14-01

P-01 owners
  |-- P-05 authority
  |-- M-01 review --> resolve conditions
  |-- E-01 / E-02 acknowledgements
  '-- A14-01

S-00 (planned detail only)
  '-- E-03 branch/worktree --> E-04 PG16 --> S-01 --> SEC-P2-01 + ENG-P2-01

A-01..A-12 + A-14 + A-13 package --> P-03 Gate A

Gate A --> R1-P1..R1-P9 implementation --> M-01 code review --> A-13 refresh --> P-03
Gate B  --> separately, after Gate A, production only
```

Critical path to first line of code: **A14-01 and Gate A**, which depend on
B-01, P-01, M-01, and C-1. S-00/E-03/E-04 can run in parallel but only S-00
starts before code.

---

## 9. Technical tasks that can proceed independently

Honest scope: preparation only. No code, migration, branch, or environment.

| Task | State | Blocked by |
|---|---|---|
| Consolidated implementation spec with DDL | PREPARED | - |
| Consolidated test spec, 47 tests | PREPARED | - |
| This execution package and tracker | PREPARED | - |
| Dependency and version verification against pinned requirements | PREPARED | - |
| S-00 planned-environment specification | PREPARED (§5.5) | Security signature |
| Exact E-03 command sequence, drafted but not run | PREPARED | S-00 |
| C-1 adoption text for the two HOLD specs | PREPARED, not applied | Project Owner decision |
| C-3 attestation re-scoping text | PREPARED, not applied | Project Owner decision |
| Freeze hashes at approval time | AWAITING | A14-01 |

There is no remaining technical work that can be executed without Gate A. Said
plainly: the engineering queue is empty until signatures exist.

---

## 10. Master execution tracker

| ID | Task | Owner | Dependency | Status | Evidence | Next action |
|---|---|---|---|---|---|---|
| B-01 | Sign D11 FULL/REDUCED | Business Owner | - | AWAITING | EV-D11-01 | Fill §2 of D11 record |
| C-1 | Decide spec adoption option A-1/A-2 | Project Owner | - | AWAITING | - | Choose; then apply once |
| C-3 | Re-scope P2 attestations | Project Owner | - | AWAITING | - | Approve narrowed wording |
| C-5 | Decide evidence anchor B-1/B-2 | Project Owner | - | AWAITING | - | Choose commit or version |
| P-01 | Assign 3 roles | Project Owner | - | AWAITING | EV-OWN-01/02/03 | Fill ownership §1 |
| P-04 | Assign custodian | Project Owner | B-01 | AWAITING | EV-REC-01 | Name custodian |
| P-05 | Confirm A-14 authority | Project Owner | P-01 | AWAITING | EV-A14-AUTH-01 | Name authority |
| M-01 | Review both specs | Engineering Manager | P-01, C-1 | AWAITING | EV-A14-REV-01 | Use §6 checklist |
| A14-01 | Approve specs | Project Owner | M-01, B-01, C-1, C-5 | BLOCKED | EV-SPEC-01 | After review |
| E-01 | Primary acknowledgement | Primary | P-01 | AWAITING | EV-ACK-01 | Sign |
| E-02 | Backup acknowledgement | Backup | P-01 | AWAITING | EV-ACK-02 | Sign |
| S-00 | Verify planned isolation | Security | - | AWAITING | SEC-PRE-01..08 | Use §5.5 |
| E-03 | Create branch/worktree | Primary | S-00 | BLOCKED | EV-BR-01 | No action |
| E-04 | Provision PG16 | Primary | S-00 | BLOCKED | EV-ENV-01 | No action |
| S-01 | Verify actual isolation | Security | E-04 | BLOCKED | SEC-POST-01..06 | No action |
| SEC-P2-01 | P2 security attestation | Security | S-01, C-3 | BLOCKED | EV-SEC-P2-01 | After C-3 |
| ENG-P2-01 | P2 engineering attestation | Engineering | C-3 | BLOCKED | EV-ENG-P2-01 | After C-3 |
| A-13 | Evidence package | P-04/M-01 | A-01..A-12, A-14 | BLOCKED | EV-GATEA-PKG-01 | No action |
| P-03 | Gate A decision | Project Owner | A-13 | BLOCKED | EV-GATEA-01 | No action |
| R1-P1 | TPM + 4 migrations | Primary | P-03 | NOT AUTHORIZED | - | No action |
| R1-P2 | Mirrors + fenced write helper | Primary | R1-P1 | NOT AUTHORIZED | - | No action |
| R1-P3 | Outbox writer + dispatcher | Primary | R1-P2 | NOT AUTHORIZED | - | No action |
| R1-P4 | Claim + fence | Primary | R1-P3 | NOT AUTHORIZED | - | No action |
| R1-P5 | Heartbeat + progress | Primary | R1-P4 | NOT AUTHORIZED | - | No action |
| R1-P6 | Reconciler + redispatch | Primary | R1-P5 | NOT AUTHORIZED | - | No action |
| R1-P7 | Attempt artifacts + publication | Primary | R1-P6 | NOT AUTHORIZED | - | No action |
| R1-P8 | Strict checkpoint | Primary | R1-P7 | NOT AUTHORIZED | - | No action |
| R1-P9 | Partial completion + beat + drain | Primary | R1-P8 | NOT AUTHORIZED | - | No action |
| Gate B | Production package | Separate authority | Gate A | NOT AUTHORIZED | - | No action |

---

### 10.1 Approval closure tracker

Derived from §2 and the canonical register. This is a view, not a new approval
record; the register remains authoritative if the two ever disagree.
"Indep" = can this action be completed without any other action first.

| ID | Decision required | Owner | Evidence | Depends on | Blocks | Indep | Next action | Status |
|---|---|---|---|---|---|---|---|---|
| B-01 | FULL or REDUCED | Business Owner | EV-D11-01 | - | P-02, P-04, A14-01, all migrations | Yes | Sign D11 record §2 | Pending |
| P-01 | Name 3 roles | Project Owner | EV-OWN-01/02/03 | - | P-05, M-01, E-01, E-02 | Yes | Fill ownership record §1 | Pending |
| P-02 | Confirm Gate A scope matches D11 | Project Owner | EV-SCOPE-01 | B-01 | P-03 | No | After D11 | Blocked |
| P-04 | Name custodian | Project Owner | EV-REC-01 | B-01 | A-13, EV-TRACK-01 | No | After D11 | Blocked |
| P-05 | Name A-14 authority | Project Owner | EV-A14-AUTH-01 | P-01 | A14-01 | No | After P-01 | Blocked |
| M-01 | Review both specs | Eng Manager | EV-A14-REV-01 | P-01, §4 C-1 | A14-01 | No | Use §6 checklist | Blocked |
| A14-01 | Approve specs | Project Owner | EV-SPEC-01 | M-01, B-01, C-1, C-5 | Gate A, all code | No | After review | Blocked |
| E-01 | Primary acknowledgement | Primary Engineer | EV-ACK-01 | P-01 | A-13 | No | Sign | Blocked |
| E-02 | Backup acknowledgement | Backup Engineer | EV-ACK-02 | P-01 | A-13 | No | Sign | Blocked |
| S-00 | Verify planned isolation | Security | SEC-PRE-01..08 | - | E-03, E-04 | Yes | Use §5.5 | Pending |
| E-03 | Create branch/worktree | Primary Engineer | EV-BR-01 | S-00, A14-01 | E-04, R1-P1 | No | No action yet | Blocked |
| E-04 | Provision PG16 | Primary Engineer | EV-ENV-01 | S-00, E-03 | S-01, all tests | No | No action yet | Blocked |
| S-01 | Verify actual isolation | Security | SEC-POST-01..06 | E-04 | A-13 | No | No action yet | Blocked |
| SEC-P2-01 | P2 security attestation | Security | EV-SEC-P2-01 | S-01, C-3 | A-13 | No | After C-3 | Blocked |
| ENG-P2-01 | P2 engineering attestation | Engineering | EV-ENG-P2-01 | C-3, implementation | A-13 | No | After C-3 | Blocked |
| A-13 | Evidence package + review | Custodian/Manager | EV-GATEA-PKG-01 | A-01..A-12, A-14 | P-03 | No | No action yet | Blocked |
| P-03 | Gate A decision | Project Owner | EV-GATEA-01 | A-13 | All implementation, Gate B | No | No action yet | Blocked |

Independent actions available right now: **B-01, P-01, S-00** (three, all
human). No technical action is independent of A14-01 and P-03.

### 10.2 Governance commit plan (C-5) - prepared, NOT executed

State: **NOT EXECUTED.** No branch created, nothing staged, `main` unchanged at
`6719568f6fe7233e74aa151e3ba3531b2d6cb99d`.

| Item | Value |
|---|---|
| Target branch | `docs/release-1-governance-freeze` |
| Base | `6719568f6fe7233e74aa151e3ba3531b2d6cb99d` |
| Files to stage | 67, all under `docs/` |
| Excluded | `p0/`, `p1_rehearsal/`, all application code, migrations, config |
| Staging method | path-scoped `git add -- docs/`; **never** `git add .` |
| `main` | untouched; commit lands on the new branch only |

Exact sequence for review:

```powershell
git switch -c docs/release-1-governance-freeze 6719568f6fe7233e74aa151e3ba3531b2d6cb99d
git status --short
git add -- docs/
git status --short
git diff --cached --stat
git diff --cached --name-only | Select-String '^p0/|^p1_rehearsal/|^api/|^worker/|^web/'
git commit -m "docs: freeze Release 1 governance records for Gate A"
git rev-parse HEAD
```

Pre-commit checks, all mandatory:

| Check | Required result |
|---|---|
| `git status --short` after add | exactly 67 lines, all `A  docs/...` |
| Excluded-path grep | no output |
| `git diff --cached --stat` | docs only, no binary, no secret |
| Staged count | 67 |
| `git rev-parse HEAD` before commit | still `6719568f...` on `main` |

Proposed commit message:

```text
docs: freeze Release 1 governance records for Gate A

Adds the Release 1 governance, specification, and evidence documents that were
previously untracked, so that A14-01 hashes can be anchored to a commit.

No application code, migration, configuration, or deployment change.
```

After execution, record the new commit SHA as the A14-01 "commit/version"
anchor, alongside the two frozen specification hashes in §1.

Rollback if the commit is wrong: `git switch main` and delete the local branch.
`main` never moved, so no history rewrite is needed.

## 11. Exact next actions by stakeholder

Ordered so that each sender unblocks the most downstream work.

**Business Owner** - one action: sign §2 of
`RELEASE_1_D11_BUSINESS_APPROVAL_RECORD.md`. Unblocks P-02, P-04, A14-01,
and both migration graph shapes.

**Project Owner** - two remaining actions:
1. Supply the five names for P-01/P-04/P-05. The response contained
   `[INSERT NAME]` placeholders; names must not be invented.
2. Approve execution of the §10.2 governance commit plan.

**Engineering Manager** - one action: complete §6 and return a verdict.
Reviewing the drafts is the highest-leverage step for everyone else.

**Security** - one action: verify §5.5 and sign the nine SEC-PRE controls.

**Primary and Backup engineers** - no action until Gate A. Then sign E-01/E-02
and begin R1-P1.

---

## 12. What is still prohibited

Production database, credentials, queues, workers, S3, deployment, and data
remain inaccessible and unauthorized. Gate B is not granted and cannot be
submitted until Gate A is granted and the isolated implementation is tested and
reviewed. No P2-excluded security or configuration behavior is authorized by
this package.

---

## 13. Stop condition

This package is preparation. It records no approval and authorizes no code.
The next artifact that can be produced without a human signature does not
exist; the remaining work begins when B-01, P-01, and M-01 are recorded.
