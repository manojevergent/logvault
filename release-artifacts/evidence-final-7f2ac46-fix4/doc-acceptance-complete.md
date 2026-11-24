
---

## Non-production acceptance - COMPLETE (candidate verified) - 2026-11-15T15:00Z

The candidate was exercised end to end against real Last9 data: commit
`7f2ac46`, schema `0034`, worker `f96fac9f…`, API `78f7f987…`, on a disposable
stack that was destroyed afterwards.

- login and credential test (`ok=true`, `valid`, `Connection successful`);
- manual extraction **job 1**: 14:58:35.508 → 14:58:39.092, **6,923 rows**, 1/1
  chunk, no error;
- download validated: 325,987-byte archive, **6,923 data rows**, header ok, every
  timestamp inside the requested window, count equals `rows_written`;
- scheduled run **job 2**: **7,192 rows**, completed 14:59:37.268;
- hard failure **job 3** (`token refresh returned HTTP 400`) and retry
  **job 4** failing identically;
- worker, beat and API logs captured.

A non-existent physical index was also tried: it yields the designed **partial**
completion with a recorded gap, not a hard failure.

The acceptance report is marked COMPLETE; GB-08 is PASS (technical). This does
not alter any finding in this document, does not name a reviewer, and does not
authorise production. **Gate B remains NOT GRANTED.**
