"""Pure-function coverage for the two provider result shapes."""

from __future__ import annotations

import pytest

from app import newrelic
from app.last9_query import (
    build_filter_pipeline,
    extract_rows,
    extract_series,
    extract_total,
    infer_value_mode,
    pipelines_for_comparison,
)


def test_nrql_window_and_timeseries_are_replaced():
    query = "SELECT count(*) FROM Log FACET host " "SINCE 1 hour ago LIMIT 10 TIMESERIES 5 minutes"
    effective = newrelic.effective_nrql(
        query, start_epoch=1_700_000_000, end_epoch=1_700_003_600, bucket_seconds=300
    )
    assert effective.count("SINCE") == 1
    assert effective.count("UNTIL") == 1
    assert effective.count("TIMESERIES") == 1
    assert "SINCE 1700000000000 UNTIL 1700003600000" in effective
    assert "TIMESERIES 300 seconds" in effective
    assert effective.startswith("SELECT count(*) FROM Log FACET host LIMIT 10")


def test_nrql_timeseries_duration_is_parsed():
    assert newrelic.timeseries_seconds("SELECT count(*) FROM Log TIMESERIES 5 minutes") == 300
    assert newrelic.timeseries_seconds("SELECT count(*) FROM Log TIMESERIES 1 hour") == 3600
    assert newrelic.timeseries_seconds("SELECT count(*) FROM Log TIMESERIES AUTO") is None
    assert newrelic.timeseries_seconds("SELECT count(*) FROM Log") is None


def test_nrql_string_literals_are_not_treated_as_clauses():
    query = "SELECT count(*) FROM Log WHERE message = 'SINCE tomorrow'"
    effective = newrelic.effective_nrql(query, start_epoch=100, end_epoch=200, bucket_seconds=60)
    assert "message = 'SINCE tomorrow'" in effective
    assert "SINCE 100000 UNTIL 200000" in effective


def test_nr_results_sum_facets_and_buckets():
    start = 1_700_000_000
    total, series, field = newrelic.normalize_nr_results(
        [
            {"beginTime": start * 1000, "count": 3},
            {"beginTime": start * 1000, "count": 4},
            {"beginTime": (start + 60) * 1000, "count": 5},
        ],
        start_epoch=start,
        end_epoch=start + 120,
        bucket_seconds=60,
        value_field=None,
        mode="sum",
    )
    assert field == "count"
    assert total == 12
    assert series == [
        {"start_epoch": start, "end_epoch": start + 60, "value": 7},
        {"start_epoch": start + 60, "end_epoch": start + 120, "value": 5},
    ]


def test_nr_results_without_timeseries_make_one_whole_window_point():
    total, series, field = newrelic.normalize_nr_results(
        [{"count": 9}],
        start_epoch=100,
        end_epoch=200,
        bucket_seconds=50,
        value_field=None,
        mode="sum",
    )
    assert field == "count"
    assert total == 9
    assert series == [{"start_epoch": 100, "end_epoch": 200, "value": 9}]


def test_nr_multiple_numeric_columns_need_a_choice():
    with pytest.raises(newrelic.NewRelicError):
        newrelic.normalize_nr_results(
            [{"count": 1, "average.duration": 2.5}],
            start_epoch=0,
            end_epoch=60,
            bucket_seconds=60,
            value_field=None,
            mode="sum",
        )


def test_last9_filter_pipeline_escapes_ids_and_exact_phrases():
    pipeline = build_filter_pipeline(
        {
            "phrases": ["error"],
            "ids": ["123", "a.b"],
            "exact_phrases": ["API : 502"],
            "message_types": [],
        }
    )
    assert pipeline == [
        {
            "query": {
                "$and": [
                    {"$contains": ["Body", "error"]},
                    {"$regex": ["Body", "API\\s+:\\s+502"]},
                    {"$regex": ["Body", "123|a\\.b"]},
                ]
            },
            "type": "filter",
        }
    ]


def test_comparison_pipelines_append_count_stages():
    base = [{"type": "filter", "query": {"$and": [{"$contains": ["Body", "error"]}]}}]
    total, series = pipelines_for_comparison(base, 300)
    assert total is not None and series is not None
    assert total[-1]["type"] == "aggregate"
    assert series[-1] == {
        "type": "window_aggregate",
        "function": {"$count": []},
        "as": "last9_count",
        "window": ["300", "seconds"],
    }
    assert infer_value_mode(series) == "sum"


def test_last9_average_pipeline_keeps_average_semantics():
    pipeline = [
        {"type": "filter", "query": {"$and": [{"$neq": ["attributes['latency']", ""]}]}},
        {
            "type": "window_aggregate",
            "function": {"$avg": ["attributes['latency']"]},
            "as": "latency",
            "window": ["60", "seconds"],
        },
    ]
    assert infer_value_mode(pipeline) == "avg"
    rows = [
        {"metric": {"latency": 10, "__ts__": 1_700_000_000_000_000_000}, "values": []},
        {"metric": {"latency": 20, "__ts__": 1_700_000_000_000_000_000}, "values": []},
    ]
    assert extract_total(rows, preferred="latency", mode="avg") == 15
    assert extract_series(
        rows,
        bucket_seconds=60,
        start_epoch=1_700_000_000,
        end_epoch=1_700_000_060,
        preferred="latency",
        mode="avg",
    ) == [{"start_epoch": 1_700_000_000, "end_epoch": 1_700_000_060, "value": 15}]


def test_last9_series_accepts_nanoseconds_and_value_pairs():
    rows = [
        {"timestamp": 1_700_000_000_000_000_000, "last9_count": 5},
        {"values": [[1_700_000_060_000_000_000, "7"]]},
    ]
    series = extract_series(
        rows, bucket_seconds=60, start_epoch=1_700_000_000, end_epoch=1_700_000_120
    )
    assert series == [
        {"start_epoch": 1_700_000_000, "end_epoch": 1_700_000_060, "value": 5},
        {"start_epoch": 1_700_000_060, "end_epoch": 1_700_000_120, "value": 7},
    ]
    assert extract_total([{"count": 12}]) == 12


def test_last9_aggregate_metric_shape_is_understood():
    """The real aggregate API puts values and __ts__ inside `metric`."""
    rows = [
        {
            "metric": {"last9_count": 6, "__ts__": 1_700_000_000_000_000_000},
            "values": [],
        },
        {
            "metric": {"last9_count": "9", "__ts__": 1_700_000_060_000_000_000},
            "values": [],
        },
    ]
    assert extract_total(rows) == 15
    assert extract_series(
        rows, bucket_seconds=60, start_epoch=1_700_000_000, end_epoch=1_700_000_120
    ) == [
        {"start_epoch": 1_700_000_000, "end_epoch": 1_700_000_060, "value": 6},
        {"start_epoch": 1_700_000_060, "end_epoch": 1_700_000_120, "value": 9},
    ]


def test_last9_extract_rows_flattens_the_metric_wrapper():
    rows = extract_rows(
        {
            "data": {
                "resultType": "matrix",
                "result": [
                    {
                        "metric": {"last9_count": 6, "__ts__": "2023-11-14T22:13:20Z"},
                        "values": [],
                    }
                ],
            }
        }
    )
    assert rows == [{"last9_count": 6, "__ts__": "2023-11-14T22:13:20Z"}]
    assert extract_total(rows) == 6
    assert extract_series(
        rows, bucket_seconds=60, start_epoch=1_700_000_000, end_epoch=1_700_000_120
    ) == [{"start_epoch": 1_700_000_000, "end_epoch": 1_700_000_060, "value": 6}]
