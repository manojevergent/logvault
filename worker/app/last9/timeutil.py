"""Time handling (§2.12).

The API takes UTC epoch **seconds**. Users think in IST (UTC+5:30, no DST — a
fixed offset, so no tz database is needed). Helpers convert a user-entered local
time to epoch and describe a resolved range in both zones for pre-run display.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), name="IST")

_ZONES = {"IST": IST, "UTC": UTC}


def to_epoch(dt: datetime) -> int:
    """Epoch seconds for a timezone-aware datetime."""
    if dt.tzinfo is None:
        raise ValueError("to_epoch requires a timezone-aware datetime")
    return int(dt.timestamp())


def local_to_epoch(dt_naive: datetime, tz_name: str = "IST") -> int:
    """Interpret a naive datetime as wall-clock time in ``tz_name`` -> epoch."""
    tz = _resolve(tz_name)
    if dt_naive.tzinfo is not None:
        raise ValueError("local_to_epoch expects a naive datetime")
    return int(dt_naive.replace(tzinfo=tz).timestamp())


def epoch_to_datetime(epoch: int, tz_name: str = "UTC") -> datetime:
    return datetime.fromtimestamp(epoch, _resolve(tz_name))


def format_epoch(epoch: int, tz_name: str = "UTC") -> str:
    return epoch_to_datetime(epoch, tz_name).strftime("%Y-%m-%d %H:%M:%S")


# Last9 returns a row's timestamp as an epoch integer whose unit varies by
# endpoint (nanoseconds, in practice). Written to CSV raw it reaches Excel as
# 1.78784E+18 — past the 2^53 mark where a float stops being exact, so it is not
# merely unreadable but lossy. Bounds are generous enough to stay right for
# decades either side of now while keeping the units unambiguous.
_UNIT_SCALES = ((10**17, 1_000_000_000), (10**14, 1_000_000), (10**11, 1_000), (0, 1))


def format_log_timestamp(value: str | int | None, tz_name: str = "UTC") -> str:
    """A Last9 row timestamp rendered as wall-clock text in ``tz_name``.

    Anything that isn't a bare integer (an ISO string, an empty value) is passed
    through untouched — better a timestamp we didn't recognize than one we
    mangled.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if not text.lstrip("-").isdigit():
        return text
    n = int(text)
    divisor = next(d for threshold, d in _UNIT_SCALES if abs(n) >= threshold)
    dt = datetime.fromtimestamp(n / divisor, _resolve(tz_name))
    # Matches Last9's own rendering, including the colon before milliseconds and
    # the literal zone suffix: 2026-11-12 10:38:12:632 UTC. `strftime` has no
    # millisecond directive, hence the manual tail.
    zone = tz_name.upper()
    return dt.strftime("%Y-%m-%d %H:%M:%S:") + f"{dt.microsecond // 1000:03d} {zone}"


def previous_calendar_day_window(now_epoch: int, tz_name: str = "UTC") -> tuple[int, int]:
    """The most recently completed full calendar day in ``tz_name`` as
    ``[start, end)`` UTC epoch seconds — e.g. a schedule wanting "00:00-23:59
    every day" runs against yesterday's full day, however late it actually fires.

    Defaults to UTC because the boundary has to match the zone the application
    writes its log timestamps in, which is UTC. Aligning to IST instead would
    make each run straddle two UTC days (18:30 to 18:30), so a query for
    "yesterday" would return the tail of one day and the head of another.
    """
    tz = _resolve(tz_name)
    local_now = datetime.fromtimestamp(now_epoch, tz)
    local_midnight_today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = local_midnight_today - timedelta(days=1)
    return to_epoch(start), to_epoch(local_midnight_today)


def describe_range(start_epoch: int, end_epoch: int) -> dict[str, str | int]:
    """Human-readable summary of a range in both IST and UTC (for the wizard)."""
    return {
        "start_utc": format_epoch(start_epoch, "UTC"),
        "end_utc": format_epoch(end_epoch, "UTC"),
        "start_ist": format_epoch(start_epoch, "IST"),
        "end_ist": format_epoch(end_epoch, "IST"),
        "duration_seconds": end_epoch - start_epoch,
    }


def _resolve(tz_name: str) -> timezone:
    try:
        return _ZONES[tz_name.upper()]
    except KeyError as exc:
        raise ValueError(f"unknown timezone {tz_name!r}; use IST or UTC") from exc
