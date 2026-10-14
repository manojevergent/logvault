"""Last9 query client: authenticated requests, retry policy, and streaming
pagination (§2.1–§2.3, §2.8, §2.10).

The client never accumulates rows in memory — :meth:`iter_rows` yields each row
as it is parsed. Retry policy (§2.10):

- 5xx / timeout / connection error -> exponential backoff, up to ``max_attempts``
  (10), delay capped at ``backoff_cap`` (300s).
- HTTP 400 -> retry up to 3 times at a flat 5s, then raise
  :class:`TransientBadRequestError` (caller skips that batch and continues).
- Other 4xx (403/404/429) -> :class:`FatalClientError` immediately.
- 401, or HTTP 200 whose body contains "Authorization token is expired" ->
  refresh the token inline and retry (§2.2).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx

from .constants import DEFAULT_DIRECTION, DEFAULT_LIMIT, DEFAULT_STEP
from .errors import (
    AuthExpiredError,
    FatalClientError,
    RetryableError,
    TransientBadRequestError,
)
from .tokens import TokenManager

_EXPIRED_TOKEN_MARKER = "Authorization token is expired"
_EXPIRED_TOKEN_MARKER_BYTES = _EXPIRED_TOKEN_MARKER.encode()
_MESSAGE_KEYS = ("message", "Message", "Body", "body", "msg")


@dataclass
class LogRow:
    """One extracted log line."""

    timestamp: str
    message: str
    raw: str


class Last9Client:
    def __init__(
        self,
        *,
        token_manager: TokenManager,
        org_slug: str,
        api_base: str,
        http: httpx.Client,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 10,
        backoff_cap: float = 300.0,
        bad_request_attempts: int = 3,
        bad_request_delay: float = 5.0,
        max_auth_refreshes: int = 2,
    ) -> None:
        self._tokens = token_manager
        self._http = http
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._backoff_cap = backoff_cap
        self._bad_request_attempts = bad_request_attempts
        self._bad_request_delay = bad_request_delay
        self._max_auth_refreshes = max_auth_refreshes
        base = api_base.rstrip("/")
        self._query_url = f"{base}/organizations/{org_slug}/logs/api/v2/query_range/json"

    # ── public API ───────────────────────────────────────────────────────────

    def iter_rows(
        self,
        *,
        index: str,
        region: str,
        start: int,
        end: int,
        pipeline: list[dict[str, Any]],
        limit: int = DEFAULT_LIMIT,
    ) -> Iterator[LogRow]:
        """Stream rows for one time window, paging until a short page (§2.8)."""
        offset = 0
        while True:
            params = {
                "start": start,
                "end": end,
                "limit": limit,
                "direction": DEFAULT_DIRECTION,
                "step": DEFAULT_STEP,
                "offset": offset,
                "index": index,
                "region": region,
            }
            parsed = self._execute(params, {"pipeline": pipeline})
            page_count = 0
            for stream in _result_streams(parsed):
                for value in stream.get("values", []) or []:
                    page_count += 1
                    yield _row_from_value(value)
            # Fewer than a full page means we've reached the end of this window.
            if page_count < limit:
                return
            offset += limit

    # ── request execution with the §2.10 retry policy ─────────────────────────

    def _execute(self, params: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        retryable = 0
        bad_request = 0
        auth_refreshes = 0
        last_error_body = ""

        while True:
            try:
                resp = self._http.post(
                    self._query_url, params=params, json=body, headers=self._headers()
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                retryable += 1
                if retryable >= self._max_attempts:
                    raise RetryableError(
                        f"request failed after {retryable} attempts: {exc!r}",
                        attempts=retryable,
                    ) from exc
                self._sleep(self._backoff(retryable))
                continue

            status = resp.status_code

            if status == 200:
                # Scanned as bytes: `resp.text` decodes the whole body to a str
                # that is then thrown away, and `resp.json()` re-parses from
                # `resp.content` anyway. At limit=10000 that is a multi-MB
                # allocation and scan on every page of every chunk.
                if _EXPIRED_TOKEN_MARKER_BYTES in resp.content:
                    auth_refreshes += 1
                    if auth_refreshes > self._max_auth_refreshes:
                        raise AuthExpiredError("token still expired after refresh")
                    self._tokens.refresh()
                    continue
                return resp.json()

            if status == 401:
                auth_refreshes += 1
                if auth_refreshes > self._max_auth_refreshes:
                    raise AuthExpiredError("received 401 after refreshing token")
                self._tokens.refresh()
                continue

            if status == 400:
                bad_request += 1
                if bad_request >= self._bad_request_attempts:
                    raise TransientBadRequestError(
                        f"HTTP 400 persisted after {bad_request} attempts",
                        body=resp.text,
                    )
                self._sleep(self._bad_request_delay)
                continue

            if 500 <= status < 600:
                retryable += 1
                last_error_body = resp.text
                if retryable >= self._max_attempts:
                    raise RetryableError(
                        _status_message(status, last_error_body, f"after {retryable} attempts"),
                        attempts=retryable,
                    )
                self._sleep(self._backoff(retryable))
                continue

            # Other 4xx (403/404/429, …) — fast-fail.
            raise FatalClientError(
                _status_message(status, resp.text), status=status, body=resp.text
            )

    def _headers(self) -> dict[str, str]:
        # §2.2 — custom header, NOT the standard Authorization header.
        return {
            "X-LAST9-API-TOKEN": f"Bearer {self._tokens.get_access_token()}",
            "Content-Type": "application/json",
        }

    def _backoff(self, attempt: int) -> float:
        return min(self._backoff_cap, 2 ** (attempt - 1))


# ── response parsing (§2.8) ───────────────────────────────────────────────────


def _result_streams(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """Locate the list of streams. Defensive about the exact nesting.

    The documented shape is ``data.data.result`` (§2.8); some responses nest one
    level shallower. ``result`` is ``null`` when empty.
    """
    for path in (("data", "data", "result"), ("data", "result"), ("result",)):
        cursor: Any = parsed
        for key in path:
            if isinstance(cursor, dict) and key in cursor:
                cursor = cursor[key]
            else:
                cursor = _MISSING
                break
        if cursor is not _MISSING:
            return cursor or []
    return []


def _error_detail(text: str, limit: int = 200) -> str:
    """The useful sentence out of an error body.

    Last9 answers with ``{"message": "You don't have access to this resource."}``
    or ``{"error": "ERR_S3_CONFIG_MISSING"}``. Surfacing only the status code
    turns both of those into a bare "HTTP 403", which says nothing about whether
    the credential, the org, the region or the index is at fault.
    """
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        for key in ("message", "error", "detail"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:limit]
    return " ".join((text or "").split())[:limit]


def _status_message(status: int, body: str, suffix: str = "") -> str:
    head = f"HTTP {status}" + (f" {suffix}" if suffix else "")
    detail = _error_detail(body)
    return f"{head}: {detail}" if detail else head


def _row_from_value(value: list[Any]) -> LogRow:
    timestamp = str(value[0]) if value else ""
    raw = value[1] if len(value) > 1 else ""
    raw_str = raw if isinstance(raw, str) else json.dumps(raw)
    return LogRow(timestamp=timestamp, message=_extract_message(raw_str), raw=raw_str)


def _extract_message(raw_line: str) -> str:
    """Pull a human message out of a raw line, which may be JSON (§2.8)."""
    try:
        obj = json.loads(raw_line)
    except (json.JSONDecodeError, ValueError):
        return _extract_message_from_broken_json(raw_line)
    if isinstance(obj, dict):
        for key in _MESSAGE_KEYS:
            val = obj.get(key)
            if val is not None:
                return val if isinstance(val, str) else json.dumps(val)
    return raw_line


# Applications do emit envelopes that aren't valid JSON — most often because a
# redaction step drops bare quotes into a string value:
#     {"level":"TRACK","message":"... apiPassword="***REDACTED***" ..."}
# Strict parsing fails there, and handing back the whole envelope means every
# parse pattern has to match JSON wrapper text instead of the log line.
_BROKEN_JSON_MESSAGE = re.compile(
    r'"(?:' + "|".join(_MESSAGE_KEYS) + r')"\s*:\s*"(?P<msg>.*)"\s*\}\s*$',
    re.DOTALL,
)


def _extract_message_from_broken_json(raw_line: str) -> str:
    """Best-effort message for an envelope that won't parse.

    Greedy to the final quote before the closing brace, which is exact when the
    message is the last key — the usual shape, since it's the bulk of the line.
    If other keys follow it, this over-captures their text rather than losing the
    message; the untouched original is still on ``LogRow.raw``.
    """
    if not raw_line.startswith("{"):
        return raw_line
    m = _BROKEN_JSON_MESSAGE.search(raw_line)
    return m.group("msg") if m else raw_line


_MISSING = object()
