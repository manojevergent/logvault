# Release 1 - Final Approval Closure Package

2026-11-14. This replaces every prior approval-collection artifact. It does not
create new approvals and does not modify any canonical record.

**Purpose:** reduce Release 1 to five signatures. Nothing else stands between
the current state and implementation.

| Class | Count |
|---|---|
| Prepared | 4 specifications/packages |
| Approved | **0** |
| Implemented | **0 lines** |
| Tested | **0 tests** |
| Open human decisions | **5** |

---

## 1. Baseline verification

Re-verified this session against the repository, not carried forward.

| Item | Value |
|---|---|
| HEAD | `6719568f6fe7233e74aa151e3ba3531b2d6cb99d` |
| Branch | `main` (unmodified) |
| Tracked changes | 0 |
| Untracked | 71 (all `docs/`, `p0/`, `p1_rehearsal/`) |
| Alembic head | `0031_extraction_groups.py` |
| P1 migrations present | 0 |
| Governance branch | not created (§10.2 plan, unexecuted) |

Frozen specification versions (FREEZE-1, 2026-11-14):

| File | SHA-256 |
|---|---|
| `docs/RELEASE_1_CONSOLIDATED_IMPLEMENTATION_SPECIFICATION_DRAFT.md` | `7BFD48D70B3E66F6CBEB4696B0DC266C90D1618D58ED816CBEE0C0EF1A915BF3` |
| `docs/RELEASE_1_CONSOLIDATED_TEST_SPECIFICATION_DRAFT.md` | `FC3C7CD6B0CE7513C08B81AD0266484FA81E9E1FE33604558EF2466926F8F308` |

Recorded decisions already applied (they are decisions, not approvals):

| ID | Decision | Applied where |
|---|---|---|
| C-1 | Adopt consolidated specs; retain drafts; keep paths/versions/hashes | Freeze headers on both files |
| C-3 | Two separate attestations (security / engineering) | Canonical register §12 |
| C-5 | Governance branch, exact-path staging, plan before execution | Execution package §10.2 |

Action count correction: the canonical register §2 defines **16** action rows.
A-13 (`EV-GATEA-PKG-01`) is a P-04 duty and evidence item, not a separate action
row. "17" = 16 actions + A-13 package. Both figures describe the same thing.

---

## 2. Master closure tracker

Nine required fields. "Indep" = can be completed with no other action first.

### 2.1 Decision and assignment actions

| ID | Decision required | Owner | Evidence | Depends on | Blocks | Indep | Next action | Status |
|---|---|---|---|---|---|---|---|---|
| B-01 | FULL or REDUCED | Business Owner | EV-D11-01 | — | P-02, P-04, A14-01, migration graph | **Yes** | Sign §3.1 | PENDING |
| P-01 | Name 3 engineering roles | Project Owner | EV-OWN-01/02/03 | — | P-05, M-01, E-01, E-02 | **Yes** | Sign §3.2 | PENDING |
| P-02 | Confirm Gate A scope matches D11 | Project Owner | EV-SCOPE-01 | B-01 | P-03 | No | After D11 | BLOCKED |
| P-04 | Name records custodian | Project Owner | EV-REC-01 | B-01 | A-13, EV-TRACK-01 | No | Sign §3.2 | BLOCKED |
| P-05 | Name A-14 authority | Project Owner | EV-A14-AUTH-01 | P-01 | A14-01 | No | Sign §3.2 | BLOCKED |
| M-01 | Review both specs | Engineering Manager | EV-A14-REV-01 | P-01 | A14-01 | No | Sign §3.3 | BLOCKED |
| A14-01 | Approve both specs | Project Owner | EV-SPEC-01 | M-01, B-01, P-05 | All code | No | Sign §3.4 | BLOCKED |
| E-01 | Primary acknowledgement | Primary Engineer | EV-ACK-01 | P-01 | A-13 | No | Sign §3.5 | BLOCKED |
| E-02 | Backup acknowledgement | Backup Engineer | EV-ACK-02 | P-01 | A-13 | No | Sign §3.5 | BLOCKED |
| P-03 | Gate A decision | Project Owner | EV-GATEA-01 | A-13 | Implementation, Gate B | No | Sign §3.6 | BLOCKED |

### 2.2 Security and environment actions

| ID | Decision required | Owner | Evidence | Depends on | Blocks | Indep | Next action | Status |
|---|---|---|---|---|---|---|---|---|
| S-00 | Verify planned isolation | Security | SEC-PRE-01..08 | — | E-03, E-04, A-07..A-11 | **Yes** | Sign §3.7 | PENDING |
| E-03 | Create branch/worktree | Primary Engineer | EV-BR-01 | S-00, A14-01 | E-04, R1-P1 | No | Execute after §3.7 | BLOCKED |
| E-04 | Provision disposable PG16 | Primary Engineer | EV-ENV-01 | S-00, E-03 | S-01, all tests | No | Execute after E-03 | BLOCKED |
| S-01 | Verify actual isolation | Security | SEC-POST-01..06 | E-04 | A-13 | No | After E-04 | BLOCKED |
| SEC-P2-01 | Security capability attestation | Security | EV-SEC-P2-01 | S-01 | A-13 | No | After S-01 | BLOCKED |
| ENG-P2-01 | Engineering scope attestation | Engineering | EV-ENG-P2-01 | implementation | A-13 | No | After implementation | BLOCKED |

**Independent right now: three. B-01, P-01, S-00. All human. No technical task
is independent of A14-01 and P-03.**

---

## 3. Signature forms

Each form is complete as written. Fill the blanks; do not restate scope.

### 3.1 B-01 - D11 decision (Business Owner)

Scope difference, stated without advocacy:

| | FULL | REDUCED |
|---|---|---|
| Revisions | `0032, 0032b, 0033, 0034, 0035, 0036` | `0032, 0032b, 0033, 0034` |
| Schedule window ledger | in schema; duplicate windows blocked by a unique constraint | absent; deduplication relies on `last_run_at` comparison |
| S3 attempt lineage | per-attempt columns recorded | absent |
| Message-dispatch reliability | identical | identical |
| Migration count / window | 6 revisions, longer hold | 4 revisions, shorter hold |
| Reversible | yes, reverse order | yes, reverse order |

```text
D11 DECISION
Business owner name : _____________________________
Role / title        : _____________________________
Selected option     : FULL  /  REDUCED        (delete one)
Rationale           : _____________________________
Date                : _____________________________
Signature           : _____________________________

Recorded in: docs/RELEASE_1_D11_BUSINESS_APPROVAL_RECORD.md §2
Evidence ID: EV-D11-01
```

On receipt I apply: P-02 scope confirmation, P-04 propagation into the decision
register, authorization checklist, and execution tracker, and I lock the
migration graph to the selected shape.

This decision gates P-02, P-04, A14-01 and the `0035`/`0036` revisions. It does
**not** gate P-01 assignments, S-00, or M-01 preparation; those run in parallel.

### 3.2 P-01 / P-04 / P-05 - names (Project Owner)

```text
ENGINEERING OWNERSHIP
Primary engineer      : _____________________________
Backup engineer       : _____________________________
Engineering manager   : _____________________________
Records custodian     : _____________________________
A-14 approval authority: ____________________________
Date assigned         : _____________________________

Recorded in: docs/RELEASE_1_GATE_A_OWNERSHIP_RECORD.md §1
Evidence IDs: EV-OWN-01, EV-OWN-02, EV-OWN-03, EV-REC-01, EV-A14-AUTH-01
```

Duties, so acceptance is informed:

| Role | Accepts |
|---|---|
| Primary | Implements, maintains evidence, halts on any scope violation |
| Backup | Covers primary absence; independently verifies migration graph, TPM behavior, evidence |
| Manager | Confirms ownership, performs M-01 and post-implementation review |
| Custodian | Holds signed D11, propagates scope to 3 records, keeps evidence references consistent |
| A-14 authority | May approve A14-01 on the Project Owner's behalf |

Names cannot be supplied by me. Placeholders were left blank deliberately.

### 3.3 M-01 - technical review (Engineering Manager)

Read two frozen files:

- `RELEASE_1_CONSOLIDATED_IMPLEMENTATION_SPECIFICATION_DRAFT.md` (664 lines; DDL in §22)
- `RELEASE_1_CONSOLIDATED_TEST_SPECIFICATION_DRAFT.md` (477 lines)

Eight questions, with a preliminary position on each so the review is a critique
rather than a cold read. Preliminary positions are **not** review findings and
carry no authority.

| # | Question | Preliminary position |
|---|---|---|
| 1 | State machine correct? | Six statuses, nine guarded transitions, terminal absorbing, cancel dominant. Review: resume increments the token, so it opens a new attempt. |
| 2 | Lease ownership and monotonic fencing correct? | Single conditional `UPDATE ... RETURNING`. Review: unguarded job updates must be removed or the fence is bypassable. |
| 3 | Migration sequence and transaction boundaries safe? | TPM per revision, 3 autocommit blocks, no `upgrade head`. Review: TPM must precede `0032b`. |
| 4 | Concurrent-index and invalid-index recovery adequate? | `IF NOT EXISTS` avoided, `indisvalid` asserted, invalid index dropped before rebuild. |
| 5 | Tests cover duplicate delivery, crashes, stale writes? | T-R1-001/002, 010/011/012, 006/007. Review: T-R1-012 needs an injectable kill point. |
| 6 | Backward compatibility addressed? | Four-stage rollout with a drain window. **Weakest area:** an old worker holds no lease, so the drain window lacks a mechanical bound. |
| 7 | Rollback and recovery adequate? | Reversible migrations, published pointers never deleted. Review: revert code before dropping indexes. |
| 8 | Missing requirements or unacceptable risks? | Progress-only renewal treats a silent phase as stalled; the C-3 conflict is now resolved by register §12; publish-then-crash recovers via `locked_until` expiry. |

```text
M-01 REVIEW
Reviewer            : _____________________________
Date                : _____________________________
Specification version reviewed : FREEZE-1, 2026-11-14
Implementation spec SHA-256    : 7BFD48D7...A915BF3
Test spec SHA-256              : FC3C7CD6...6F8F308
Verdict             : APPROVED / APPROVED WITH CONDITIONS / REJECTED   (delete two)
Conditions          : _____________________________
Required corrections: _____________________________
Signature           : _____________________________

Recorded in: docs/RELEASE_1_GATE_A_CANONICAL_REGISTER.md (M-01)
Evidence ID: EV-A14-REV-01
```

On receipt I resolve conditions, issue FREEZE-2 with new hashes, and return the
corrected package for confirmation.

### 3.4 A14-01 - specification approval (Project Owner)

Requires **all** of: signed D11 (B-01), confirmed A-14 authority (P-05), a
completed M-01 review with no outstanding conditions, the frozen paths and
hashes above, and the Project Owner's signature. An M-01 verdict alone does not
authorize A14-01.

The path substitution is recorded in register §4.2, so no further governance
action is required.

After approval:

```text
A14-01 APPROVAL
Specification path     : docs/RELEASE_1_CONSOLIDATED_IMPLEMENTATION_SPECIFICATION_DRAFT.md
Specification SHA-256  : 7BFD48D70B3E66F6CBEB4696B0DC266C90D1618D58ED816CBEE0C0EF1A915BF3
Test-spec path         : docs/RELEASE_1_CONSOLIDATED_TEST_SPECIFICATION_DRAFT.md
Test-spec SHA-256      : FC3C7CD6B0CE7513C08B81AD0266484FA81E9E1FE33604558EF2466926F8F308
Commit / version       : FREEZE-1, 2026-11-14  <or> governance commit SHA
D11 scope              : FULL / REDUCED   (must match EV-D11-01)
Approver               : _____________________________
Reviewer               : _____________________________
Date                   : _____________________________
Signature              : _____________________________

Recorded in: docs/RELEASE_1_GATE_A_CANONICAL_REGISTER.md §4.1
Evidence ID: EV-SPEC-01
```

### 3.5 E-01 / E-02 - engineer acknowledgements

```text
ENGINEERING ACKNOWLEDGEMENT
Primary engineer : ______________________  date ______
Backup engineer  : ______________________  date ______

Acknowledged: scope understood; isolation duties accepted; authority to halt on
scope violation accepted; no production access held or requested.

Evidence IDs: EV-ACK-01, EV-ACK-02
```

### 3.6 P-03 - Gate A decision (Project Owner)

Not signable yet. Requires A-13 complete. When complete:

```text
GATE A DECISION
All A-01..A-14 verified : YES / NO
Evidence package        : EV-GATEA-PKG-01, reviewed by ____________
Decision                : GRANTED / NOT APPROVED
Scope granted           : 0032, 0032b, 0033, 0034 [, 0035, 0036 if FULL]
Production              : NOT AUTHORIZED (Gate B separate)
Date / signature        : _____________________________

Evidence ID: EV-GATEA-01
```

### 3.7 S-00 - planned isolation (Security)

Verify the plan, before anything is provisioned.

| Planned item | Value |
|---|---|
| Repository | `E:\last9_web_app` |
| Branch | `release-1/p1-dispatch` (not created) |
| Worktree | `..\last9_web_app-p1` (not created) |
| Base commit | `6719568f6fe7233e74aa151e3ba3531b2d6cb99d` |
| PostgreSQL | `postgres:16-alpine`, disposable, non-default port |
| Database | `last9_p1_test` |
| Redis/Celery | disposable container, separate port and DB index, no shared keyspace |
| S3 | local stub or MinIO, no real bucket or credential |
| Data | synthetic or sanitized only |
| Production DB/credentials/network | unavailable and unrequested |
| Cleanup | container and volume destroyed after evidence capture |

```text
S-00 PRE-PROVISIONING VERIFICATION
SEC-PRE-01 no production DB credentials        : PASS / FAIL  ________
SEC-PRE-02 no production deploy permissions    : PASS / FAIL  ________
SEC-PRE-03 no production S3/Redis/Celery creds : PASS / FAIL  ________
SEC-PRE-04 no production network access        : PASS / FAIL  ________
SEC-PRE-05 no production .env/secret/deploy key: PASS / FAIL  ________
SEC-PRE-06 PG16 disposable, sanitized data only: PASS / FAIL  ________
SEC-PRE-07 branch/worktree not production      : PASS / FAIL  ________
SEC-PRE-08 no prohibited config/flags enabled  : PASS / FAIL  ________

Verifier : ______________________  Date ______  Signature ______________

Recorded in: docs/RELEASE_1_PRODUCTION_ISOLATION_CONFIRMATION.md
Evidence IDs: SEC-PRE-01..08
```

---

## 4. What each reply unblocks

Single-line replies are sufficient. I execute the consequence, not another plan.

| Reply | I do immediately |
|---|---|
| `D11 = FULL` or `D11 = REDUCED` | Record scope, propagate to 3 records, fix migration graph, prepare P-02 |
| Names for the 5 roles | Fill ownership record, prepare P-05 and E-01/E-02 forms |
| `Path amendment approved` | Apply the 2-line register change |
| `M-01 = APPROVED` / `+ conditions` | Finalize specs, FREEZE-2 if changed, prepare A14-01 signature line |
| `A14-01 approved` | Record EV-SPEC-01 with hashes, prepare A-13 skeleton |
| `S-00 = PASS` | Prepare E-03 command sheet for approval |
| `Commit plan approved` | Execute §10.2 staging and commit, record SHA |
| `Gate A = GRANTED` | Create worktree, provision PG16, begin R1-P1 |

---

## 5. Gate A evidence checklist

| Criterion | Evidence | Action | State |
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
| A-11 No prod .env/secret/deploy key | SEC-PRE-05 / SEC-POST-02 | S-00 / S-01 | NOT MET |
| A-12 Disposable DB, sanitized data | SEC-PRE-06 / SEC-POST-01, 04 | E-04 / S-01 | NOT MET |
| A-13 Package complete, independently reviewed | EV-GATEA-PKG-01 | P-04 / M-01 | NOT MET |
| A-14 Specs approved | EV-A14-AUTH-01 / EV-A14-REV-01 / EV-SPEC-01 | P-05 / M-01 / A14-01 | NOT MET |
| Scope matches D11 | EV-SCOPE-01 | P-02 | NOT MET |
| Register consistency | EV-TRACK-01 | Custodian | NOT MET |
| SEC-P2-01 | EV-SEC-P2-01 | Security | NOT MET |
| ENG-P2-01 | EV-ENG-P2-01 | Engineering | NOT MET |

A-13 does not depend on P-03. P-03 is the decision, not an input to it.

---

## 6. Implementation queue (gated)

Ten phases, fully specified, zero started. Each begins only after P-03.

| Phase | Content | Gate |
|---|---|---|
| R1-P1 | TPM + `0032`, `0032b`, `0033`, `0034` (+`0035`,`0036` if FULL) | P-03 |
| R1-P2 | Model mirrors, fenced-write helper | R1-P1 |
| R1-P3 | Outbox writer + dispatcher | R1-P2 |
| R1-P4 | Claim, ownership, fence | R1-P3 |
| R1-P5 | Heartbeat + progress | R1-P4 |
| R1-P6 | Reconciler + redispatch | R1-P5 |
| R1-P7 | Attempt artifacts + atomic publication | R1-P6 |
| R1-P8 | Strict checkpoint | R1-P7 |
| R1-P9 | Partial completion, dedicated beat, legacy drain | R1-P8 |
| R1-P10 | 61 tests, evidence capture (14 carried forward + 47 new) | R1-P9 |

---

## 7. Prohibitions in force

Production database, credentials, queues, workers, S3, deployment, and data
remain inaccessible. Gate B remains NOT GRANTED and is not submittable before
Gate A is granted and the isolated implementation is tested and independently
reviewed. No P2-excluded security or configuration behavior is authorized.

---

## 8. Status

**Prepared:** this package, two frozen specifications, the consolidated execution
package, and the C-3 register amendment.

**Implemented:** nothing. **Tested:** nothing. **Approved:** nothing.

Five signatures close the approval phase. Their absence is the only remaining
blocker, and no further analysis can substitute for them.
