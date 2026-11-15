# Release 1 Gate A Canonical Register

Status: **HOLD.** Gate A and Gate B are **NOT GRANTED**. D11 is **UNSIGNED**.
P1 is **NOT STARTED**. P2 is **NOT AUTHORIZED**. No evidence or approval in
this register is complete.

## 1. Authority

This register is the only active source for action IDs, evidence IDs, the
Gate A prerequisite list, the ISO/EV-ISO crosswalk, and Gate A/B boundaries.
Documents marked superseded retain history but must not define new IDs.

## 2. Canonical action register

| ID | Responsibility | Owner | Evidence | State |
|---|---|---|---|---|
| B-01 | D11 business approval | Business owner | EV-D11-01 | HOLD — UNSIGNED |
| P-01 | Primary/backup engineering owner and manager assignments | Project owner | EV-OWN-01/02/03 | HOLD — NOT ASSIGNED |
| P-02 | Gate A scope confirmation | Project owner | EV-D11-01 + EV-SCOPE-01 | HOLD — BLOCKED by B-01 |
| P-03 | Final Gate A decision | Project owner | EV-GATEA-01 (output only) | HOLD — NOT GRANTED |
| P-04 | D11 records custodian and evidence-package verification | Project owner/delegate | EV-REC-01, EV-GATEA-PKG-01 | HOLD — NOT ASSIGNED |
| P-05 | A-14 approval authority | Project owner | EV-A14-AUTH-01 | HOLD — UNCONFIRMED |
| M-01 | Engineering Manager review | Engineering Manager | EV-A14-REV-01 | HOLD — NOT STARTED |
| A14-01 | Implementation and test-specification approval | Project owner with Manager review | EV-SPEC-01 | HOLD — NOT APPROVED |
| E-01 | Primary engineering acknowledgement | Primary engineering owner | EV-ACK-01 | HOLD — NOT STARTED |
| E-02 | Backup engineering acknowledgement | Backup engineering owner | EV-ACK-02 | HOLD — NOT STARTED |
| S-00 | Pre-provisioning isolation verification | Security/infrastructure owner | SEC-PRE-01..08 | HOLD — NOT STARTED |
| E-03 | Actual branch/worktree creation | Primary engineering owner | EV-BR-01 | HOLD — BLOCKED by S-00 |
| E-04 | Actual PostgreSQL 16 environment provisioning | Primary engineering owner | EV-ENV-01 | HOLD — BLOCKED by S-00/E-03 |
| S-01 | Post-provisioning security verification | Security/infrastructure owner | SEC-POST-01..06 | HOLD — BLOCKED by E-04 |
| SEC-P2-01 | Security P2 environmental/configuration attestation | Security/infrastructure owner | EV-SEC-P2-01 | HOLD — NOT VERIFIED |
| ENG-P2-01 | Engineering P2 application-behavior attestation | Engineering | EV-ENG-P2-01 | HOLD — NOT VERIFIED |

P-03 is the decision outcome. It is not a prerequisite to itself. A-13 is an
independent evidence-package review, not P-03.

## 3. Canonical evidence register

| Evidence ID | Content | Owner | State |
|---|---|---|---|
| EV-D11-01 | Signed D11 FULL/REDUCED record | Business owner | UNSIGNED |
| EV-SCOPE-01 | P-02 Gate A scope confirmation matching D11 | Project owner | HOLD |
| EV-OWN-01 | Primary engineering owner | Project owner | NOT ASSIGNED |
| EV-OWN-02 | Backup engineering owner | Project owner | NOT ASSIGNED |
| EV-OWN-03 | Engineering manager | Project owner | NOT ASSIGNED |
| EV-REC-01 | Records custodian assignment and propagation | Project owner/delegate | NOT ASSIGNED |
| EV-GATEA-PKG-01 | Gate A evidence package index and independent consistency review | Project owner/M-01 | NOT STARTED |
| EV-A14-AUTH-01 | A-14 approval-authority confirmation | Project owner | UNCONFIRMED |
| EV-A14-REV-01 | Engineering Manager technical review | Engineering Manager | NOT STARTED |
| EV-SPEC-01 | Both specification approvals with paths, commit/version, individual SHA-256 | Project owner | NOT APPROVED |
| EV-ACK-01 | Primary engineering acknowledgement | Primary owner | NOT STARTED |
| EV-ACK-02 | Backup engineering acknowledgement | Backup owner | NOT STARTED |
| EV-BR-01 | Actual branch/worktree/base commit | Primary owner | NOT CREATED |
| EV-ENV-01 | Actual disposable PostgreSQL 16 environment | Primary owner | NOT RECORDED |
| SEC-PRE-01 | Planned environment has no production DB credentials | Security/infrastructure | NOT STARTED |
| SEC-PRE-02 | No production deployment permissions are available | Security/infrastructure | NOT STARTED |
| SEC-PRE-03 | No production S3/Redis/Celery credentials are available | Security/infrastructure | NOT STARTED |
| SEC-PRE-04 | No production network access from planned environment | Security/infrastructure | NOT STARTED |
| SEC-PRE-05 | No production `.env`, secret, or deploy key | Security/infrastructure | NOT STARTED |
| SEC-PRE-06 | Planned PG16 is disposable; synthetic/sanitized data only | Security/infrastructure | NOT STARTED |
| SEC-PRE-07 | Planned branch/worktree is not production | Security/infrastructure | NOT STARTED |
| SEC-PRE-08 | No P2 production configuration/flags enabled | Security/infrastructure | NOT STARTED |
| SEC-POST-01 | Actual PG16 is disposable and version recorded | Security/infrastructure | BLOCKED by E-04 |
| SEC-POST-02 | Actual scan shows no production credentials/secrets/deploy keys | Security/infrastructure | BLOCKED by E-04 |
| SEC-POST-03 | Actual network isolation tested; production unreachable | Security/infrastructure | BLOCKED by E-04 |
| SEC-POST-04 | Actual database uses synthetic/sanitized data | Security/infrastructure | BLOCKED by E-04 |
| SEC-POST-05 | Actual branch/worktree matches E-03, not production | Security/infrastructure | BLOCKED by E-04 |
| SEC-POST-06 | Actual environment has no P2 config/flags enabled | Security/infrastructure | BLOCKED by E-04 |
| EV-SEC-P2-01 | Security attests no P2 environmental/config enablement; P2 excluded | Security/infrastructure | NOT VERIFIED |
| EV-ENG-P2-01 | Engineering attests no P2 code paths, reads, tasks, runtime behavior; P2 excluded | Engineering | NOT VERIFIED |
| EV-GATEA-01 | Gate A decision record (output) | Project owner | NOT GRANTED |
| EV-TRACK-01 | Canonical register consistency check | Engineering/records custodian | NOT STARTED |
| EV-ISO-01..09 | Historical aliases; crosswalk in §5 | — | RETAINED |

Action/evidence separation: SEC-P2-01 is an action, EV-SEC-P2-01 is its evidence.
ENG-P2-01 is an action, EV-ENG-P2-01 is its evidence. Neither attestation
authorizes P2 implementation, testing, or deployment. SEC-P2-01 covers
environmental/configuration boundaries; ENG-P2-01 covers application scope and
behavior.

## 4. A-01..A-14 mapping

| A ID | Criterion | Action | Evidence | Owner | Blocking condition |
|---|---|---|---|---|---|
| A-01 | D11 signed FULL/REDUCED | B-01 | EV-D11-01 | Business owner | Signature and selected scope |
| A-02 | Primary engineering owner assigned | P-01 | EV-OWN-01 | Project owner | Named and accepted |
| A-03 | Backup engineering owner assigned | P-01 | EV-OWN-02 | Project owner | Named and accepted |
| A-04 | Engineering manager named | P-01 | EV-OWN-03 | Project owner | Named |
| A-05 | Dedicated branch/worktree | E-03 | EV-BR-01 | Primary owner | Actual branch after S-00 |
| A-06 | Isolated PostgreSQL 16 environment | E-04 | EV-ENV-01 | Primary owner | Actual disposable PG16 after S-00/E-03 |
| A-07 | No production DB credentials | S-00/S-01 | SEC-PRE-01/SEC-POST-02 | Security/infrastructure | Planned and actual verification |
| A-08 | No production deployment permissions | S-00/S-01 | SEC-PRE-02/SEC-POST-02 | Security/infrastructure | Planned and actual verification |
| A-09 | No production S3/Redis/Celery credentials | S-00/S-01 | SEC-PRE-03/SEC-POST-02 | Security/infrastructure | Planned and actual verification |
| A-10 | Production network access restricted | S-00/S-01 | SEC-PRE-04/SEC-POST-03 | Security/infrastructure | Planned and actual verification |
| A-11 | No production `.env`/secret/deploy key | S-00/S-01 | SEC-PRE-05/SEC-POST-02 | Security/infrastructure | Planned and actual verification |
| A-12 | Disposable test DB and sanitized data | E-04/S-01 | SEC-PRE-06/SEC-POST-01/SEC-POST-04 | Engineering/security | Actual environment verification |
| A-13 | Gate A evidence package complete and independently reviewed | P-04/M-01 | EV-GATEA-PKG-01 | Project owner/records custodian | A-01..A-12 and A-14 evidence complete; P-03 not an input |
| A-14 | Implementation and test specification approved | P-05/M-01/A14-01 | EV-A14-AUTH-01/EV-A14-REV-01/EV-SPEC-01 | Project owner with Manager | D11 signed; scope matches D11; paths/commit/SHA-256 |

A-14 is mandatory and inside A-01..A-14. A-14 cannot be complete while D11 is
UNSIGNED and must record the FULL or REDUCED scope selected in the signed D11
record.

### 4.1 A-14 approval evidence (EV-SPEC-01)

EV-SPEC-01 is complete only when all fields exist:

| Field | Required value |
|---|---|
| Specification path | `docs/RELEASE_1_CONSOLIDATED_IMPLEMENTATION_SPECIFICATION_DRAFT.md` |
| Specification SHA-256 | Individual SHA-256 of that file at approval time |
| Test-specification path | `docs/RELEASE_1_CONSOLIDATED_TEST_SPECIFICATION_DRAFT.md` |
| Test-specification SHA-256 | Individual SHA-256 of that file at approval time |
| Commit/version | Git commit SHA or approved document version covering both files |
| D11 scope | FULL or REDUCED, matching the signed D11 record |
| Approver | Project Owner |
| Reviewer | Engineering Manager |
| Approval date | Date of signature |

A14-01 is not complete while D11 is UNSIGNED. P-05 confirms authority; M-01
records the review; A14-01 records the approval.

### 4.2 Path supersession (C-1)

Recorded 2026-11-14 under Project Owner decision C-1, which adopted the
consolidated specifications as authoritative and directed that the earlier
specifications be retained as superseded historical records. This affects the
two path fields in §4.1 only.

| Role | Path | State |
|---|---|---|
| Authoritative implementation specification | `docs/RELEASE_1_CONSOLIDATED_IMPLEMENTATION_SPECIFICATION_DRAFT.md` | FREEZE-1, 2026-11-14 |
| Authoritative test specification | `docs/RELEASE_1_CONSOLIDATED_TEST_SPECIFICATION_DRAFT.md` | FREEZE-1, 2026-11-14 |
| Superseded implementation specification | `docs/RELEASE_1_P1_IMPLEMENTATION_SPECIFICATION.md` | Retained unchanged; no longer an A-14 path |
| Superseded test specification | `docs/RELEASE_1_P1_IMPLEMENTATION_TEST_SPEC.md` | Retained unchanged; no longer an A-14 path |

Frozen hashes at the time this amendment was recorded:

| File | SHA-256 |
|---|---|
| Consolidated implementation specification | `7BFD48D70B3E66F6CBEB4696B0DC266C90D1618D58ED816CBEE0C0EF1A915BF3` |
| Consolidated test specification | `FC3C7CD6B0CE7513C08B81AD0266484FA81E9E1FE33604558EF2466926F8F308` |

Rules:

- Paths changed; approval did not. A14-01 remains **NOT APPROVED**, and this
  amendment satisfies no A-criterion.
- The superseded files must not be edited, deleted, renamed, or reused. They are
  audit history and remain readable at the paths listed above.
- No evidence ID, criterion, dependency, or migration boundary changes because
  of this substitution.
- The `_DRAFT` filename component is retained deliberately. Renaming would alter
  the paths recorded here and force FREEZE-2. It is a filename artifact; the
  document state is FROZEN.

## 5. ISO and EV-ISO crosswalk

| Existing ID/action | Existing content | SEC-PRE control | SEC-POST control | Note |
|---|---|---|---|---|
| ISO-01 | No production DB credentials | SEC-PRE-01 | SEC-POST-02 | Direct |
| ISO-02 | No production deployment permissions | SEC-PRE-02 | SEC-POST-02 | Direct |
| ISO-03 | No production S3/Redis/Celery credentials | SEC-PRE-03 | SEC-POST-02 | Direct |
| ISO-04 | Worktree not production branch | SEC-PRE-07 | SEC-POST-05 | Direct |
| ISO-05 | No production `.env`/secret/deploy key | SEC-PRE-05 | SEC-POST-02 | Direct |
| ISO-06 | Disposable test DB | SEC-PRE-06 | SEC-POST-01 | Planned versus actual |
| ISO-07 | Synthetic/sanitized data | SEC-PRE-06 | SEC-POST-04 | Planned versus actual |
| ISO-08 | No P2 runtime behavior | SEC-PRE-08 | SEC-POST-06 + EV-SEC-P2-01 + EV-ENG-P2-01 | Split security and engineering |
| ISO-09 | No production config change capability | SEC-PRE-02 | SEC-POST-02/SEC-POST-03 | Access and network |
| ISO-10 | Production network restricted | SEC-PRE-04 | SEC-POST-03 | No EV-ISO-10 exists |
| EV-ISO-01 | No production DB credentials | SEC-PRE-01 | SEC-POST-02 | Retained alias |
| EV-ISO-02 | No production deployment permissions | SEC-PRE-02 | SEC-POST-02 | Retained alias |
| EV-ISO-03 | No production S3/Redis/Celery credentials | SEC-PRE-03 | SEC-POST-02 | Retained alias |
| EV-ISO-04 | No production network access | SEC-PRE-04 | SEC-POST-03 | Retained alias |
| EV-ISO-05 | No production secrets or keys | SEC-PRE-05 | SEC-POST-02 | Retained alias |
| EV-ISO-06 | Disposable test DB | SEC-PRE-06 | SEC-POST-01 | Retained alias |
| EV-ISO-07 | Synthetic/sanitized data | SEC-PRE-06 | SEC-POST-04 | Retained alias |
| EV-ISO-08 | No P2 behavior | SEC-PRE-08 | SEC-POST-06 + P2 evidence | Retained alias; split ownership |
| EV-ISO-09 | No production config change | SEC-PRE-02 | SEC-POST-02/SEC-POST-03 | Retained alias |

No existing item is unmappable. ISO-10 has no EV-ISO-10; that is expected.

## 6. Dependency graph

    B-01 D11 signature
      -> P-02 Gate A scope
      -> P-04 records propagation

    P-01 owners/manager
      -> P-05 A-14 authority
      -> M-01 Engineering Manager review
      -> E-01 primary acknowledgement
      -> E-02 backup acknowledgement

    S-00 pre-provisioning (planned details only)
      -> E-03 actual branch/worktree
          -> E-04 disposable PostgreSQL 16
              -> S-01 post-provisioning verification
                  -> SEC-P2-01
                  -> ENG-P2-01

    B-01 + P-05 + M-01 + EV-SPEC-01 -> A14-01

    A-01..A-12 + A-14 + P-04/M-01 -> A-13 evidence package

    A-01..A-14 + P-02 -> P-03 Gate A decision (outcome: GRANTED or NOT APPROVED)

P-03 is the final decision outcome and is not an input to itself. A-13 does not
depend on P-03.

## 7. P-03 prerequisites

- Signed D11: EV-D11-01.
- Primary/backup owners and manager: EV-OWN-01/02/03.
- Records custodian: EV-REC-01.
- A-14 authority: EV-A14-AUTH-01.
- Manager review: EV-A14-REV-01.
- Spec/test approval: EV-SPEC-01 with paths, commit/version, individual SHA-256.
- S-00: SEC-PRE-01..08.
- Primary/backup acknowledgements: EV-ACK-01/02.
- E-03 actual branch: EV-BR-01.
- E-04 actual PG16: EV-ENV-01.
- S-01: SEC-POST-01..06.
- SEC-P2-01: EV-SEC-P2-01.
- ENG-P2-01: EV-ENG-P2-01.
- P-02 scope confirmation.
- A-13 evidence package: EV-GATEA-PKG-01.
- No mandatory control in NOT APPROVED.

P-03 itself is the decision, not a prerequisite.

## 8. Gate A versus Gate B

Gate A covers isolated engineering implementation and validation only. Gate B
separately controls production migration and deployment.

Gate A does not require the production operator runbook. Gate B requires the
current approved `RELEASE_1_P1_FINAL_OPERATOR_RUNBOOK.md`; the superseded
`RELEASE_1_P1_OPERATOR_RUNBOOK.md` is not valid for Gate B.

The Gate A approval record's "engineering change/ticket" means an isolated
engineering ticket, not a production deployment record.

## 9. Status model

- HOLD: missing prerequisite or evidence.
- NOT APPROVED: mandatory control failed or authorization refused.
- GRANTED: explicit Project Owner authorization after successful review.

## 10. Historical authority

Current authority: this register, D11 record, ownership record, production
isolation confirmation, Gate A approval record, final Gate A authorization
checklist, P1 execution tracker for G-* blockers, final decision register,
final P1 authorization checklist, implementation/test specifications, and
Gate A/B authorization documents.

Historical documents retain their original content and must not define new IDs.

## 11. Migration scope

FULL: `0031 -> 0032 -> 0032b -> 0033 -> 0034 -> 0035 -> 0036`.
REDUCED: `0031 -> 0032 -> 0032b -> 0033 -> 0034`.
REDUCED excludes both `0035` and `0036`.

No deferred index or P2 functionality is authorized by this register.

## 12. Amendment 1 - attestation separation (C-3)

Recorded 2026-11-14 under Project Owner decision C-3. The definitions in
sections 2 to 5 above are **not deleted or rewritten**. This amendment re-scopes
them and must be read together with them.

### 12.1 Problem this resolves

`ISO-08`, `SEC-PRE-08`, `SEC-POST-06`, `EV-SEC-P2-01` and `EV-ENG-P2-01` used
one term, "P2", for two unrelated things:

- prohibited **security, environmental and configuration** capability; and
- the **dispatch runtime** (claim, fencing, heartbeat, redispatch) that the
  consolidated Release 1 scope authorizes.

Once the consolidated scope is implemented, "no P2 runtime behavior" cannot be
attested truthfully, which would make the A-13 evidence package impossible to
complete.

### 12.2 Re-scoped definitions

| ID | Meaning from this amendment |
|---|---|
| SEC-P2-01 | Security attests that prohibited P2 **security, environmental and configuration** capabilities are absent: no production credentials, secrets, flags, deploy permissions, or reachable production configuration from the engineering environment. |
| EV-SEC-P2-01 | Evidence supporting SEC-P2-01. |
| ENG-P2-01 | Engineering attests that the implementation **matches the formally approved Release 1 engineering scope**: every authorized component is present, and no behavior outside that scope is present or enabled. |
| EV-ENG-P2-01 | Evidence supporting ENG-P2-01, including a component inventory mapped to R1-C01..R1-C15. |
| ISO-08 | Security/configuration exclusion only. The authorized dispatch runtime is governed by the approved scope, not by ISO-08. |
| SEC-PRE-08 / SEC-POST-06 | Unchanged in method: verify no prohibited configuration or flag is enabled. They no longer imply absence of the authorized dispatch runtime. |

### 12.3 Constraints preserved

- Two separate attestations remain mandatory: one security, one engineering.
- Neither attestation authorizes additional P2 functionality.
- Both remain mandatory A-13 evidence and neither is an input to P-03.
- No A-criterion is satisfied by this amendment.
- A-13 remains independent of P-03.

### 12.4 Status

Recorded as directed. The amendment itself remains subject to governance-authority
review, P-04 custody propagation, and the EV-TRACK-01 consistency check before it
is relied on as final.
