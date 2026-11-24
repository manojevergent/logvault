
---

## Integration evidence verified - 2026-11-15T15:00Z

The candidate was exercised against real Last9 data on a disposable stack
(schema `0034`, worker `f96fac9f…`, API `78f7f987…`):

- manual job **1**: completed in 3.6 s with **6,923 rows**;
- downloaded archive validated: 6,923 data rows, header ok, every timestamp
  inside the requested window, count equals `rows_written`;
- scheduled job **2**: **7,192 rows**;
- invalid credential: job **3** failed with `token refresh returned HTTP 400`;
  manual retry job **4** failed identically;
- worker/beat/API logs captured.

A non-existent physical index produced the designed **partial** completion with a
recorded gap rather than a hard failure — behaviour worth knowing, not a defect.

Finding statuses are unchanged. GB-08 is now PASS (technical); GB-01, GB-05 and
the other production gates remain open. No reviewer is named; Gate B remains
**NOT GRANTED**.
