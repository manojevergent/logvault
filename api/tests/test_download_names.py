"""Download filenames: a saved file should say which search made it and what
window it covers, without needing the job id to look anything up."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import Job
from app.routers.jobs import download_filename


def _epoch(y, mo, d, h=0, mi=0) -> int:
    return int(datetime(y, mo, d, h, mi, tzinfo=UTC).timestamp())


def _job(label="AHA_CGetEntitlements", start=None, end=None, fmt="csv") -> Job:
    return Job(
        id=16,
        start_epoch=start if start is not None else _epoch(2026, 8, 30),
        end_epoch=end if end is not None else _epoch(2026, 8, 31),
        filter_spec={"phrases": [], "ids": [], **({"label": label} if label else {})},
        output_format=fmt,
    )


def test_full_day_is_named_for_the_day_it_covers():
    # Half-open window: 30 Aug 00:00 -> 31 Aug 00:00 covers 30 Aug, and naming it
    # after the exclusive end would label the file with the wrong date.
    assert download_filename(_job()) == "AHA_CGetEntitlements_2026-08-30.csv.zip"


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("counts", "AHA_CGetEntitlements_2026-08-30_counts.csv.zip"),
        ("summary", "AHA_CGetEntitlements_2026-08-30_summary.csv.zip"),
    ],
)
def test_each_artifact_keeps_the_same_stem(kind, expected):
    assert download_filename(_job(), kind) == expected


def test_a_partial_day_carries_its_times():
    job = _job(start=_epoch(2026, 8, 31, 7, 5), end=_epoch(2026, 8, 31, 8, 5))
    assert download_filename(job) == "AHA_CGetEntitlements_2026-08-31_0705-0804.csv.zip"


def test_a_window_spanning_days_names_both_ends():
    job = _job(start=_epoch(2026, 8, 30, 9, 0), end=_epoch(2026, 8, 31, 9, 0))
    assert download_filename(job) == "AHA_CGetEntitlements_2026-08-30_0900-2026-08-31_0859.csv.zip"


def test_jsonl_keeps_its_extension():
    assert download_filename(_job(fmt="jsonl")).endswith(".jsonl.zip")


def test_a_job_with_no_saved_search_falls_back_to_its_id():
    assert download_filename(_job(label=None)) == "logvault_job_16_2026-08-30.csv.zip"


@pytest.mark.parametrize("label", ["AHA/CGet Entitlements", "AHA:CGet*Entitlements?"])
def test_characters_that_would_break_a_filename_are_replaced(label):
    name = download_filename(_job(label=label))
    assert name.startswith("AHA_CGet")
    assert not set(name) & set(r'/\:*?"<>|')


# ── compressed must match what's actually on disk ────────────────────────────
# A preview ("Test filter") run's raw output is written plain regardless of
# settings (worker/app/runner.py skips zipping it), and ZIP_EXPORTS=false
# writes every artifact plain. Naming a plain-text file *.zip is exactly what
# makes Windows (and every other zip reader) call the download corrupt — the
# bytes never were a zip.


def test_uncompressed_raw_output_has_no_zip_suffix():
    assert download_filename(_job(), compressed=False) == "AHA_CGetEntitlements_2026-08-30.csv"


def test_uncompressed_jsonl_has_no_zip_suffix():
    name = download_filename(_job(fmt="jsonl"), compressed=False)
    assert name.endswith(".jsonl")
    assert ".zip" not in name


@pytest.mark.parametrize("kind", ["summary", "counts"])
def test_uncompressed_summary_and_counts_have_no_zip_suffix(kind):
    name = download_filename(_job(), kind, compressed=False)
    assert name == f"AHA_CGetEntitlements_2026-08-30_{kind}.csv"
