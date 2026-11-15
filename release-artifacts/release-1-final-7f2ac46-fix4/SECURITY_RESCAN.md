# Security rescan after approved remediation (2026-11-15)

Applied: cryptography 44.0.0 -> 50.0.0, python-jose 3.3.0 -> 3.4.0 (API and worker).
Scanner: pip-audit 2.10.1.

Worker: No known vulnerabilities found.
API:    cryptography CLEAN, python-jose CLEAN.
        Remaining: starlette 0.41.3 (7 advisories, needs FastAPI 1.x - deferred),
                   ecdsa 0.19.2 (PYSEC-2026-1325, removed only by replacing
                   python-jose - deferred).

Regression after upgrade: API 289 passed, worker suite passed.
Rollback of the upgrade: revert the two pins and rebuild; no schema or API change.
