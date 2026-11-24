# Source-to-image provenance - candidate 7f2ac46-fix4

Commit: `7f2ac468e21de16e2feee9f2bd81b8fe0669c89b` (parent `84046b2`)
Worker image: `last9-worker:release-1-final-7f2ac46-fix4`
Image ID / index digest: `sha256:f96fac9f2d16a0b3141578111cc110313f6de5488dcc6f80868767fbfe224fbb`
Config digest: `sha256:4a3ea343a668f789e60451ae128a9e735807318c783ae7441b0f73ec9d8a1be3`

## Method

The image was built from `git archive --format=tar 7f2ac46`, not from the
working tree. The archive contains only tracked files and writes the bytes Git
stores (LF), so the build context is exactly the commit and is not affected by
`core.autocrlf=true` on this host.

The image was then extracted (`docker cp`) and every file compared with the
archive by SHA-256:

| Tree | Files in commit | Files in image | Mismatches | Missing | Extra |
|---|---|---|---|---|---|
| `worker/app` | 37 | 37 | **0** | 0 | 0 |
| `worker/tests` | 25 | 25 | **0** | 0 | 0 |

Because both sides are LF, the comparison is byte-identical - no CRLF
normalisation was needed, unlike the `84046b2` candidate where two files
differed only by line endings.

Key content assertions inside the image:

- `grep -c 'applied = save' /app/app/rollup.py` -> **3**
- `grep -c 'def test_' /app/tests/test_rollup_ownership.py` -> **13**
- `grep -c 'xfail'` on either file -> **0**

## Dependency provenance

`pip freeze` in the new worker image is identical to the `84046b2` worker image
(0 differing lines). The requirements layer was a cache hit; no dependency was
upgraded or downgraded by this build.

## Image format

BuildKit attestations were enabled, so the tag resolves to a manifest list
(index digest above). The `84046b2` worker image was a classic single-manifest
image whose ID equalled its config digest. Both are addressed by digest; the
difference is recorded so that a reviewer comparing `docker image inspect`
output between candidates is not surprised.

## Unchanged images

| Role | Tag | Digest | Note |
|---|---|---|---|
| API | `last9-api:release-1-final-84046b2-fix3` | `sha256:78f7f987...6396bb` | not rebuilt; no API source changed |
| Web | `last9-web:release-1-final-78fb0a7` | `sha256:6a6489dc...660ab1` | not rebuilt; still built with `http://localhost:8000` |

## What this does and does not prove

It proves: the worker image contains exactly the tracked source of `7f2ac46` at
the recorded digest, with the same dependencies as `84046b2`.

It does not prove: bit-reproducibility across hosts. The base image
(`python:3.12-slim`) is a floating tag, `pip` installs without hashes or a lock
file, and Docker image digests are not required to be identical when the same
Dockerfile is rebuilt elsewhere. "Reproducible" here means verifiable
commit-to-image provenance, not identical bytes on another machine.

## Known image contents beyond the application

- `tests/`, `requirements-dev.txt` and `pyproject.toml` ship in the image because
  the Dockerfile copies the whole context and `.dockerignore` does not exclude
  them. This is pre-existing, not introduced by this candidate.
- `worker/.impeccable/hook.cache.json` (184 bytes) is a tracked file in the
  repository and therefore present in the image. Pre-existing.

## Previous-package discrepancy found during this build

The frozen package `release-1-final-84046b2-fix3` ships a **stale copy** of
`0034_job_dispatch_outbox.py`: 2,309 bytes, SHA-256
`5DFC32753A84696B8A471286467CD38FD871C8313426879474A7427975F7AEEC`, without the
`LOCK TABLE ... ACCESS EXCLUSIVE` statement that commit `84046b2` contains. Its
own checksum file was consistent with the stale copy, so the discrepancy was
only visible by comparing the package file with `git show 84046b2:...`. The
other three migration copies match the commit.

That package is preserved unmodified as historical evidence. This candidate
copies all four migrations from `git show 7f2ac46:...`; the correct `0034` here
is 3,693 bytes, SHA-256
`550ED5AEA4EEBB0ECEEAEE1D84E5B3A1DB30F3FBDD5A5D7AA289230860395F0B`, and
contains the lock at line 82.

## Evidence scope inside this package

Documents that describe **this candidate**: `BUILD_LOG.md`, `PROVENANCE.md`,
`TEST_RESULTS.md`, `IMAGE_INVENTORY.md`, `HANDOVER.md`, `REMEDIATION_EVIDENCE.md`,
`RELEASE_NOTES.md`, `build-manifest.json`, `checksums.sha256`,
`CHECKSUMS_SHA256.txt`, `sbom-worker-pip.txt`, `sbom-api-pip.txt` (recaptured
from the retained API image), `sbom-web-npm.json` (copied - the web image is
unchanged).

Documents carried forward as **historical evidence** from earlier candidates and
not re-executed for this build: `DISPOSABLE_ENV_EVIDENCE.md`,
`INTEGRATION_EVIDENCE.md`, `MONITORING_EVIDENCE.md`, `MIGRATION_EVIDENCE.md`,
`LEASE_FIX_EVIDENCE.md`, `GATE_B_READINESS.md`, `SECURITY_*.md`,
`MONITORING_AND_ALERTS.md`, migration copies, `docker-compose.yml`,
`env.example`, and the deployment runbook. Where they name an older image or
scan date, that is their historical subject.
