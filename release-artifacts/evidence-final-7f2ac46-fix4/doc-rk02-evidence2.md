
---

## RK-02 evidence update - 2026-11-15T14:45Z

RK-02 ("live Last9 extraction never tested") has moved from attestation to
**partial evidence**:

- job 976 completed with 15,423 real rows, 3/3 chunks, in 8 s; the exported
  archive was parsed and its rows all fall inside the requested window
  (detail in `RELEASE_1_NON_PRODUCTION_ACCEPTANCE_REPORT.md`);
- the Last9 org/index/credential path works from this host:
  credential 9 (`Singapore`, `evergentapse1`), index 4 (`UMS_singapore`).

**However**, the run used the pre-Release-1 application (`E:\last9_web_app`,
schema `0031`, dev images from 2026-11-12), not the candidate (`7f2ac46`,
schema `0034`, worker `f96fac9f…`). Scheduled extraction, failure handling and
retry are also unevidenced.

**RK-02 remains OPEN.** Severity is unchanged; likelihood of an extraction
failure in the candidate is now materially lower because the external
dependency is proven. Closure requires the candidate run described in the
acceptance report.

RK-19, RK-20 and RK-24 remain OPEN and are unaffected.
