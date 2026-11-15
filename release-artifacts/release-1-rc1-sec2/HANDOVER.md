# Release 1 RC1-sec2 - Handover to Gate B review

Date: 15 November 2026
Prepared for: Gate B review
Status: HANDED OVER FOR REVIEW - NOT PRODUCTION APPROVED

## What is being handed over

| Artifact | Tag | Immutable image ID |
|---|---|---|
| API | last9-api:release-1-rc1-monitoring-fix1-sec1 | sha256:5cf482c20c449c1cec4b0cad99064bc1f5cfca5ac7ad81afce260f97db7b4eea |
| Worker | last9-worker:release-1-rc1-monitoring-fix1-sec1 | sha256:c6f17b4959fe02cde852cb92547c81b267119c5e012366d7d24dbd28268426e5 |
| Web | last9-web:release-1-rc1-sec2 | sha256:11887ffd088d63cece66fdc1b1058c6c40c214910c2e4acb54eadbf25ebaa071 |
| Beat | worker image + python -m app.beat_guard | sha256:c6f17b4959fe02cde852cb92547c81b267119c5e012366d7d24dbd28268426e5 |

Database: REDUCED scope, head 0034 (0032, 0032b, 0033, 0034). 0035/0036 excluded.

## What changed since sec1

Only the web image. sec1 shipped a development image (npm run dev). sec2 builds
from web/Dockerfile.prod: multi-stage, Next.js standalone, node server.js,
non-root user, no dev tooling. Verified HTTP 200 in the isolated stack.
API, worker, migrations, runbooks and all other files are unchanged.

## Exceptions the reviewer must consider

1. Extraction, artifact creation and pointer publication were NOT tested against
   a live Last9 endpoint. All dispatcher, fencing, outbox, recovery, checkpoint
   and publication paths were validated with synthetic records. Accepted as a
   documented limitation by the Project Owner.
2. starlette 0.41.3 (7 advisories) and ecdsa 0.19.2 (1 advisory) remain deferred.
   Fixing starlette requires a FastAPI major upgrade; ecdsa has no fix and is
   only removed by replacing python-jose.
3. All approvals were self-certified by one individual holding every role
   (primary, backup, manager, custodian, A-14 authority), who also performed the
   implementation and granted Gate A. This is recorded, not endorsed.
4. NEXT_PUBLIC_API_BASE_URL is baked at build time as http://localhost:8000. The
   production web image must be rebuilt with the real API URL.

## What is verified

- API and worker images match the source tree file-for-file (SHA-256).
- 24 package files, checksums verified.
- API suite 289 passed; worker suite passed; frontend 8/8 and tsc clean.
- Stack verified: /ready ok, dispatch health reports lock, heartbeat, worker, queue.
- Migrations and rollback runbook tested on disposable PostgreSQL 16.
- Rollback drain drill passed all four gates.

## Sign-off

Integrity check performed by : MANOJ
Role                         : Tester
Date                         : 15 NOV 2026
Package                      : release-artifacts/release-1-rc1-sec2
Web image rebuilt and re-verified : YES - sha256:11887ffd088d63cece66fdc1b1058c6c40c214910c2e4acb54eadbf25ebaa071
Decision                     : HAND OVER TO GATE B REVIEW
Signature                    : MANOJ (as recorded 15 Nov 2026 on sec1; sec2 differs
                               only in the web image, which is rebuilt and verified)

Next step is a Gate B decision by the authorised production owner. This handover
does not grant Gate B and does not authorise deployment.
