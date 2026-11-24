# Build log - candidate 7f2ac46-fix4

Commit: `7f2ac468e21de16e2feee9f2bd81b8fe0669c89b` (parent `84046b2`)
Branch: `release-1/p1-dispatch`
Builder: Docker Desktop 29.8.2, BuildKit
Host: Windows, `core.autocrlf=true` (bypassed by building from `git archive`)

## Input

```powershell
git archive --format=tar 7f2ac46 > src.tar
tar -xf src.tar -C src
```

The archive contains tracked files only, with the bytes stored in Git (LF), so
the build context contains no `celerybeat-schedule`, `.pytest_cache`,
`.ruff_cache` or other untracked working-tree residue.

## Build

```powershell
docker build --progress=plain -t last9-worker:release-1-final-7f2ac46-fix4 src\worker
```

| Field | Value |
|---|---|
| Command exit code | **0** |
| Start (UTC) | 2026-11-15T13:55:54Z |
| End (UTC) | 2026-11-15T13:55:57Z |
| Base image | `python:3.12-slim` (floating tag; layers resolved at build time) |
| Requirements layer | cache hit - installed packages identical to the 84046b2 worker image |
| Image ID / index digest | `sha256:f96fac9f2d16a0b3141578111cc110313f6de5488dcc6f80868767fbfe224fbb` |
| Config digest (build output) | `sha256:4a3ea343a668f789e60451ae128a9e735807318c783ae7441b0f73ec9d8a1be3` |
| Attestations | BuildKit provenance and SBOM manifests present, so the tag resolves to a manifest list. The `84046b2` worker was a classic single-manifest image; both are referenced by digest the same way. |

## Not built

- **API** - no API source changed since `84046b2`; the existing image
  `sha256:78f7f987...6396bb` is retained and re-verified (289 tests).
- **Web** - unchanged; `NEXT_PUBLIC_API_BASE_URL` is still `http://localhost:8000`,
  so GB-05 remains blocked.

## Dependency inventory

`pip freeze` inside the new worker image is identical to the `84046b2` worker
image (0 differing lines). See `sbom-worker-pip.txt` and
`evidence-final-7f2ac46-fix4/sbom-worker-diff.txt`.
