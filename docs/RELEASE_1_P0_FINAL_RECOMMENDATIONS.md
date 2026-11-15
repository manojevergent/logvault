# Release 1 P0 Final Recommendations

Status: final P0 assessment. No implementation beyond P0 test infrastructure was
performed. P1+ is not authorized.

## 1. Final P0 assessment

| Metric | Count |
|---|---|
| Tests executed | 19 |
| Passed | 18 |
| Failed | 1 (P0-13) |
| Blocked | 1 (real S3 provider) |
| Not executed | 23/24 h limits, production timing, production S3, full T1-T24 |

P0 is **complete as validation** but **not clean**: one test failed in a way that
changes the Celery/Redis architecture. P1 should not start until D9 is revised
and approved.

## 2. Required architecture changes

### 2.1 D9 - broker visibility is not recovery

P0-13 proved that a long unacked task is not reliably redelivered while workers
are already running. P0-13b proved a new worker startup can restore it and start
a duplicate. Therefore:

- Keep one task per job only if a **DB lease-expiry re-dispatch reconciler**
  exists.
- Treat visibility timeout as a backstop, not recovery.
- Fencing prevents duplicate writes, not duplicate starts/slot use.
- Add a running-job re-dispatch path with capped attempts/backoff.
- Do not set 24 h visibility as the sole recovery mechanism.
- Option B (bounded execution units) remains the long-term alternative.

### 2.2 D3 - zero committed chunks

A checkpoint row with `completed_chunks=0` is not recoverable work. Restart.
The contract is updated.

### 2.3 D8 - progress

`progress_at`/progress-aware heartbeat is necessary. P0 did not measure
production silent stages; values remain provisional.

### 2.4 D11 - schedule ledger primitives

P0-09 proved unique window/lock/dispatch/retry/snapshot/delete at the DB level.
It did not prove the production scheduler/report/rollup integration. The scope
decision (calendar+interval vs calendar-only) remains.

### 2.5 Artifact/S3

Attempt isolation passed. S3 provider behavior (multipart, conditional, IAM,
versioning, listing) is **blocked** until a real S3/MinIO staging test.

## 3. Defects/limitations discovered

1. P0-13 visibility failure (high).
2. P0-13b duplicate start on new worker (high).
3. Zero-chunk checkpoint ambiguity (medium; corrected).
4. Real S3 provider unavailable (medium).
5. 23/24 h limits not tested (high decision risk).
6. Production timing/eviction/stop-grace unverified.

## 4. Decisions requiring approval

| ID | Decision | Recommendation |
|---|---|---|
| D3 | Checkpoint/retry | Strict matrix, zero-commit restart; approve contract |
| D8 | Lease/progress | 600/60/60/3600/60 provisional; measure |
| D9 | Celery/Redis | Option C: DB re-dispatch + hard/soft limits + visibility backstop; approve limits |
| D10 | Completion | Minimum completion + UI partial |
| D11 | Schedule ledger | Full calendar+interval, or accepted split |
| D13 | Constraints | Audit then CHECKs |
| A1/A2 | Artifact/cleanup | Attempt paths + ownership rules |
| P0 | Test foundation | Complete with one failed test; next phase requires D9 revision |

## 5. Recommended next step

**Do not start P1.** First:

1. Revise D9 to make the DB lease-expiry re-dispatch reconciler a Release 1
   requirement.
2. Decide the hard/soft runtime limit (or explicitly accept stuck-slot risk).
3. Approve D3 zero-commit restart.
4. Decide D11 full ledger vs reduced scope.
5. Schedule a real S3/MinIO staging validation.
6. Schedule production timing measurements for D8.

After those approvals, the smallest safe production scope is:

- P1 additive schema/state primitives.
- P2 claim/fencing/progress/control phases.
- P4 attempt artifacts/checkpoints.
- P3 completion/UI.
- P8 S3 attempt publication.

P5/P6/P7 remain separately approved.

## 6. P0 evidence

- `p0/results/p0_results.json` — 19 executed, 18 pass, 1 fail.
- `p0/results/p0_manual_evidence.json` — AOF pass; real S3 blocked.
- `p0/results/logs/` — worker logs.
- `p0/results/checkpoint/` — crash matrix artifacts.
- `p0/results/artifacts/`, `p0/results/s3/` — isolation and S3 stub.

## 7. P0 verdict

**P0 primitive validation: partially successful.** The Postgres ownership,
fencing, cancel/pause, outbox, schedule ledger, checkpoint, artifact isolation,
worker kill/retry/limit/SIGTERM, and AOF primitives passed. The Celery/Redis
visibility assumption failed, requiring a DB-authoritative re-dispatch design.

**Full Release 1 remains NOT READY.** P1+ implementation is not authorized.
