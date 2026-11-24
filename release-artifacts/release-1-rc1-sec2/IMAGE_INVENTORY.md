# Image inventory

| Role | Tag | Immutable image ID | Status |
|---|---|---|---|
| API | last9-api:release-1-rc1-monitoring-fix1-sec1 | sha256:5cf482c20c449c1cec4b0cad99064bc1f5cfca5ac7ad81afce260f97db7b4eea | CURRENT |
| Worker | last9-worker:release-1-rc1-monitoring-fix1-sec1 | sha256:c6f17b4959fe02cde852cb92547c81b267119c5e012366d7d24dbd28268426e5 | CURRENT |
| Web | last9-web:release-1-rc1-sec2 | sha256:11887ffd088d63cece66fdc1b1058c6c40c214910c2e4acb54eadbf25ebaa071 | CURRENT - production build |
| Beat | worker image + `python -m app.beat_guard` | sha256:c6f17b4959fe02cde852cb92547c81b267119c5e012366d7d24dbd28268426e5 | CURRENT |

Web image details: built from `web/Dockerfile.prod` (multi-stage, Next.js
standalone). Runs `node server.js` as user `nextjs`; no dev dependencies and
no `.bin` tooling in the final layer. Serves HTTP 200 in the isolated stack.

Superseded, retained, do not deploy:
- last9-web:release-1-rc1 (sha256:49bb152ad3908ef5e57f6bd84083c96ccd971bbc06f7fe5851c8837ff659ad11) - DEVELOPMENT image (npm run dev), not a production build
- last9-api:release-1-rc1-monitoring-fix1 (4c0226b9...) - pre-security remediation
- last9-api:release-1-rc1 (5db8099...) - pre-monitoring fix
- last9-worker:release-1-rc1 (706fb977...) - pre-security remediation

No image was pushed to a registry; the image ID is the immutable reference.
