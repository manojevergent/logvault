"""Shared job state constants and helpers.

Kept dependency-free so both the API and the worker can import their own copy
without a shared package (the two images build independently).
"""

from __future__ import annotations

# Persisted job statuses. No new status is introduced by P1.
QUEUED = "queued"
RUNNING = "running"
PAUSED = "paused"
COMPLETED = "completed"
FAILED = "failed"
CANCELED = "canceled"

TERMINAL = frozenset({COMPLETED, FAILED, CANCELED})

# completion_state
UNKNOWN = "unknown"
COMPLETE = "complete"
PARTIAL = "partial"

COMPLETION_STATES = frozenset({UNKNOWN, COMPLETE, PARTIAL})

# outbox statuses
OUTBOX_PENDING = "pending"
OUTBOX_PUBLISHED = "published"
OUTBOX_DEAD = "dead"


def is_terminal(status: str | None) -> bool:
    return status in TERMINAL


def is_complete(state: str | None) -> bool:
    return state == COMPLETE


def is_partial(state: str | None) -> bool:
    return state == PARTIAL
