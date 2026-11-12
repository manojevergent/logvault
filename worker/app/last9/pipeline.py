"""Filter pipeline construction (§2.4–§2.7).

The Last9 query body is ``{"pipeline": [ {"query": <expr>, "type": "filter"} ]}``
where ``pipeline`` is ALWAYS a list (§2.4) and key order inside the stage is
``query`` then ``type``.

Filter semantics exposed to the UI (§2.7):

    (PHRASE_1 AND PHRASE_2 AND …)  AND  (ID_1 OR ID_2 OR …)

The OR-of-many-IDs is expressed as a SINGLE `$regex` with `|` alternation, never
as a `$or` of many `$contains` — the latter silently returns 0 rows (§2.6).
"""

from __future__ import annotations

from typing import Any

from .constants import BODY_FIELD
from .errors import PipelineError
from .escaping import esc


def contains_clause(phrase: str, field: str = BODY_FIELD) -> dict[str, list[str]]:
    """A required-phrase clause: ``{"$contains": ["Body", phrase]}``."""
    return {"$contains": [field, phrase]}


def regex_clause(pattern: str, field: str = BODY_FIELD) -> dict[str, list[str]]:
    """A regex clause: ``{"$regex": ["Body", pattern]}``."""
    return {"$regex": [field, pattern]}


def notcontains_clause(phrase: str, field: str = BODY_FIELD) -> dict[str, list[str]]:
    """An excluded-word clause: ``{"$notcontains": ["Body", phrase]}``."""
    return {"$notcontains": [field, phrase]}


def notregex_clause(pattern: str, field: str = BODY_FIELD) -> dict[str, list[str]]:
    """An excluded adjacent phrase: ``{"$notregex": ["Body", pattern]}``."""
    return {"$notregex": [field, pattern]}


def build_id_regex(ids: list[str]) -> str:
    """Join IDs into a single alternation pattern, each escaped (§2.6).

    This is the ONLY correct way to match "any of these IDs". Pass a single
    batch (~100 IDs) — see :func:`app.last9.batching.batch_ids`.
    """
    if not ids:
        raise PipelineError("build_id_regex requires at least one id")
    return "|".join(esc(i) for i in ids)


def exact_phrase_regex(phrase: str) -> str:
    """A literal phrase, tolerant of any run of whitespace between its tokens.

    `$contains` in Last9 is word-based, so a phrase like "API : 502" cannot be
    expressed with it: sent as words it also matches a line whose *timestamp*
    happens to contain "502". As a regex it means adjacency, which is what the
    person typing the phrase meant.
    """
    tokens = [esc(t) for t in phrase.split()]
    if not tokens:
        raise PipelineError("an exact phrase cannot be empty")
    return r"\s+".join(tokens)


def build_filter_query(
    phrases: list[str] | None = None,
    ids: list[str] | None = None,
    field: str = BODY_FIELD,
    exact_phrases: list[str] | None = None,
    exclude_phrases: list[str] | None = None,
    exclude_exact_phrases: list[str] | None = None,
) -> dict[str, Any]:
    """Build the ``query`` expression for one request.

    Always an `$and` of clauses, whatever the mode (§2.7):
    - phrases       -> one `$contains` per phrase (all must appear, any order).
    - exact_phrases -> one `$regex` per phrase (tokens must appear adjacent).
    - IDs only      -> `$and` of the single `$regex` alternation clause.
    - exclude_*     -> `$notcontains` / `$notregex` (all must be absent).
    - any mix       -> all of the above.

    Even a lone clause keeps the wrapper — see the note below; a bare operator at
    the query root returns 0 rows without erroring.

    ``ids`` here is a single already-chosen batch; batching happens upstream.
    """
    phrases = phrases or []
    ids = ids or []
    exact_phrases = exact_phrases or []
    exclude_phrases = exclude_phrases or []
    exclude_exact_phrases = exclude_exact_phrases or []
    if not phrases and not ids and not exact_phrases:
        raise PipelineError("a filter needs at least one phrase, exact phrase or id")

    clauses: list[dict[str, Any]] = [contains_clause(p, field) for p in phrases]
    clauses += [regex_clause(exact_phrase_regex(p), field) for p in exact_phrases]
    if ids:
        clauses.append(regex_clause(build_id_regex(ids), field))
    # Exclusions are ANDed with everything else: a row must contain none of
    # them. (NOT A AND NOT B == NOT (A OR B).)
    clauses += [notcontains_clause(p, field) for p in exclude_phrases]
    clauses += [notregex_clause(exact_phrase_regex(p), field) for p in exclude_exact_phrases]

    # Always wrap in $and — the API requires it even for a single clause.
    # A bare operator at the query root silently returns 0 rows (§2.4).
    return {"$and": clauses}


def build_pipeline(query: dict[str, Any]) -> list[dict[str, Any]]:
    """Wrap a query expression in the single-stage filter pipeline (§2.4).

    ``pipeline`` is always a list; stage key order is ``query`` then ``type``.
    """
    return [{"query": query, "type": "filter"}]


def build_filter_pipeline(
    phrases: list[str] | None = None,
    ids: list[str] | None = None,
    field: str = BODY_FIELD,
    exact_phrases: list[str] | None = None,
    exclude_phrases: list[str] | None = None,
    exclude_exact_phrases: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Convenience: build the full pipeline for one phrases/ids batch."""
    return build_pipeline(
        build_filter_query(
            phrases,
            ids,
            field,
            exact_phrases,
            exclude_phrases,
            exclude_exact_phrases,
        )
    )
