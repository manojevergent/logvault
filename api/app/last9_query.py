"""Last9 execution for comparisons.

The extraction worker streams raw rows for hours. A comparison is the opposite
shape: one cheap aggregate query for the total, and one windowed aggregate for
the chart. Both reuse the Logs Query API's JSON pipeline and the same encrypted
refresh-token credential the extraction jobs use.
"""

from __future__ import annotations

import copy
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from app import crypto
from app.config import get_settings
from app.last9_oauth import refresh_access_token
from app.models import Last9Credential

COUNT_ALIAS = "last9_count"
_ALLOWED_STAGES = {"filter", "parse", "aggregate", "window_aggregate"}
_TIME_KEYS = (
    "timestamp",
    "Timestamp",
    "ts",
    "time",
    "Time",
    "begin",
    "start",
    "start_time",
    "startTime",
    "window_start",
    "windowStart",
    "bucket",
    "from",
    "beginTime",
    "begin_time",
    "_timestamp",
    "__ts__",
    "__timestamp__",
)
_TOKEN_BUFFER_SECONDS = 300
_EXPIRED_MARKER = "Authorization token is expired"


class Last9QueryError(ValueError):
    """A user-actionable Last9 query failure."""


@dataclass
class Last9QueryResult:
    rows: list[dict[str, Any]]
    elapsed_ms: int


def access_token(db, cred: Last9Credential, *, force: bool = False) -> str:
    """A valid access token, refreshing and persisting it when needed."""
    if (
        not force
        and cred.encrypted_access_token
        and cred.access_token_expires_at
        and cred.access_token_expires_at > time.time() + _TOKEN_BUFFER_SECONDS
    ):
        return crypto.decrypt(cred.encrypted_access_token)

    result = refresh_access_token(crypto.decrypt(cred.encrypted_refresh_token))
    cred.encrypted_access_token = crypto.encrypt(result["access_token"])
    cred.access_token_expires_at = result["expires_at"]
    if result.get("refresh_token"):
        cred.encrypted_refresh_token = crypto.encrypt(result["refresh_token"])
        cred.refresh_token_last4 = result["refresh_token"][-4:]
    db.commit()
    return result["access_token"]


# ── pipeline construction ─────────────────────────────────────────────────────

_ESCAPE_RE = re.compile(r"([.^$*+?()\[\]{}|\\])")


def _esc(value: str) -> str:
    return _ESCAPE_RE.sub(r"\\\1", value)


def _exact_phrase_regex(phrase: str) -> str:
    tokens = [_esc(token) for token in phrase.split()]
    if not tokens:
        raise ValueError("an exact phrase cannot be empty")
    return r"\s+".join(tokens)


def build_filter_pipeline(spec: dict[str, Any] | Any) -> list[dict[str, Any]]:
    """The phrase/ID builder, mirroring worker/app/last9/pipeline.py."""
    data = spec.model_dump() if hasattr(spec, "model_dump") else dict(spec or {})
    phrases = [p for p in data.get("phrases", []) if str(p).strip()]
    message_types = [p for p in data.get("message_types", []) if str(p).strip()]
    exact_phrases = [p for p in data.get("exact_phrases", []) if str(p).strip()]
    exclude_phrases = [p for p in data.get("exclude_phrases", []) if str(p).strip()]
    exclude_exact_phrases = [
        p for p in data.get("exclude_exact_phrases", []) if str(p).strip()
    ]
    ids = [str(i) for i in data.get("ids", []) if str(i).strip()]

    clauses: list[dict[str, Any]] = [
        {"$contains": ["Body", phrase]} for phrase in [*phrases, *message_types]
    ]
    clauses += [{"$regex": ["Body", _exact_phrase_regex(p)]} for p in exact_phrases]
    if ids:
        clauses.append({"$regex": ["Body", "|".join(_esc(i) for i in ids)]})
    clauses += [{"$notcontains": ["Body", p]} for p in exclude_phrases]
    clauses += [{"$notregex": ["Body", _exact_phrase_regex(p)]} for p in exclude_exact_phrases]
    if not clauses:
        raise ValueError("a Last9 query needs at least one phrase, exact phrase or ID")
    return [{"query": {"$and": clauses}, "type": "filter"}]


def validate_pipeline(pipeline: Any) -> list[dict[str, Any]]:
    if not isinstance(pipeline, list) or not pipeline:
        raise ValueError("the Last9 pipeline must be a non-empty JSON array")
    for index, stage in enumerate(pipeline):
        if not isinstance(stage, dict):
            raise ValueError(f"pipeline stage {index + 1} must be a JSON object")
        stage_type = stage.get("type")
        if stage_type not in _ALLOWED_STAGES:
            raise ValueError(
                f"pipeline stage {index + 1} has type {stage_type!r}; "
                "use filter, parse, aggregate or window_aggregate"
            )
        if stage_type == "filter" and not isinstance(stage.get("query"), dict):
            raise ValueError(f"pipeline stage {index + 1} (filter) needs a query object")
        if stage_type == "aggregate" and not stage.get("aggregates"):
            raise ValueError(f"pipeline stage {index + 1} (aggregate) needs aggregates")
        if stage_type == "window_aggregate":
            for key in ("function", "as", "window"):
                if key not in stage:
                    raise ValueError(f"pipeline stage {index + 1} (window_aggregate) needs {key}")
    return copy.deepcopy(pipeline)


def infer_value_mode(pipeline: list[dict[str, Any]]) -> str:
    """How to combine multiple aggregate rows: the function the user chose.

    Generated count pipelines return sum. A hand-written pipeline using
    average/min/max/quantile keeps its meaning, so the comparison's total and
    duplicate-bucket folding use the same reduction instead of summing averages.
    """
    for stage in pipeline:
        functions: list[dict[str, Any]] = []
        if stage.get("type") == "aggregate":
            for aggregate in stage.get("aggregates", []) or []:
                if isinstance(aggregate, dict) and isinstance(aggregate.get("function"), dict):
                    functions.append(aggregate["function"])
        elif stage.get("type") == "window_aggregate":
            function = stage.get("function")
            if isinstance(function, dict):
                functions.append(function)
        for function in functions:
            if "$count" in function or "$sum" in function:
                return "sum"
            if "$avg" in function or "$quantile" in function or "$median" in function:
                return "avg"
            if "$min" in function:
                return "min"
            if "$max" in function:
                return "max"
    return "sum"


def aggregate_values(values: list[float], mode: str) -> float:
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


def pipelines_for_comparison(
    pipeline: list[dict[str, Any]], bucket_seconds: int
) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None]:
    """(total pipeline, series pipeline) for a saved base pipeline.

    A hand-written aggregate query is respected: an aggregate-only pipeline
    gives a total with no chart, a windowed aggregate gives a chart (and its
    total is reduced with the aggregate's own function). A filter/parse-only
    pipeline gets both stages appended automatically, which is the normal path.
    """
    base = copy.deepcopy(pipeline)
    kinds = {stage.get("type") for stage in base}
    if "window_aggregate" in kinds:
        return None, base
    if "aggregate" in kinds:
        return base, None

    total = [
        *copy.deepcopy(base),
        {
            "type": "aggregate",
            "aggregates": [{"function": {"$count": []}, "as": COUNT_ALIAS}],
        },
    ]
    series = [
        *copy.deepcopy(base),
        {
            "type": "window_aggregate",
            "function": {"$count": []},
            "as": COUNT_ALIAS,
            "window": [str(max(1, bucket_seconds)), "seconds"],
        },
    ]
    return total, series


# ── HTTP ─────────────────────────────────────────────────────────────────────


def query_last9(
    *,
    org_slug: str,
    token: str,
    refresh: Callable[[], str] | None,
    region: str,
    index: str,
    pipeline: list[dict[str, Any]],
    start_epoch: int,
    end_epoch: int,
    limit: int = 1000,
    timeout: float = 60.0,
) -> Last9QueryResult:
    settings = get_settings()
    url = f"{settings.last9_api_base.rstrip('/')}/organizations/{org_slug}/logs/api/v2/query_range/json"
    params: dict[str, Any] = {
        "start": start_epoch,
        "end": end_epoch,
        "limit": max(1, min(limit, 10000)),
        "direction": "backward",
        "region": region,
    }
    if index:
        params["index"] = index

    started = time.monotonic()
    current_token = token
    refreshed = False
    while True:
        try:
            resp = httpx.post(
                url,
                params=params,
                json={"pipeline": pipeline},
                headers={
                    "X-LAST9-API-TOKEN": f"Bearer {current_token}",
                    "Content-Type": "application/json",
                },
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            raise Last9QueryError(f"could not reach Last9: {exc}") from exc

        expired = _EXPIRED_MARKER.encode() in resp.content
        if (resp.status_code == 401 or expired) and refresh and not refreshed:
            current_token = refresh()
            refreshed = True
            continue

        if resp.status_code != 200:
            raise Last9QueryError(_status_message(resp))
        try:
            payload = resp.json()
        except ValueError:
            raise Last9QueryError("Last9 returned a non-JSON response") from None
        rows = extract_rows(payload)
        return Last9QueryResult(
            rows=rows,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )


def _error_detail(text: str) -> str:
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        for key in ("message", "error", "detail"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:300]
        if isinstance(parsed.get("error"), dict):
            message = parsed["error"].get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()[:300]
    return " ".join((text or "").split())[:300]


def _status_message(resp: httpx.Response) -> str:
    detail = _error_detail(resp.text)
    return f"Last9 returned HTTP {resp.status_code}" + (f": {detail}" if detail else "")


# ── response parsing ─────────────────────────────────────────────────────────


def extract_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        data = payload
    result = data.get("result")
    if isinstance(result, list):
        return [_flatten_row(row) for row in result if isinstance(row, dict)]
    if isinstance(result, dict):
        for key in ("series", "rows", "values", "data"):
            value = result.get(key)
            if isinstance(value, list):
                return [_flatten_row(row) for row in value if isinstance(row, dict)]
        return [_flatten_row(result)]
    return []


def _flatten_row(row: dict[str, Any]) -> dict[str, Any]:
    """Lift the provider's aggregate `metric` object to the row's top level.

    The Logs API returns `{"metric": {"last9_count": 12, "__ts__": "..."},
    "values": []}`. Keeping that wrapper makes the UI's raw-result table show
    two opaque columns. Flattening is lossless for the aggregate shape and
    leaves a Prometheus-style row alone.
    """
    metric = row.get("metric")
    if not isinstance(metric, dict):
        return row
    flat = dict(metric)
    for key, value in row.items():
        if key == "metric":
            continue
        if key == "values" and not value:
            continue
        flat.setdefault(key, value)
    return flat


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _parse_epoch(value: Any) -> float | None:
    """Last9 returns nanoseconds in row timestamps; accept any epoch unit."""
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


def _value_in_row(row: dict[str, Any], preferred: str = COUNT_ALIAS) -> float | None:
    value = _as_number(row.get(preferred))
    if value is not None:
        return value
    for key in ("count", "_count", "Count", "COUNT"):
        value = _as_number(row.get(key))
        if value is not None:
            return value
    for key, raw in row.items():
        if key in _TIME_KEYS:
            continue
        value = _as_number(raw)
        if value is not None:
            return value
    return None


def extract_total(
    rows: list[dict[str, Any]], preferred: str = COUNT_ALIAS, mode: str = "sum"
) -> float | None:
    values: list[float] = []
    for row in rows:
        # The Logs API's aggregate shape is
        #   {"metric": {"<alias>": 12, "group": "...", "__ts__": "..."}, "values": []}
        # The metric object holds the numeric aggregate; `values` is unused for
        # this API (it is the Prometheus instant-vector shape).
        metric = row.get("metric") if isinstance(row.get("metric"), dict) else row
        values_list = row.get("values")
        if isinstance(values_list, list) and values_list:
            for item in values_list:
                if isinstance(item, list | tuple) and len(item) >= 2:
                    value = _as_number(item[1])
                    if value is not None:
                        values.append(value)
                elif isinstance(item, dict):
                    value = _value_in_row(item, preferred)
                    if value is not None:
                        values.append(value)
            continue
        value = _value_in_row(metric, preferred)
        if value is not None:
            values.append(value)
    if values:
        return aggregate_values(values, mode)
    return 0.0 if not rows else None


def _row_time(row: dict[str, Any]) -> float | None:
    for key in _TIME_KEYS:
        if key in row:
            parsed = _parse_epoch(row[key])
            if parsed is not None:
                return parsed
    for key, raw in row.items():
        if "time" in key.lower():
            parsed = _parse_epoch(raw)
            if parsed is not None:
                return parsed
    return None


def extract_series(
    rows: list[dict[str, Any]],
    *,
    bucket_seconds: int,
    start_epoch: int,
    end_epoch: int,
    preferred: str = COUNT_ALIAS,
    mode: str = "sum",
) -> list[dict[str, int | float]]:
    points: list[tuple[float, float]] = []

    for row in rows:
        # Aggregate rows put the numeric value and the window timestamp inside
        # `metric`; `values` is the Prometheus instant-vector shape and is
        # empty here. Some other response shapes do put pairs in `values`, so
        # both are handled.
        metric = row.get("metric") if isinstance(row.get("metric"), dict) else row
        values_list = row.get("values")
        if isinstance(values_list, list) and values_list:
            for item in values_list:
                if isinstance(item, list | tuple) and len(item) >= 2:
                    ts = _parse_epoch(item[0])
                    value = _as_number(item[1])
                    if value is None and isinstance(item[1], dict):
                        value = _value_in_row(item[1], preferred)
                elif isinstance(item, dict):
                    ts = _row_time(item)
                    value = _value_in_row(item, preferred)
                else:
                    continue
                if ts is not None and value is not None:
                    points.append((ts, value))
            continue

        ts = _row_time(metric) or _row_time(row)
        value = _value_in_row(metric, preferred)
        if ts is not None and value is not None:
            points.append((ts, value))

    if not points and len(rows) == 1:
        metric = rows[0].get("metric") if isinstance(rows[0].get("metric"), dict) else rows[0]
        value = _value_in_row(metric, preferred)
        if value is not None:
            points.append((float(start_epoch), value))
    if not points:
        return []

    # `window_aggregate` normally emits one row per window. If a shape emits
    # duplicate window starts (group-by dimensions), combine them with the
    # same reduction the aggregate function uses.
    grouped: dict[int, list[float]] = {}
    for ts, value in points:
        start = int(ts)
        grouped.setdefault(start, []).append(float(value))

    return [
        {
            "start_epoch": start,
            "end_epoch": min(int(end_epoch), start + max(1, bucket_seconds)),
            "value": aggregate_values(values, mode),
        }
        for start, values in sorted(grouped.items())
    ]
