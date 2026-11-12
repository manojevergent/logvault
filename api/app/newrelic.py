"""New Relic NerdGraph client and NRQL result normalization.

Only two operations are needed: validate an account/API key, and run one NRQL
query. Everything else here exists so the comparison UI can reduce the
provider's row shapes to a total plus a time series without knowing whether the
saved NRQL used TIMESERIES, FACET, or a custom aggregate alias.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

GRAPHQL_URLS = {
    "us": "https://api.newrelic.com/graphql",
    "eu": "https://api.eu.newrelic.com/graphql",
}

_DEFAULT_TIMEOUT = 60.0
_TIME_KEYS = frozenset(
    {
        "beginTime",
        "endTime",
        "beginTimeMillis",
        "endTimeMillis",
        "startTime",
        "timestamp",
        "timeSince",
    }
)

_QUERY = """
query($accountId: Int!, $nrql: Nrql!) {
  actor {
    account(id: $accountId) {
      nrql(query: $nrql) {
        results
        metadata { timeWindow { begin end } }
      }
    }
  }
}
"""

_ACCOUNT_QUERY = """
query($accountId: Int!) {
  actor {
    account(id: $accountId) {
      id
      name
    }
  }
}
"""


class NewRelicError(ValueError):
    """A user-actionable New Relic failure (bad key, bad account, bad NRQL)."""


@dataclass
class NewRelicQueryResult:
    results: list[dict[str, Any]]
    metadata: dict[str, Any] | None
    elapsed_ms: int


def graphql_url(region: str) -> str:
    return GRAPHQL_URLS.get((region or "us").lower(), GRAPHQL_URLS["us"])


def _post_graphql(
    *, api_key: str, region: str, payload: dict[str, Any], timeout: float
) -> dict[str, Any]:
    if not api_key:
        raise NewRelicError("New Relic API key is missing")
    try:
        resp = httpx.post(
            graphql_url(region),
            json=payload,
            headers={"API-Key": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        # The exception text carries the endpoint, never the API-Key header.
        raise NewRelicError(f"could not reach New Relic: {exc}") from exc

    try:
        body = resp.json()
    except ValueError:
        raise NewRelicError(
            f"New Relic returned HTTP {resp.status_code}: {resp.text[:300]}"
        ) from None
    if not isinstance(body, dict):
        raise NewRelicError("New Relic returned an unexpected response")

    errors = body.get("errors") or []
    if errors:
        message = "; ".join(
            str(e.get("message") or e) if isinstance(e, dict) else str(e) for e in errors
        )
        raise NewRelicError(message[:600])

    if resp.status_code >= 400:
        raise NewRelicError(f"New Relic returned HTTP {resp.status_code}")

    data = body.get("data") or {}
    if not isinstance(data, dict):
        raise NewRelicError("New Relic returned an unexpected response")
    return data


def test_connection(*, api_key: str, account_id: int, region: str, timeout: float = 15.0) -> str:
    """Return the account name if the key can read this account."""
    data = _post_graphql(
        api_key=api_key,
        region=region,
        payload={
            "query": _ACCOUNT_QUERY,
            "variables": {"accountId": int(account_id)},
        },
        timeout=timeout,
    )
    actor = data.get("actor") or {}
    account = actor.get("account") if isinstance(actor, dict) else None
    if not isinstance(account, dict):
        raise NewRelicError(
            "account not found or not accessible with this API key "
            "(check the account id and US/EU region)"
        )
    name = account.get("name")
    return str(name) if name else f"account {account_id}"


def execute_nrql(
    *,
    api_key: str,
    account_id: int,
    region: str,
    nrql: str,
    timeout: float = _DEFAULT_TIMEOUT,
) -> NewRelicQueryResult:
    started = time.monotonic()
    data = _post_graphql(
        api_key=api_key,
        region=region,
        payload={"query": _QUERY, "variables": {"accountId": int(account_id), "nrql": nrql}},
        timeout=timeout,
    )
    actor = data.get("actor") or {}
    account = actor.get("account") if isinstance(actor, dict) else None
    if not isinstance(account, dict):
        raise NewRelicError("account not found or not accessible with this API key")
    nrql_result = account.get("nrql")
    if not isinstance(nrql_result, dict):
        raise NewRelicError("New Relic returned no NRQL result")

    raw_results = nrql_result.get("results")
    if raw_results is None:
        raw_results = []
    if not isinstance(raw_results, list):
        raise NewRelicError("New Relic returned an unexpected NRQL result shape")
    results = [row for row in raw_results if isinstance(row, dict)]
    metadata = nrql_result.get("metadata")
    return NewRelicQueryResult(
        results=results,
        metadata=metadata if isinstance(metadata, dict) else None,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )


# ── NRQL rewrite: selected window + a known TIMESERIES bucket ─────────────────
#
# The saved NRQL is the user's text. On each run we replace only its time
# window and bucket so both providers describe the same slice of time. The
# effective query is stored on the run and shown in the UI, so nothing is
# silently hidden.

_CLAUSE_KEYWORDS = {"SINCE", "UNTIL", "TIMESERIES", "FACET", "LIMIT", "WITH", "COMPARE"}
_UNIT_SECONDS = {
    "SECOND": 1,
    "SECONDS": 1,
    "MINUTE": 60,
    "MINUTES": 60,
    "HOUR": 3600,
    "HOURS": 3600,
    "DAY": 86400,
    "DAYS": 86400,
    "WEEK": 604800,
    "WEEKS": 604800,
}
_TIMESERIES_RE = re.compile(
    r"\bTIMESERIES\s+(\d+)\s*(SECOND|SECONDS|MINUTE|MINUTES|HOUR|HOURS|DAY|DAYS|WEEK|WEEKS)\b",
    re.IGNORECASE,
)


def _keyword_positions(query: str) -> list[tuple[int, str]]:
    """Top-level NRQL clause keywords, ignoring strings and parentheses."""
    positions: list[tuple[int, str]] = []
    quote: str | None = None
    depth = 0
    i = 0
    n = len(query)
    while i < n:
        ch = query[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth == 0 and (ch.isalpha() or ch == "_"):
            if i > 0 and (query[i - 1].isalnum() or query[i - 1] == "_"):
                i += 1
                continue
            j = i
            while j < n and (query[j].isalnum() or query[j] == "_"):
                j += 1
            word = query[i:j].upper()
            if word in _CLAUSE_KEYWORDS:
                positions.append((i, word))
            i = j
            continue
        i += 1
    return positions


def _clause_end(query: str, start: int, positions: list[tuple[int, str]]) -> int:
    for pos, _word in positions:
        if pos > start:
            return pos
    return len(query)


def _remove_clauses(query: str, names: set[str]) -> str:
    """Remove top-level clauses in reverse order so indexes stay valid."""
    positions = _keyword_positions(query)
    text = query
    for pos, word in reversed(positions):
        if word not in names:
            continue
        end = _clause_end(query, pos, positions)
        prefix = text[:pos].rstrip()
        suffix = text[end:].lstrip()
        text = f"{prefix} {suffix}".strip()
    return text


def timeseries_seconds(nrql: str) -> int | None:
    """The fixed TIMESERIES width in the saved query, if it has one."""
    positions = _keyword_positions(nrql)
    for pos, word in positions:
        if word != "TIMESERIES":
            continue
        clause = nrql[pos : _clause_end(nrql, pos, positions)]
        match = _TIMESERIES_RE.search(clause)
        if match:
            return int(match.group(1)) * _UNIT_SECONDS[match.group(2).upper()]
        return None
    return None


def effective_nrql(nrql: str, *, start_epoch: int, end_epoch: int, bucket_seconds: int) -> str:
    """Pin the saved query to the selected window and a known bucket width."""
    cleaned = _remove_clauses(nrql.strip().rstrip(";"), {"SINCE", "UNTIL", "TIMESERIES"})
    window = f"SINCE {start_epoch * 1000} UNTIL {end_epoch * 1000}"

    # Canonical NRQL order places SINCE/UNTIL before WITH TIMEZONE and
    # COMPARE WITH; TIMESERIES comes after them.
    positions = _keyword_positions(cleaned)
    insert_before = next((pos for pos, word in positions if word in {"WITH", "COMPARE"}), None)
    if insert_before is None:
        query = f"{cleaned} {window}".strip()
    else:
        query = (
            f"{cleaned[:insert_before].rstrip()} {window} " f"{cleaned[insert_before:].lstrip()}"
        ).strip()
    return f"{query} TIMESERIES {bucket_seconds} seconds"


# ── result normalization ──────────────────────────────────────────────────────


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _parse_epoch(value: Any) -> float | None:
    """Epoch seconds from an NR timestamp, accepting ns/us/ms/s or ISO text."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        n = float(value)
        if abs(n) >= 10**17:  # nanoseconds
            return n / 1_000_000_000
        if abs(n) >= 10**14:  # microseconds
            return n / 1_000_000
        if abs(n) >= 10**11:  # milliseconds
            return n / 1_000
        return n
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return _parse_epoch(float(text))
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _row_bucket_start(row: dict[str, Any], fallback: int) -> float:
    for key in ("beginTimeMillis", "beginTime", "startTime", "timestamp"):
        if key in row:
            parsed = _parse_epoch(row[key])
            if parsed is not None:
                return parsed
    for key in ("endTimeMillis", "endTime"):
        if key in row:
            parsed = _parse_epoch(row[key])
            if parsed is not None:
                return parsed
    return float(fallback)


def choose_value_field(results: list[dict[str, Any]], requested: str | None) -> str:
    available: list[str] = []
    for row in results:
        for key, value in row.items():
            if key in _TIME_KEYS:
                continue
            if _as_number(value) is not None and key not in available:
                available.append(key)
    if requested:
        if results and requested not in available:
            raise NewRelicError(
                f"NRQL result has no numeric column {requested!r}; "
                f"available: {', '.join(available) or 'none'}"
            )
        return requested
    if not available:
        if not results:
            return "count"
        raise NewRelicError(
            "NRQL query returned no numeric column to compare — return an aggregate "
            "such as count(*), average(duration), sum(bytes), or set the numeric column"
        )
    if len(available) == 1:
        return available[0]
    raise NewRelicError(
        "NRQL query returned multiple numeric columns ("
        + ", ".join(available)
        + "); set the numeric column to compare"
    )


def _aggregate(values: list[float], mode: str) -> float:
    if not values:
        return 0.0
    if mode == "avg":
        return sum(values) / len(values)
    if mode == "max":
        return max(values)
    if mode == "min":
        return min(values)
    if mode == "last":
        return values[-1]
    return sum(values)


def normalize_nr_results(
    results: list[dict[str, Any]],
    *,
    start_epoch: int,
    end_epoch: int,
    bucket_seconds: int,
    value_field: str | None,
    mode: str,
) -> tuple[float | None, list[dict[str, int | float]], str]:
    """Reduce NR rows to one total and one time series.

    `mode` decides how multiple rows in the same bucket (FACET, or a custom
    aggregate) combine, and how the total is derived:
      sum  — counts; total = sum of every value
      avg  — gauges; total = mean of every value
      max/min — the extreme value
      last — the newest bucket's value
    """
    field = choose_value_field(results, value_field)
    if not results:
        return (0.0 if mode == "sum" else None), [], field

    points: dict[float, list[float]] = {}
    has_time = False
    last_value: tuple[float, float] | None = None

    for index, row in enumerate(results):
        raw = _as_number(row.get(field))
        if raw is None:
            continue
        bucket_start = _row_bucket_start(row, start_epoch)
        has_time = has_time or any(
            key in row
            for key in (
                "beginTimeMillis",
                "beginTime",
                "startTime",
                "timestamp",
                "endTimeMillis",
                "endTime",
            )
        )
        points.setdefault(bucket_start, []).append(raw)
        sort_key = bucket_start if has_time else float(index)
        if last_value is None or sort_key >= last_value[0]:
            last_value = (sort_key, raw)

    if not points:
        return (0.0 if mode == "sum" else None), [], field

    series = [
        {
            "start_epoch": int(start),
            "end_epoch": int(start + bucket_seconds),
            "value": _aggregate(values, mode),
        }
        for start, values in sorted(points.items())
    ]

    all_values = [value for values in points.values() for value in values]
    if mode == "sum":
        total = float(sum(all_values))
    elif mode == "avg":
        total = float(sum(all_values) / len(all_values))
    elif mode == "max":
        total = float(max(all_values))
    elif mode == "min":
        total = float(min(all_values))
    else:  # last
        total = float(last_value[1]) if last_value else None

    if not has_time:
        # A query without TIMESERIES has no bucket positions. Show a single
        # whole-window point instead of pretending every row is a bucket.
        series = [
            {
                "start_epoch": int(start_epoch),
                "end_epoch": int(end_epoch),
                "value": _aggregate(all_values, mode),
            }
        ]
    return total, series, field
