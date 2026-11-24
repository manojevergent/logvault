# Security scan status

Tool: pip-audit 2.10.1
Commands:
  pip-audit -r api/requirements.txt --progress-spinner off
  pip-audit -r worker/requirements.txt --progress-spinner off

API findings (OPEN): cryptography 44.0.0 (7 advisories), python-jose 3.3.0 (4),
starlette 0.41.3 (7), ecdsa 0.19.2 (1, no fix).
Worker findings (OPEN): cryptography 44.0.0 (same 7).

Severity: not published by OSV in this output; CVSS review required.
No dependency was upgraded. Scan is not S-00 or S-01.
