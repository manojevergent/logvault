from datetime import datetime

import pytest

from app.last9.timeutil import (
    describe_range,
    epoch_to_datetime,
    format_log_timestamp,
    local_to_epoch,
    previous_calendar_day_window,
    to_epoch,
)


def test_ist_offset_is_five_thirty():
    # 2024-01-01 05:30:00 IST == 2024-01-01 00:00:00 UTC == epoch 1704067200
    epoch = local_to_epoch(datetime(2024, 1, 1, 5, 30, 0), "IST")
    assert epoch == 1704067200
    assert epoch_to_datetime(epoch, "UTC").hour == 0


def test_utc_local_to_epoch():
    assert local_to_epoch(datetime(2024, 1, 1, 0, 0, 0), "UTC") == 1704067200


def test_to_epoch_of_aware_datetime():
    assert to_epoch(epoch_to_datetime(1704067200, "UTC")) == 1704067200


def test_to_epoch_requires_aware_datetime():
    with pytest.raises(ValueError):
        to_epoch(datetime(2024, 1, 1))


def test_local_to_epoch_rejects_aware():
    aware = epoch_to_datetime(0, "UTC")
    with pytest.raises(ValueError):
        local_to_epoch(aware, "UTC")


def test_describe_range_shows_both_zones():
    start = 1704067200  # 2024-01-01 00:00 UTC
    desc = describe_range(start, start + 3600)
    assert desc["start_utc"] == "2024-01-01 00:00:00"
    assert desc["start_ist"] == "2024-01-01 05:30:00"
    assert desc["duration_seconds"] == 3600


def test_unknown_timezone_raises():
    with pytest.raises(ValueError):
        local_to_epoch(datetime(2024, 1, 1), "PST")


def test_calendar_day_window_defaults_to_utc_not_local():
    """The boundary has to match the zone the application timestamps its logs
    in. Defaulting to IST would make each run cover 18:30->18:30 UTC — the tail
    of one log day plus the head of the next."""
    fired_at = local_to_epoch(datetime(2026, 8, 31, 4, 0, 0), "UTC")
    assert previous_calendar_day_window(fired_at) == previous_calendar_day_window(fired_at, "UTC")


def test_calendar_day_window_is_a_full_utc_day_however_late_it_fires():
    """The exact requirement: on 31 Aug, pick 30 Aug 00:00:00 -> 23:59:59 UTC.
    The window is half-open, so it ends at the next midnight."""
    # A run firing at 02:47 UTC on 31 Aug must still cover all of 30 Aug.
    fired_at = local_to_epoch(datetime(2026, 8, 31, 2, 47, 13), "UTC")
    start, end = previous_calendar_day_window(fired_at, "UTC")

    assert epoch_to_datetime(start, "UTC").strftime("%Y-%m-%d %H:%M:%S") == "2026-08-30 00:00:00"
    assert epoch_to_datetime(end, "UTC").strftime("%Y-%m-%d %H:%M:%S") == "2026-08-31 00:00:00"
    assert end - start == 86400
    # The last instant actually included — the "23:59" users are shown.
    assert epoch_to_datetime(end - 1, "UTC").strftime("%Y-%m-%d %H:%M:%S") == "2026-08-30 23:59:59"


def test_calendar_day_window_is_stable_across_the_whole_day():
    """Every firing time within a day must select the same previous day, or a
    retried or delayed run would silently extract a different window."""
    base = datetime(2026, 8, 31)
    windows = {
        previous_calendar_day_window(local_to_epoch(base.replace(hour=h), "UTC"), "UTC")
        for h in range(24)
    }
    assert len(windows) == 1


def test_a_log_line_at_either_edge_of_the_day_falls_inside_the_window():
    """End-to-end on the contract that matters: a row timestamped 00:00:00.000
    and one timestamped 23:59:59.999 on 30 Aug both belong to the 30 Aug run."""
    fired_at = local_to_epoch(datetime(2026, 8, 31, 0, 5, 0), "UTC")
    start, end = previous_calendar_day_window(fired_at, "UTC")

    first_ns = local_to_epoch(datetime(2026, 8, 30, 0, 0, 0), "UTC") * 1_000_000_000
    last_ns = local_to_epoch(datetime(2026, 8, 30, 23, 59, 59), "UTC") * 1_000_000_000 + 999_000_000
    # Just outside on each side.
    before_ns = first_ns - 1_000_000
    after_ns = local_to_epoch(datetime(2026, 8, 31, 0, 0, 0), "UTC") * 1_000_000_000

    assert start <= first_ns // 1_000_000_000 < end
    assert start <= last_ns // 1_000_000_000 < end
    assert before_ns // 1_000_000_000 < start
    assert after_ns // 1_000_000_000 >= end

    assert format_log_timestamp(first_ns, "UTC") == "2026-08-30 00:00:00:000 UTC"
    assert format_log_timestamp(last_ns, "UTC") == "2026-08-30 23:59:59:999 UTC"


# 2024-01-01 00:00:00 UTC == 05:30:00 IST, expressed in each unit Last9 might use.
_MOMENT = {
    "seconds": 1704067200,
    "millis": 1704067200_000,
    "micros": 1704067200_000_000,
    "nanos": 1704067200_000_000_000,
}


@pytest.mark.parametrize("unit,value", sorted(_MOMENT.items()))
def test_log_timestamp_units_all_resolve_to_the_same_moment(unit, value):
    assert format_log_timestamp(value, "IST") == "2024-01-01 05:30:00:000 IST", unit


def test_log_timestamp_defaults_to_utc():
    """Exports carry UTC so the timestamp column can be checked directly against
    the job's window without a mental offset."""
    assert format_log_timestamp(1704067200) == "2024-01-01 00:00:00:000 UTC"


def test_log_timestamp_is_the_real_nanosecond_value_not_a_float(tmp_path):
    """1787840566975000000 exceeds 2^53, so anything that round-trips it through
    a float loses the sub-second digits — which is what Excel showed as
    1.78784E+18."""
    assert format_log_timestamp("1787840566975000000", "UTC").endswith(":975 UTC")


def test_log_timestamp_keeps_millisecond_precision():
    assert format_log_timestamp(1704067200_123, "UTC") == "2024-01-01 00:00:00:123 UTC"


def test_log_timestamp_passes_through_anything_not_an_integer():
    # Better an unrecognized timestamp than a mangled one.
    assert format_log_timestamp("2024-01-01T00:00:00Z") == "2024-01-01T00:00:00Z"
    assert format_log_timestamp("") == ""
    assert format_log_timestamp(None) == ""
