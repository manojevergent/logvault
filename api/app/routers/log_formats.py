"""Log formats library: named parse patterns a job tries against every row.

One regex per job only works when a job's rows share one shape. Registering a
format here makes every future job able to parse it, so adding a new log shape
is a row in this table rather than an edit to each search.
"""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.aggregation import MAX_PATTERN_LENGTH, check_pattern_cost, normalize_pattern
from app.database import get_db
from app.deps import get_current_user
from app.models import FilterTemplate, LogFormat, User
from app.schemas import (
    DetectedCandidate,
    DetectedField,
    InferredPattern,
    LogFormatCreate,
    LogFormatDetectRequest,
    LogFormatDetectResult,
    LogFormatOut,
    LogFormatTestRequest,
    LogFormatTestResult,
)

router = APIRouter(prefix="/log-formats", tags=["log-formats"])

# Bounded so a paste of an entire log file cannot turn one request into a
# regex sweep, and so the response stays readable.
MAX_DETECT_LINES = 200
MAX_LINE_CHARS = 8000


def _compile(regex: str) -> re.Pattern[str]:
    try:
        return re.compile(normalize_pattern(regex))
    except re.error as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"invalid regex: {exc}") from exc


def _validate(body: LogFormatCreate) -> re.Pattern[str]:
    compiled = _compile(body.regex)
    if not compiled.groupindex:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "the pattern defines no named groups — without them there are no fields to extract",
        )
    if body.hint and body.sample_line and body.hint not in body.sample_line:
        # The hint is a fast pre-filter: if it isn't in the line, the regex is
        # never run. A hint the sample lacks would silently match nothing.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"the match hint {body.hint!r} does not appear in the sample line, "
            "so this format would never be tried",
        )
    if body.sample_line and not compiled.search(body.sample_line):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "the pattern does not match the sample line",
        )
    return compiled


@router.get("", response_model=list[LogFormatOut])
def list_log_formats(db: Session = Depends(get_db)) -> list[LogFormat]:
    return list(db.scalars(select(LogFormat).order_by(LogFormat.priority, LogFormat.id)))


@router.post("", response_model=LogFormatOut, status_code=status.HTTP_201_CREATED)
def create_log_format(
    body: LogFormatCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LogFormat:
    _validate(body)
    fmt = LogFormat(
        name=body.name,
        regex=body.regex,
        hint=body.hint or None,
        sample_line=body.sample_line or None,
        priority=body.priority,
        enabled=body.enabled,
        description=body.description or None,
    )
    db.add(fmt)
    try:
        db.flush()
        audit.record(db, "create", "log_format", fmt.id, {"name": fmt.name}, user_id=user.email)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "a log format with this name already exists"
        ) from exc
    db.refresh(fmt)
    return fmt


@router.put("/{format_id}", response_model=LogFormatOut)
def update_log_format(
    format_id: int,
    body: LogFormatCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LogFormat:
    fmt = db.get(LogFormat, format_id)
    if fmt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "log format not found")
    _validate(body)
    fmt.name = body.name
    fmt.regex = body.regex
    fmt.hint = body.hint or None
    fmt.sample_line = body.sample_line or None
    fmt.priority = body.priority
    fmt.enabled = body.enabled
    fmt.description = body.description or None
    audit.record(db, "update", "log_format", fmt.id, {"name": fmt.name}, user_id=user.email)
    db.commit()
    db.refresh(fmt)
    return fmt


@router.delete("/{format_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_log_format(
    format_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    fmt = db.get(LogFormat, format_id)
    if fmt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "log format not found")
    db.delete(fmt)
    audit.record(db, "delete", "log_format", format_id, user_id=user.email)
    db.commit()


# --- auto-detect -------------------------------------------------------------

# A field seen on fewer than this share of the matched lines is reported but not
# suggested: counting on a column that is usually blank produces a confidently
# wrong number.
_SUGGEST_MIN_COVERAGE = 0.5
_MAX_SUGGESTIONS = 3


# Names/values that read as a per-event key rather than a dimension. Callers
# paste one line far more often than a hundred, and a single line carries no
# cardinality at all - the name and the value are the only signals left.
_IDENTIFIER_TOKENS = frozenset({"id", "uuid", "guid", "key", "token", "hash", "pk"})
_IDENTIFIER_PARTS = ("tracker", "request", "session", "trace", "correlation")
_DIGIT = re.compile(r"\d")


def _looks_like_identifier(name: str, sample: str) -> bool:
    """True for per-event keys such as trackerid, SPAccountId or request_id.

    CamelCase is split first, so SPAccountId ends in the token "id" while a plain
    English word such as "paid" or "valid" does not become a false positive.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    tokens = [token for token in re.split(r"[^a-z0-9]+", spaced.lower()) if token]
    if any(token in _IDENTIFIER_TOKENS for token in tokens):
        return True
    if any(part in name.lower() for part in _IDENTIFIER_PARTS):
        return True
    # Ids, timestamps and ports carry digits; dimensions ("INFO", "checkout",
    # "CGetAccount") do not.
    return bool(_DIGIT.search(sample))


def _distinct_suggestion(
    distinct: int, total: int, name: str = "", sample: str = ""
) -> Literal["group_by", "unique", "none"]:
    """Low cardinality groups; high cardinality gets counted.

    A value that never repeats (distinct == total) cannot group anything
    usefully, which matters most on small samples where a fixed threshold would
    call a repeated value unique. With a single line there is no cardinality to
    measure, so the field name and its value decide instead.
    """
    if total <= 0:
        return "none"
    if total == 1:
        return "unique" if _looks_like_identifier(name, sample) else "group_by"
    if distinct >= total:
        return "unique"
    if distinct <= max(2, total // 3):
        return "group_by"
    return "unique"


def _json_object(line: str) -> dict | None:
    import json

    text = line.strip()
    if not text.startswith("{"):
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _fields_from(values: list[dict[str, str]], *, sort: bool = True) -> list[DetectedField]:
    """Coverage, distinct count and a sample per field, across matched lines."""
    names: list[str] = []
    for row in values:
        for key in row:
            if key not in names:
                names.append(key)

    total = len(values)
    out: list[DetectedField] = []
    for name in names:
        seen = [row.get(name, "") for row in values]
        present = [v for v in seen if v != ""]
        distinct = len(set(present))
        sample = present[0][:120] if present else ""
        out.append(
            DetectedField(
                name=name,
                coverage=len(present),
                distinct=distinct,
                sample=sample,
                suggested=_distinct_suggestion(distinct, total, name, sample),
            )
        )
    # Most-covered first: the fields worth using are the ones that are always
    # there. An inferred pattern keeps its positional order instead, because
    # field1..fieldN read as noise once sorted alphabetically.
    if sort:
        out.sort(key=lambda f: (-f.coverage, f.name))
    return out


def _suggestions(fields: list[DetectedField], total: int) -> tuple[list[str], list[str]]:
    floor = max(1, int(total * _SUGGEST_MIN_COVERAGE))
    usable = [f for f in fields if f.coverage >= floor]
    group_by = [f.name for f in usable if f.suggested == "group_by"][:_MAX_SUGGESTIONS]
    unique = [f.name for f in usable if f.suggested == "unique"][:_MAX_SUGGESTIONS]
    if not unique:
        # The aggregation needs at least one field to count, and it must not also
        # be a grouping key - so promote a field out of group_by rather than
        # handing back the same name in both boxes.
        remaining = [f.name for f in usable if f.name not in group_by]
        if remaining:
            unique = remaining[-1:]
        elif group_by:
            unique = [group_by.pop()]
        else:
            unique = [f.name for f in fields[:1]]
    return group_by, unique


# --- inference for shapes nothing saved covers -------------------------------

# key=value tokens: the shape logfmt and most structured application logs use.
_KV_TOKEN = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*)=(.+)$")
MAX_INFER_TOKENS = 80


def _group_name(raw: str, used: set[str]) -> str:
    """A valid, unique regex group name from a label or a placeholder."""
    name = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_").lower()
    if not name or not name[0].isalpha():
        name = f"field_{name}" if name else "field"
    base = name
    index = 2
    while name in used:
        name = f"{base}_{index}"
        index += 1
    used.add(name)
    return name


def _kv_pairs(line: str) -> list[tuple[str, str]] | None:
    """Every token is key=value with unique keys, or None."""
    pairs: list[tuple[str, str]] = []
    for token in line.split():
        match = _KV_TOKEN.match(token)
        if match is None:
            return None
        pairs.append((match.group(1), match.group(2)))
    if len(pairs) < 2:
        return None
    keys = [key for key, _ in pairs]
    return pairs if len(set(keys)) == len(keys) else None


def _infer_key_values(lines: list[str]) -> str | None:
    """logfmt-style lines: the labels stay literal, only the values vary."""
    parsed = [_kv_pairs(line) for line in lines]
    if any(pairs is None for pairs in parsed):
        return None
    first = parsed[0]
    assert first is not None  # the any() above returned False
    keys = [key for key, _ in first]
    if any(pairs is None or [key for key, _ in pairs] != keys for pairs in parsed):
        return None
    used: set[str] = set()
    return r"\s+".join(f"{re.escape(key)}=(?<{_group_name(key, used)}>\\S+)" for key in keys)


def _infer_positional(lines: list[str]) -> str | None:
    """Token-aligned lines: tokens that never change are literals, the rest groups."""
    tokenized = [line.split() for line in lines]
    widths = {len(tokens) for tokens in tokenized}
    if len(widths) != 1:
        return None
    width = widths.pop()
    if width == 0 or width > MAX_INFER_TOKENS:
        return None

    used: set[str] = set()
    parts: list[str] = []
    anchored = False
    field_index = 0
    for column_index in range(width):
        column = [tokens[column_index] for tokens in tokenized]
        pairs = [_KV_TOKEN.match(token) for token in column]
        keys = {match.group(1) for match in pairs if match is not None}
        if all(match is not None for match in pairs) and len(keys) == 1:
            # A key=value column keeps its label and varies only in the value.
            key = keys.pop()
            parts.append(f"{re.escape(key)}=(?<{_group_name(key, used)}>\\S+)")
            anchored = True
        elif len(set(column)) == 1:
            parts.append(re.escape(column[0]))
            anchored = True
        else:
            field_index += 1
            parts.append(f"(?<{_group_name(f'field{field_index}', used)}>\\S+)")

    # All-variable columns share no structure: bare \S+ groups would match
    # anything and extract nothing worth counting.
    if not anchored:
        return None
    return r"\s+".join(parts)


def _infer(lines: list[str]) -> tuple[InferredPattern | None, str | None]:
    """Build a candidate pattern from the pasted lines, or explain why not."""
    if any(_json_object(line) is not None for line in lines):
        return None, None

    too_long = False
    for regex in (_infer_key_values(lines), _infer_positional(lines)):
        if regex is None:
            continue
        # A pattern that the create endpoint would reject is not worth offering:
        # the Save button would 422 after the operator typed a name.
        if len(regex) > MAX_PATTERN_LENGTH:
            too_long = True
            continue
        try:
            check_pattern_cost(regex)
        except ValueError:
            continue
        try:
            pattern = re.compile(normalize_pattern(regex))
        except re.error:
            continue
        if not pattern.groupindex:
            continue
        matches = [pattern.search(line) for line in lines]
        if any(match is None for match in matches):
            continue
        rows = [
            {key: (value or "") for key, value in match.groupdict().items()}
            for match in matches
            if match is not None
        ]
        fields = _fields_from(rows, sort=False)
        group_by, unique = _suggestions(fields, len(rows))
        return (
            InferredPattern(
                regex=regex,
                fields=fields,
                suggested_group_by=group_by,
                suggested_unique=unique,
                lines_used=len(rows),
            ),
            None,
        )

    if too_long:
        note = (
            "These lines have too many varying parts to build a compact pattern. "
            "Write the regex by hand, or paste fewer fields."
        )
    elif len(lines) < 2:
        note = (
            "Paste 2-3 lines of the same shape (or key=value lines) and Detect again, "
            "so the stable text and the varying parts can be told apart."
        )
    elif len({len(line.split()) for line in lines}) != 1:
        note = (
            "These lines do not split into the same number of fields, so no stable "
            "pattern can be inferred. Paste 2-3 lines of one shape."
        )
    else:
        note = (
            "These lines share no stable text, so no pattern can be inferred. Paste "
            "2-3 lines from the same log format."
        )
    return None, note


@router.post("/detect", response_model=LogFormatDetectResult)
def detect_formats(
    body: LogFormatDetectRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> LogFormatDetectResult:
    """Match pasted lines against every saved pattern and propose fields.

    "Saved" means both sources that already exist in the platform:
      * the Log Formats library - the patterns extraction actually tries, and
      * each saved search's parse pattern, which is otherwise locked inside that
        search and cannot be reused by a different one.

    The response carries per-field coverage so the UI can pre-fill the
    group-by and unique-count boxes instead of asking someone to retype names.
    """
    lines = [line[:MAX_LINE_CHARS] for line in (body.lines or []) if line.strip()]
    lines = lines[:MAX_DETECT_LINES]
    if not lines:
        return LogFormatDetectResult(
            lines_analyzed=0,
            matched=0,
            unmatched=0,
            candidates=[],
            message="Paste at least one log line to detect a pattern.",
        )

    # Candidate patterns, in the order the extractor would try them: library by
    # priority, then saved searches (a search pattern is a fallback, not part of
    # the library).
    candidates: list[dict] = []
    for fmt in db.scalars(
        select(LogFormat).where(LogFormat.enabled).order_by(LogFormat.priority, LogFormat.id)
    ):
        candidates.append(
            {
                "source": "library",
                "id": fmt.id,
                "name": fmt.name,
                "regex": fmt.regex,
                "hint": fmt.hint,
                "priority": fmt.priority,
            }
        )
    for tpl in db.scalars(select(FilterTemplate).order_by(FilterTemplate.name)):
        agg = tpl.aggregation or {}
        if not agg.get("enabled") or agg.get("use_library") or not agg.get("regex"):
            continue
        candidates.append(
            {
                "source": "saved_search",
                "id": tpl.id,
                "name": tpl.name,
                "regex": agg["regex"],
                "hint": None,
                "priority": 1000,
            }
        )

    # One compiled pattern per distinct regex. A saved search normally embeds a
    # copy of a library pattern; reporting it twice would just be noise.
    compiled: list[tuple[dict, re.Pattern[str]]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = normalize_pattern(candidate["regex"]).strip()
        if key in seen:
            continue
        try:
            pattern = re.compile(key)
        except re.error:
            continue
        if not pattern.groupindex:
            continue
        seen.add(key)
        compiled.append((candidate, pattern))

    per_candidate: dict[int, list[dict[str, str]]] = {i: [] for i in range(len(compiled))}
    matched_lines = 0
    json_rows: list[dict[str, str]] = []

    for line in lines:
        hit_index: int | None = None
        for index, (candidate, pattern) in enumerate(compiled):
            hint = candidate["hint"]
            if hint and hint not in line:
                continue
            m = pattern.search(line)
            if m is None:
                continue
            hit_index = index
            per_candidate[index].append({k: (v or "") for k, v in m.groupdict().items()})
            break

        if hit_index is not None:
            matched_lines += 1

        parsed = _json_object(line)
        if parsed is not None:
            json_rows.append(
                {
                    k: (v if isinstance(v, str) else str(v))
                    for k, v in parsed.items()
                    if isinstance(v, str | int | float | bool)
                }
            )

    detected: list[DetectedCandidate] = []
    for index, (candidate, _pattern) in enumerate(compiled):
        rows = per_candidate[index]
        if not rows:
            continue
        fields = _fields_from(rows)
        group_by, unique = _suggestions(fields, len(rows))
        detected.append(
            DetectedCandidate(
                source=candidate["source"],
                id=candidate["id"],
                name=candidate["name"],
                regex=candidate["regex"],
                hint=candidate["hint"],
                priority=candidate["priority"],
                matched=len(rows),
                fields=fields,
                suggested_group_by=group_by,
                suggested_unique=unique,
            )
        )
    detected.sort(key=lambda c: (-c.matched, c.priority, c.name))

    json_fields = _fields_from(json_rows)[:20] if json_rows else []

    # Nothing saved fits and the lines are not JSON: build a pattern from the
    # lines themselves rather than sending the operator off to write one.
    inferred: InferredPattern | None = None
    infer_note: str | None = None
    if not detected and not json_fields:
        inferred, infer_note = _infer(lines)

    message = None
    if not detected and json_fields:
        message = (
            "No saved pattern matches these lines, but they are JSON - these are its keys. "
            "Save a Log Format for this shape to reuse it across searches."
        )
    elif not detected and inferred is not None:
        message = (
            "No saved pattern matches these lines, so this pattern was inferred from them. "
            "Review it, then save it as a Log Format to reuse it across searches."
        )
    elif not detected:
        message = infer_note or (
            "No saved pattern matches these lines. Add a Log Format for this shape, or write "
            "the regex by hand below."
        )

    return LogFormatDetectResult(
        lines_analyzed=len(lines),
        matched=matched_lines,
        unmatched=len(lines) - matched_lines,
        candidates=detected,
        json_fields=json_fields,
        inferred=inferred,
        message=message,
    )


@router.post("/test", response_model=LogFormatTestResult)
def test_log_format(body: LogFormatTestRequest) -> LogFormatTestResult:
    """Try a pattern against a line without saving it — the fast way to build one."""
    try:
        compiled = re.compile(normalize_pattern(body.regex))
    except re.error as exc:
        return LogFormatTestResult(matched=False, error=f"invalid regex: {exc}", fields={})
    # Hint first, exactly as the matcher does it: when the hint is absent the
    # regex is never run, so reporting a match here would be a lie about what
    # happens at extraction time.
    if body.hint and body.hint not in body.sample_line:
        return LogFormatTestResult(
            matched=False,
            error=f"the hint {body.hint!r} is not in this line, so the format would be skipped",
            fields={},
        )
    m = compiled.search(body.sample_line)
    if m is None:
        return LogFormatTestResult(
            matched=False, error="the pattern does not match this line", fields={}
        )
    return LogFormatTestResult(
        matched=True,
        error=None,
        fields={k: (v or "") for k, v in m.groupdict().items()},
    )
