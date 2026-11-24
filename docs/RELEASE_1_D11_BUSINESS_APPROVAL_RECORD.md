# Release 1 D11 Business Decision Approval Record

Status: **UNSIGNED.** No decision is granted by this record. The business owner
must sign one option below.

This record is the authoritative D11 business decision. It supersedes earlier
wording that described a different reduced-scope variant.

## 1. Decision

Select exactly one:

- [ ] **FULL** — authorize the full calendar+interval schedule ledger.
  - Include `0035` (`schedule_windows` table and `jobs.schedule_window_id` /
    `attempt_no`).
  - Include `0036` (S3 attempt columns).
  - `0036.down_revision = "0035"`.
  - `0035b` and `0036b` remain deferred to P7/P8.
- [ ] **REDUCED** — exclude both `0035` and `0036`.
  - P1 revision graph becomes `0031 -> 0032 -> 0032b -> 0033 -> 0034`.
  - No `schedule_windows` table or `jobs` window columns in P1.
  - No S3 attempt columns in P1.
  - `0035`, `0036`, `0035b`, and `0036b` are out of scope.

## 2. Required approver

| Field | Value |
|---|---|
| Business owner name | ______________________________ |
| Role/title | ______________________________ |
| Date | ______________________________ |
| Selected option | FULL / REDUCED |
| Rationale | ______________________________ |
| Signature | ______________________________ |

The approver must be the authorized business owner for Release 1, not the
engineering agent.

## 3. Evidence required to close D11

- Signed/recorded selection of FULL or REDUCED.
- The selected graph matches the P1 documents.
- If FULL: `0035` and `0036` are authorized with
  `0036.down_revision="0035"`.
- If REDUCED: `0035` and `0036` are removed from Gate A scope.
- Decision recorded in the decision register, authorization checklist, and
  execution tracker.

## 3.1 Records custodian and propagation (P-04)

The Project Owner assigns a records custodian (P-04) after D11 signature. The
custodian updates the decision register, final authorization checklist, and P1
execution tracker; the Backup Engineering Owner verifies consistency. The
business owner remains the D11 signer only.

## 4. Effect on Gate A

| Selection | Gate A maximum revision scope |
|---|---|
| FULL | `0032`, `0032b`, `0033`, `0034`, `0035`, `0036` |
| REDUCED | `0032`, `0032b`, `0033`, `0034` |

What D11 blocks and does not block:

- Blocks: P-02 scope confirmation, P-04 records propagation, A14-01 (which must
  record the selected scope), and the `0035`/`0036` revisions.
- Does not block: P-01 role assignments, S-00 pre-provisioning verification, and
  M-01 preparation. Those proceed in parallel and must not wait on this decision.

All P2 behavior, production access, production migration, deployment, and
configuration changes remain prohibited under Gate A.

## 5. Status

**UNSIGNED — D11 remains blocked.**

Until the business owner signs, the tracker must show G-01 and G-07 as
**BLOCKED**, and `0035`/`0036` must not be authorized.
