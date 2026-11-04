"""Tests for the filter pipeline builder — the §2.5/§2.6 gotchas in particular."""

import pytest

from app.last9.constants import VALID_OPERATORS, physical_index
from app.last9.errors import PipelineError
from app.last9.pipeline import (
    build_filter_pipeline,
    build_filter_query,
    build_id_regex,
    build_pipeline,
)


def test_containswords_operator_does_not_exist():
    # §2.5 — guard against regressions: $containsWords must never be valid.
    assert "$containsWords" not in VALID_OPERATORS


def test_body_field_is_capital_b():
    q = build_filter_query(phrases=["GetEntitlements"])
    assert q == {"$and": [{"$contains": ["Body", "GetEntitlements"]}]}


def test_a_single_clause_is_still_wrapped_in_and():
    """§2.4 — a bare operator at the query root silently returns 0 rows.

    This asserted the bare form until the API proved otherwise in production.
    Do not "simplify" it back: the wrapper is the whole point, and dropping it
    fails silently with a believable empty result rather than an error.
    """
    q = build_filter_query(phrases=["only"])
    assert q == {"$and": [{"$contains": ["Body", "only"]}]}


def test_phrases_only_multiple_anded():
    q = build_filter_query(phrases=["a", "b"])
    assert q == {"$and": [{"$contains": ["Body", "a"]}, {"$contains": ["Body", "b"]}]}


def test_exact_phrase_is_an_adjacent_regex_not_contains():
    """$contains is word-based: "API : 502" as words also matched a stray 502 in
    a millisecond timestamp, returning 200s. An exact phrase must be adjacency."""
    q = build_filter_query(phrases=["getStatusCode"], exact_phrases=["API : 502"])
    assert q == {
        "$and": [
            {"$contains": ["Body", "getStatusCode"]},
            {"$regex": ["Body", "API\\s+:\\s+502"]},
        ]
    }


def test_exact_phrase_escapes_regex_metacharacters():
    q = build_filter_query(exact_phrases=["a.b (c)"])
    assert q == {"$and": [{"$regex": ["Body", "a\\.b\\s+\\(c\\)"]}]}


def test_exact_phrase_alone_is_enough():
    q = build_filter_query(exact_phrases=["API : 502"])
    assert q == {"$and": [{"$regex": ["Body", "API\\s+:\\s+502"]}]}


def test_ids_only_is_single_regex_not_or():
    # §2.6 — the #1 gotcha: many IDs => ONE $regex alternation, never $or.
    q = build_filter_query(ids=["ID-A", "ID-B", "ID-C"])
    assert q == {"$and": [{"$regex": ["Body", "ID-A|ID-B|ID-C"]}]}
    assert "$or" not in repr(q)


def test_both_phrases_and_ids():
    q = build_filter_query(phrases=["GetEntitlements"], ids=["ID-A", "ID-B"])
    assert q == {
        "$and": [
            {"$contains": ["Body", "GetEntitlements"]},
            {"$regex": ["Body", "ID-A|ID-B"]},
        ]
    }


def test_id_regex_escapes_but_keeps_hyphens():
    assert build_id_regex(["a.b", "ID-1"]) == r"a\.b|ID-1"


def test_empty_filter_raises():
    with pytest.raises(PipelineError):
        build_filter_query()


def test_build_id_regex_empty_raises():
    with pytest.raises(PipelineError):
        build_id_regex([])


def test_pipeline_is_a_list_with_query_then_type():
    # §2.4 — pipeline is always a list; stage key order is query then type.
    pipe = build_pipeline({"$contains": ["Body", "x"]})
    assert isinstance(pipe, list)
    assert len(pipe) == 1
    stage = pipe[0]
    assert list(stage.keys()) == ["query", "type"]
    assert stage["type"] == "filter"


def test_physical_index_prefixes_bare_name_and_passes_full_through():
    assert physical_index("UMServices") == "physical_index:UMServices"
    # Already-qualified strings are returned unchanged (§2.13).
    assert physical_index("physical_index:UMServices") == "physical_index:UMServices"
    assert physical_index("rehydration_index:Foo") == "rehydration_index:Foo"


def test_build_filter_pipeline_convenience():
    pipe = build_filter_pipeline(phrases=["p"], ids=["i1", "i2"])
    assert pipe == [
        {
            "query": {
                "$and": [
                    {"$contains": ["Body", "p"]},
                    {"$regex": ["Body", "i1|i2"]},
                ]
            },
            "type": "filter",
        }
    ]
