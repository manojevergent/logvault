"""Exception hierarchy for the Last9 client.

Callers distinguish:
- PipelineError       — bad filter/operator at build time (programmer error).
- AuthExpiredError    — refresh failed or repeated 401/expired (credential problem).
- TransientBadRequestError — a 400 that survived retries; skip this batch, continue.
- RetryableError      — 5xx/timeout/connection exhausted all attempts.
- FatalClientError    — non-retryable 4xx (403/404/429): fail fast.
"""

from __future__ import annotations


class Last9Error(Exception):
    """Base class for all Last9 client errors."""


class PipelineError(Last9Error):
    """Invalid filter specification or operator (§2.5)."""


class AuthExpiredError(Last9Error):
    """Token refresh failed, or auth kept failing after refresh (§2.2)."""


class TransientBadRequestError(Last9Error):
    """HTTP 400 that persisted past its retry budget (§2.10). Skippable per batch."""

    def __init__(self, message: str, *, status: int = 400, body: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class RetryableError(Last9Error):
    """5xx / timeout / connection error that exhausted all retry attempts (§2.10)."""

    def __init__(self, message: str, *, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts


class FatalClientError(Last9Error):
    """Non-retryable 4xx such as 403/404/429 (§2.10)."""

    def __init__(self, message: str, *, status: int, body: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
