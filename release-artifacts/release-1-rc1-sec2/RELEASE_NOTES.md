# Release 1 RC1 - Release Notes

Status: RC1 - SECURITY REVIEW REQUIRED - NOT APPROVED FOR PRODUCTION

Built from branch release-1/p1-dispatch at HEAD 6719568f with uncommitted
Release 1 changes (16 modified, 18 untracked files).

Includes: transactional outbox, fenced claim, progress heartbeat, lease
reconciler, attempt artifacts, guarded publication, strict checkpoint,
partial completion, dedicated beat with Redis singleton guard, dispatch health
endpoint with broker gauges, frontend partial-completion badges.

Migrations 0032-0034. Schema head 0034. New code MUST NOT run on 0031.

Not included: 0035/0036 (D11 unsigned), task failure/retry metrics.

Approvals: Gate A and Gate B NOT GRANTED. No approval was fabricated.
