
### Risk register status after 7f2ac46

| ID | Status after this candidate | Basis |
|---|---|---|
| RK-18 | **CLOSED BY EVIDENCE** - F-02a-1 is fixed in commit `7f2ac46` and in the verified worker image | 6 dedicated tests, 13/13 ownership, 284/284 suite, and 4 failed / 9 passed on the `84046b2` image |
| RK-19 | **OPEN** - no new evidence | rollup still validates its aggregation spec after the claim |
| RK-20 | **OPEN** - no new evidence | the gauge still flags rollups with no raw sources |
| RK-21 / RK-22 / RK-23 | remain **CLOSED BY EVIDENCE** | rollup tests, downgrade concurrency, blocked extraction |
| RK-24 | **NEW - OPEN**: release packages are assembled by hand and can drift from the commit. The `fix3` package's stale `0034` copy is proof. Mitigated for `fix4` by copying migrations from `git show` and verifying every file against the commit; the process risk itself is not closed, no owner is assigned and no acceptance is recorded. | package file differs from `git show 84046b2:...` |

Blocking set unchanged: RK-02 (GB-08), RK-03 (GB-01) and RK-06 (GB-05) block
Gate B; RK-04, RK-07 and RK-14 block deployment. RK-18 is no longer a condition
for acceptance of the source or of the `fix4` image, but an image built from
`84046b2` still carries the defect and must not be deployed.
