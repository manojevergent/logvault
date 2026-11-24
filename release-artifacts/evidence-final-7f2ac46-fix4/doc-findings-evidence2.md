
---

## Integration evidence update - 2026-11-15T14:45Z

A real extraction record was supplied and verified: job **976**, completed,
15,423 rows, 3/3 chunks, window 12:39:52–14:39:52 UTC, finished 14:40:04.745;
worker task 8.0136 s; exported archive parsed with 15,423 rows and all
timestamps inside the window. Detail in
`RELEASE_1_NON_PRODUCTION_ACCEPTANCE_REPORT.md`.

The run belongs to the **pre-Release-1 application** (`E:\last9_web_app`,
schema `0031`, dev images from 2026-11-12), **not** to commit `7f2ac46`
(schema `0034`, worker `f96fac9f…`). Scheduled extraction, expected failure and
manual retry have no supporting record.

Finding statuses are unchanged. F-02a, F-04, F-13 and F-02a-1 remain corrected
and engineering-verified; extraction integration is partially evidenced for the
base application and unproven for the candidate, so GB-08 stays open.

No reviewer is named; Gate B remains **NOT GRANTED**.
