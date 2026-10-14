"""Access-token lifecycle (§2.2).

Access tokens expire in 24h. The refresh endpoint returns a fresh
``access_token``, sometimes a rotated ``refresh_token``, and an expiry. An
optional ``on_rotate`` callback lets the caller persist rotated tokens
(encrypted, in Postgres — Phase 3/4). Token values must never be logged.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from .errors import AuthExpiredError

# Refresh 5 minutes before expiry — avoids racing a 401 on long-running chunks.
_EXPIRY_BUFFER_SECONDS = 300
_ASSUMED_LIFETIME_SECONDS = 24 * 3600


def _is_retryable_status(status: int) -> bool:
    """Server-side or rate-limit failures clear on their own; 4xx does not."""
    return status >= 500 or status == 429


@dataclass
class TokenSet:
    refresh_token: str
    access_token: str | None = None
    expires_at: int | None = None  # epoch seconds


class TokenManager:
    """Holds a :class:`TokenSet` and refreshes it on demand."""

    def __init__(
        self,
        token_set: TokenSet,
        *,
        api_base: str,
        http: httpx.Client,
        on_rotate: Callable[[TokenSet], None] | None = None,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 5,
        backoff_cap: float = 60.0,
    ) -> None:
        self._tokens = token_set
        self._oauth_url = f"{api_base.rstrip('/')}/oauth/access_token"
        self._http = http
        self._on_rotate = on_rotate
        self._now = now
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._backoff_cap = backoff_cap

    @property
    def tokens(self) -> TokenSet:
        return self._tokens

    def get_access_token(self) -> str:
        """Return a valid access token, refreshing if missing or near expiry."""
        if not self._tokens.access_token or self._is_expired():
            self.refresh()
        assert self._tokens.access_token is not None
        return self._tokens.access_token

    def refresh(self) -> str:
        """Force a token refresh. Raises :class:`AuthExpiredError` on failure.

        Transient failures (connection errors, 5xx, 429) are retried with the
        same exponential backoff the query path uses. A refresh that fails once
        used to end the whole job, and a failed job can only be re-run from
        scratch — so a single 503 here threw away every chunk already extracted.

        A 4xx other than 429 is not retried: the refresh token is genuinely
        rejected, and repeating the call only delays the error.
        """
        resp = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                resp = self._http.post(
                    self._oauth_url, json={"refresh_token": self._tokens.refresh_token}
                )
            except httpx.HTTPError as exc:
                if attempt >= self._max_attempts:
                    raise AuthExpiredError(
                        f"token refresh request failed after {attempt} attempts: {exc!r}"
                    ) from exc
                self._sleep(self._backoff(attempt))
                continue

            if resp.status_code == 200:
                break
            if not _is_retryable_status(resp.status_code) or attempt >= self._max_attempts:
                raise AuthExpiredError(f"token refresh returned HTTP {resp.status_code}")
            self._sleep(self._backoff(attempt))

        assert resp is not None  # loop either breaks with a response or raises
        payload = resp.json()
        access = payload.get("access_token")
        if not access:
            raise AuthExpiredError("token refresh response missing access_token")

        self._tokens.access_token = access
        rotated = payload.get("refresh_token")
        if rotated:
            self._tokens.refresh_token = rotated
        self._tokens.expires_at = _parse_expiry(payload, self._now())

        if self._on_rotate:
            self._on_rotate(self._tokens)
        return access

    def _backoff(self, attempt: int) -> float:
        return min(self._backoff_cap, 2 ** (attempt - 1))

    def _is_expired(self) -> bool:
        # No known expiry but a token in hand: trust it; a 401 will trigger refresh.
        if self._tokens.expires_at is None:
            return False
        return self._now() >= self._tokens.expires_at - _EXPIRY_BUFFER_SECONDS


def _parse_expiry(payload: dict[str, Any], now: float) -> int:
    """Resolve an expiry epoch from ``expires_at`` (epoch or ISO) or ``expires_in``."""
    if "expires_at" in payload and payload["expires_at"] is not None:
        value = payload["expires_at"]
        if isinstance(value, int | float):
            return int(value)
        try:
            iso = str(value).replace("Z", "+00:00")
            return int(datetime.fromisoformat(iso).timestamp())
        except ValueError:
            pass
    if "expires_in" in payload and payload["expires_in"] is not None:
        return int(now + float(payload["expires_in"]))
    return int(now + _ASSUMED_LIFETIME_SECONDS)
