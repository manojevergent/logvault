
---

## Non-production acceptance evidence - 2026-11-15T14:45Z

A real acceptance record now exists and was checked against the running system:
job **976**, completed, **15,423 rows**, 3/3 chunks, window 12:39:52–14:39:52 UTC,
finished 14:40:04.745; worker task succeeded in 8.0136 s; the exported archive
(309,505 bytes) was opened and parsed — 15,423 data rows, correct header, all
timestamps inside the window. Full detail is in
`RELEASE_1_NON_PRODUCTION_ACCEPTANCE_REPORT.md`.

**It was produced by the pre-Release-1 application, not by this candidate.**
The stack was `E:\last9_web_app` at `98d26ca`, dev images built 2026-11-12,
database schema **0031** (no lease, owner, completion-state or outbox columns).
The candidate is `7f2ac46`, schema `0034`, worker `f96fac9f…`, and has not run a
real extraction.

Consequences for this report:

- A4–A8 and A12 are **verified for the base application**; they do not
  constitute candidate acceptance.
- A9 (schedule), A10 (failure) and A11 (retry) are **not evidenced at all** — no
  schedule exists and no failed job was recorded.
- GB-08 is **PARTIAL**: the Last9 external dependency is proven; the candidate's
  runner path is not.

No finding in this report changes. No reviewer is named. Gate B remains
**NOT GRANTED**.
