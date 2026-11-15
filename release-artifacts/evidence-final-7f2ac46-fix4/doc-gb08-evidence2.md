
---

## GB-08 evidence review #2 - 2026-11-15T14:45Z (real extraction, non-candidate build)

Evidence was supplied and independently checked against the running system
(details in `RELEASE_1_NON_PRODUCTION_ACCEPTANCE_REPORT.md`):

- job **976**, `completed`, 15,423 rows, 3/3 chunks, window
  `2026-11-15 12:39:52–14:39:52 UTC`, created 14:39:56.570, finished
  14:40:04.745 (live `jobs` row and `job_events`);
- worker task received 14:39:56.738, succeeded in 8.0136 s;
- exported archive 309,505 bytes, opened and parsed: 15,423 data rows, header
  `timestamp,sessionToken,channelPartnerID,api_name`, every timestamp inside the
  requested window;
- credential id 9 (`Singapore`, org `evergentapse1`), index id 4
  (`UMS_singapore`, `ap-southeast-1`).

**But that run used the pre-Release-1 application**: source `E:\last9_web_app`
at `98d26ca`, dev images built 2026-11-12, database schema **0031**, no
`lease_token`/`owner_id`/`completion_state`, no `job_dispatch_outbox`. The
candidate is `7f2ac46`, schema **0034**, worker `f96fac9f…`, and was not
exercised. A9 (schedule), A10 (failure) and A11 (retry) have no record: the
`schedules` table is empty and there is no failed job in the last two days.

**GB-08 remains OPEN - PARTIAL.** The external Last9 dependency (token type,
org, index, query, CSV) is now proven from this host, which is the largest part
of the risk. What remains is the candidate path itself: one A4–A8 run on
`7f2ac46`/schema `0034`/worker `f96fac9f…`, plus A9–A11. This supersedes the
earlier "attested, unevidenced" note; nothing else in the register changes.

**GB-11 remains NOT GRANTED.** Non-production technical testing is not a
production authorisation.
