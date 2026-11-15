# Release 1 P0 Failure Analysis

Status: analysis of the executed P0 evidence. No production code changed.

## 1. Failure summary

| ID | Area | Result | Severity | Impact |
|---|---|---|---|---|
| P0-13 | Celery/Redis visibility recovery | **FAIL** | High | Visibility alone did not redeliver a long task while two idle workers were already running. |
| P0-13b | New worker restore | PASS | High | Starting a new worker restored the unacked task and produced a duplicate start. |
| P0-12 | Checkpoint zero-commit contract | Initial mismatch, corrected | Medium | A zero-committed checkpoint must restart, not resume. |
| P0-S3-LIMIT | Real S3 provider | Blocked | Medium | Only a test stub was validated. |
| P0-16 | 24 h hard limit | Not executed | High | Only a 3 s hard limit mechanism was validated. |
| P0-18 | Long SIGTERM shutdown | Not executed at scale | Medium | Only a 5 s task was tested. |

## 2. P0-13 - visibility did not recover while workers were active

### Observed

- Celery 5.4.0, Kombu 5.4.2, Redis 7, `task_acks_late=True`,
  `task_reject_on_worker_lost=True`, visibility 5 s.
- Two solo workers already running.
- A task sleeping 10 s was sent.
- After 18 s only one start was recorded.
- Redis `unacked_index` retained the delivery; the queue list stayed empty.
- Starting a new worker (P0-13b) restored the unacked task and produced a second
  start.

### Why

Kombu's `QoS.restore_visible` is not a timer that always runs every
`visibility_timeout`. In Kombu 5.4.2 it increments a counter and only performs
restoration every 10th call (`interval=10`), and it is invoked from worker
poll/startup paths. A solo worker blocked in a long task does not call it; an
idle worker did not restore within the test window. A new worker startup did.

### Impact

- Visibility timeout is **not** a reliable recovery mechanism for long jobs.
- A rolling deploy/scaling event can restore an unacked long task while the
  original is alive, causing a duplicate start.
- Fencing prevents duplicate **writes**, but not duplicate **task execution** or
  slot consumption.
- A job could remain unacked indefinitely if no worker triggers restoration and
  no DB reconciler exists.

### Required architecture change

Add a **DB lease-expiry re-dispatch reconciler**:
- find `running` jobs with expired lease/progress and no active owner;
- publish a new `run_job` intent via outbox/Redis;
- cap attempts/backoff;
- fencing makes the duplicate safe.

This is stronger evidence for **Option C** (DB-authoritative dispatch) and
against relying on Option A visibility alone.

## 3. P0-12 - zero-committed checkpoint ambiguity

### Observed

After crashes before/during the first chunk, the checkpoint row existed with
`completed_chunks=0`; the artifact had partial rows and the store was empty.
The initial validator returned "resume" because `store_last_chunk=-1` was not
less than `completed_chunks-1=-1`.

### Resolution

A zero-committed checkpoint is **not recoverable work**. The contract now
requires restart when `completed_chunks=0`. The P0 test then passed all crash
cases: resume after DB/store-ahead, restart after fsync/store-missing/partial/
fingerprint.

### Impact

- A retry must not trust a zero-chunk checkpoint.
- The D3 contract was corrected; no production code exists yet.

## 4. P0-16 - hard limit mechanism, not production duration

### Observed

A prefork worker with a 3 s hard limit killed a 10 s task; one start, no normal
end. This validates the mechanism, not the proposed 24 h setting.

### Impact

- 23 h/24 h remains a business decision.
- Need production measurements of max attempt duration and shutdown behavior
  before setting limits.
- Hard kill resumes from checkpoint; soft-limit handling needs tests if used.

## 5. P0-18 - SIGTERM warm shutdown

A 5 s task finished during SIGTERM warm shutdown (stop 4.6 s). This does not
prove behavior for a multi-hour task or a Docker stop grace. Production needs a
stop-grace test; otherwise SIGKILL/checkpoint/recovery applies.

## 6. P0-S3-LIMIT - real provider behavior not validated

MinIO was unavailable from the container registry. A P0 HTTP S3 stub validated:
- path-style Put/Get/Head/Delete/List;
- unique attempt keys;
- DB pointer publication fence;
- cleanup preserving the published attempt.

Not validated:
- multipart upload/abort;
- conditional writes;
- IAM/signature/region behavior;
- versioning/object lock;
- provider-specific listing consistency.

The S3 publication design is conditional, not proven for a real provider.

## 7. Scratch-model limitations

| Test | What it proves | What it does not prove |
|---|---|---|
| P0-01..07 | Postgres conditional claim/fence/lease/reaper/cancel/pause SQL shape | Production ORM/session behavior, API concurrency |
| P0-08 | Scratch outbox claim/republish/execution gate | Production outbox transaction boundaries |
| P0-09 | Scratch ledger unique/lock/retry/snapshot | Production scheduler/report/rollup integration |
| P0-12 | Checkpoint protocol model | Production runner/CSV/store code |
| P0-11 | P0 S3 stub | Real S3 provider |
| P0-17 | Cleanup selection model | Production filesystem/DB paths |

## 8. Defects discovered

1. **Visibility is not a reliable recovery timer** (P0-13). Architecture must
   not depend on it.
2. **Worker startup can duplicate long tasks** (P0-13b). Fencing/claim are
   mandatory before scaling/rolling workers.
3. **Zero-chunk checkpoint ambiguity** (P0-12). Contract corrected to restart.
4. **Real S3 provider unverified** (P0-S3-LIMIT).
5. **No production-duration limit/shutdown evidence**.

## 9. Required architecture changes

- D9: adopt Option C (DB lease-expiry re-dispatch + hard/soft limits + explicit
  visibility as backstop). Do not rely on visibility.
- D8: progress/`progress_at` remains necessary; measure max silent stage.
- D3: zero-committed -> restart; keep the rest of the matrix.
- S3: mark provider behavior conditional until staging.
- Schedule ledger: DB primitives passed; integration still needed.

## 10. Residual risks

- Duplicate task starts during worker startup/scale; fencing stops writes but
  not slot use.
- Long-task unacked messages can accumulate if no reconciler.
- Hard limit setting not approved.
- Real S3 and production Postgres/Redis behavior unverified.
- No full T1-T24 lifecycle/API/frontend evidence.
