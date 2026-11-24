# Security disposition request - Release 1

Scanner: pip-audit 2.10.1
Severity: not published by OSV in the scan output; CVSS review required. No
severity has been invented or assumed.
No dependency was changed. This scan is not S-00 or S-01.

Decision required from the Security Owner for each group below.

| # | Package | Installed | Advisories | Fix available | Proposed action | Decision |
|---|---|---|---|---|---|---|
| 1 | cryptography | 44.0.0 (API + worker) | PYSEC-2026-3553, -3554, -3552, -1284, -2141, -35, GHSA-537c-gmf6-5ccf | yes, 44.0.1 -> 50.0.0 | upgrade to 49.0.0, then re-scan | ____ |
| 2 | python-jose | 3.3.0 | PYSEC-2024-232, -233, PYSEC-2026-4298 | yes, 3.4.0 | patch bump | ____ |
| 3 | python-jose | 3.3.0 | PYSEC-2025-185 | none | replace library (PyJWT) or accept | ____ |
| 4 | starlette | 0.41.3 | PYSEC-2026-161, -1941, -1942, -2280, -2281, -248, -249 | yes, up to 1.3.1 | requires FastAPI 1.x - separate change | ____ |
| 5 | ecdsa | 0.19.2 | PYSEC-2026-1325 | none | removed by remediation 3 | ____ |

Options: ACCEPT (with rationale and review date) / REMEDIATE (authorise the
version change) / DEFER (state the release condition).

Groups 1 and 2 are contained changes testable with the existing suites
(test_crypto, test_tokens, test_google_auth, test_auth_throttle). Groups 3-5 are
cross-major and require a separate change approval.
