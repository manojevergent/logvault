"""Log formats library: named parse patterns a job tries against every row.

One regex per job only works when a job's rows share one shape. Registering a
format here makes every future job able to parse it, so adding a new log shape
is a row in this table rather than an edit to each search.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.aggregation import normalize_pattern
from app.database import get_db
from app.deps import get_current_user
from app.models import LogFormat, User
from app.schemas import LogFormatCreate, LogFormatOut, LogFormatTestRequest, LogFormatTestResult

router = APIRouter(prefix="/log-formats", tags=["log-formats"])


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
