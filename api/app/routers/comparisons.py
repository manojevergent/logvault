"""Saved Last9 vs New Relic comparisons and inline run execution.

A run is synchronous: both sides are aggregate queries, not multi-hour
extractions. The API fires New Relic and the Last9 total/series queries in
parallel, normalizes each provider's rows into the same total + point shape,
snapshots the result, and returns it. The saved comparison is never mutated by
a run.
"""

from __future__ import annotations

import math
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import audit, crypto, newrelic
from app.config import get_settings
from app.database import SessionLocal, get_db
from app.deps import get_current_user
from app.last9_query import (
    Last9QueryError,
    access_token,
    aggregate_values,
    build_filter_pipeline,
    extract_series,
    extract_total,
    infer_value_mode,
    pipelines_for_comparison,
    query_last9,
    validate_pipeline,
)
from app.models import (
    Comparison,
    ComparisonRun,
    IndexTarget,
    Last9Credential,
    NewRelicCredential,
    User,
)
from app.schemas import (
    ComparisonCreate,
    ComparisonListOut,
    ComparisonOut,
    ComparisonPoint,
    ComparisonRunOut,
    ComparisonRunRequest,
    ComparisonRunSummary,
    ComparisonSideResult,
    ComparisonSummaryOut,
)

router = APIRouter(prefix="/comparisons", tags=["comparisons"])

_MAX_RAW_ROWS = 200
_MAX_BUCKETS = 500


def _auto_bucket(window_seconds: int) -> int:
    """The smallest bucket that keeps a chart at or under ~60 points."""
    for candidate in (60, 300, 900, 1800, 3600, 10800, 21600, 43200, 86400, 604800):
        if math.ceil(window_seconds / candidate) <= 60:
            return max(1, min(candidate, window_seconds))
    return max(1, math.ceil(window_seconds / 60))


def _bucket_seconds(comp: Comparison, requested: int | None, window: int) -> int:
    parsed = newrelic.timeseries_seconds(comp.nrql)
    bucket = requested or comp.bucket_seconds or parsed or _auto_bucket(window)
    bucket = max(1, min(int(bucket), window))
    if math.ceil(window / bucket) > _MAX_BUCKETS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"a {bucket}s bucket would return {math.ceil(window / bucket)} points "
            f"(max {_MAX_BUCKETS}); use a bucket of at least {math.ceil(window / _MAX_BUCKETS)}s",
        )
    return bucket


def _source(db: Session, body: ComparisonCreate) -> tuple[IndexTarget, Last9Credential, int]:
    idx = db.get(IndexTarget, body.last9_index_target_id)
    if idx is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Last9 index no longer exists")
    credential_id = idx.credential_id or body.last9_credential_id
    if credential_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "this Last9 index has no credential — set one on the index or pick one",
        )
    cred = db.get(Last9Credential, credential_id)
    if cred is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Last9 credential no longer exists"
        )
    return idx, cred, credential_id


def _pipeline(body: ComparisonCreate) -> tuple[list[dict], dict | None]:
    spec = body.last9_filter_spec.model_dump() if body.last9_filter_spec else None
    if body.last9_pipeline is not None:
        return validate_pipeline(body.last9_pipeline), spec
    if spec is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "provide a Last9 filter or a JSON pipeline",
        )
    try:
        return build_filter_pipeline(spec), spec
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


def _validate_create(
    db: Session, body: ComparisonCreate
) -> tuple[IndexTarget, int, list[dict], dict | None, NewRelicCredential]:
    if not body.name.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "comparison name is required")
    if not body.nrql.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "NRQL query is required")
    if "from" not in body.nrql.lower():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "NRQL must include a FROM clause (e.g. SELECT count(*) FROM Log)",
        )
    idx, _cred, credential_id = _source(db, body)
    pipeline, spec = _pipeline(body)
    nr_cred = db.get(NewRelicCredential, body.nr_credential_id)
    if nr_cred is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "New Relic connection no longer exists"
        )
    return idx, credential_id, pipeline, spec, nr_cred


def _latest_runs(db: Session, comparison_ids: list[int]) -> dict[int, dict]:
    if not comparison_ids:
        return {}
    newest = (
        select(ComparisonRun.comparison_id, func.max(ComparisonRun.id).label("id"))
        .where(ComparisonRun.comparison_id.in_(comparison_ids))
        .group_by(ComparisonRun.comparison_id)
        .subquery()
    )
    # Columns only: the latest run's raw/series JSON is not needed for a list
    # badge, and can be hundreds of rows per comparison.
    rows = (
        db.execute(
            select(
                ComparisonRun.comparison_id,
                ComparisonRun.id,
                ComparisonRun.status,
                ComparisonRun.last9_total,
                ComparisonRun.newrelic_total,
                ComparisonRun.created_at,
            ).where(ComparisonRun.id.in_(select(newest.c.id)))
        )
        .mappings()
        .all()
    )
    return {row["comparison_id"]: dict(row) for row in rows}


def _to_out(
    comp: Comparison,
    *,
    index_name: str | None,
    cred_label: str | None,
    nr_label: str | None,
    nr_account_id: int | None,
    latest: dict | None,
) -> ComparisonOut:
    return ComparisonOut(
        id=comp.id,
        name=comp.name,
        description=comp.description,
        last9_credential_id=comp.last9_credential_id,
        last9_index_target_id=comp.last9_index_target_id,
        last9_region_code=comp.last9_region_code,
        last9_pipeline=comp.last9_pipeline or [],
        last9_filter_spec=comp.last9_filter_spec,
        nr_credential_id=comp.nr_credential_id,
        nrql=comp.nrql,
        nr_value_mode=comp.nr_value_mode,
        nr_value_field=comp.nr_value_field,
        bucket_seconds=comp.bucket_seconds,
        created_by=comp.created_by,
        created_at=comp.created_at,
        updated_at=comp.updated_at,
        last9_credential_label=cred_label,
        last9_index_name=index_name,
        nr_credential_label=nr_label,
        nr_account_id=nr_account_id,
        last_run_at=latest["created_at"] if latest else None,
        last_run_id=latest["id"] if latest else None,
        last_run_status=latest["status"] if latest else None,
        last_run_last9_total=latest["last9_total"] if latest else None,
        last_run_newrelic_total=latest["newrelic_total"] if latest else None,
    )


def _summary(run: ComparisonRun) -> ComparisonRunSummary:
    return ComparisonRunSummary(
        id=run.id,
        comparison_id=run.comparison_id,
        start_epoch=run.start_epoch,
        end_epoch=run.end_epoch,
        bucket_seconds=run.bucket_seconds,
        status=run.status,
        last9_ok=run.last9_ok,
        last9_total=run.last9_total,
        newrelic_ok=run.newrelic_ok,
        newrelic_total=run.newrelic_total,
        created_by=run.created_by,
        created_at=run.created_at,
    )


def _side(
    *,
    ok: bool,
    error: str | None,
    elapsed_ms: int | None,
    total: float | None,
    series: list[dict] | None,
    raw: list[dict] | None,
    metadata: dict | None = None,
) -> ComparisonSideResult:
    return ComparisonSideResult(
        ok=ok,
        error=error,
        elapsed_ms=elapsed_ms,
        total=total,
        series=[
            ComparisonPoint(
                start_epoch=int(point["start_epoch"]),
                end_epoch=int(point["end_epoch"]),
                value=float(point["value"]),
            )
            for point in (series or [])
        ],
        raw=(raw or [])[:_MAX_RAW_ROWS],
        metadata=metadata,
    )


def _run_out(run: ComparisonRun) -> ComparisonRunOut:
    delta = None
    pct_diff = None
    if run.last9_total is not None and run.newrelic_total is not None:
        delta = run.last9_total - run.newrelic_total
        if run.newrelic_total != 0:
            pct_diff = (delta / run.newrelic_total) * 100
        elif run.last9_total == 0:
            pct_diff = 0.0
    return ComparisonRunOut(
        **_summary(run).model_dump(),
        last9=_side(
            ok=run.last9_ok,
            error=run.last9_error,
            elapsed_ms=run.last9_elapsed_ms,
            total=run.last9_total,
            series=run.last9_series,
            raw=run.last9_raw,
        ),
        newrelic=_side(
            ok=run.newrelic_ok,
            error=run.newrelic_error,
            elapsed_ms=run.newrelic_elapsed_ms,
            total=run.newrelic_total,
            series=run.newrelic_series,
            raw=run.newrelic_raw,
            metadata=run.newrelic_metadata,
        ),
        nrql_effective=run.nrql_effective,
        last9_pipeline_effective=run.last9_pipeline_effective,
        delta=delta,
        pct_diff=pct_diff,
    )


def _get_or_404(db: Session, comparison_id: int) -> Comparison:
    comp = db.get(Comparison, comparison_id)
    if comp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "comparison not found")
    return comp


def _to_summary(
    row,
    *,
    index_name: str | None,
    cred_label: str | None,
    nr_label: str | None,
    nr_account_id: int | None,
    latest: dict | None,
) -> ComparisonSummaryOut:
    return ComparisonSummaryOut(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        last9_credential_id=row["last9_credential_id"],
        last9_index_target_id=row["last9_index_target_id"],
        last9_region_code=row["last9_region_code"],
        nr_credential_id=row["nr_credential_id"],
        nr_value_mode=row["nr_value_mode"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last9_credential_label=cred_label,
        last9_index_name=index_name,
        nr_credential_label=nr_label,
        nr_account_id=nr_account_id,
        last_run_at=latest["created_at"] if latest else None,
        last_run_id=latest["id"] if latest else None,
        last_run_status=latest["status"] if latest else None,
        last_run_last9_total=latest["last9_total"] if latest else None,
        last_run_newrelic_total=latest["newrelic_total"] if latest else None,
    )


@router.get("", response_model=ComparisonListOut)
def list_comparisons(
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> ComparisonListOut:
    filters = []
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        filters.append(or_(Comparison.name.ilike(pattern), Comparison.description.ilike(pattern)))

    total = int(db.scalar(select(func.count(Comparison.id)).where(*filters)) or 0)
    rows = (
        db.execute(
            select(
                Comparison.id,
                Comparison.name,
                Comparison.description,
                Comparison.last9_credential_id,
                Comparison.last9_index_target_id,
                Comparison.last9_region_code,
                Comparison.nr_credential_id,
                Comparison.nr_value_mode,
                Comparison.created_by,
                Comparison.created_at,
                Comparison.updated_at,
            )
            .where(*filters)
            .order_by(Comparison.created_at.desc(), Comparison.id.desc())
            .limit(limit)
            .offset(offset)
        )
        .mappings()
        .all()
    )
    if not rows:
        return ComparisonListOut(items=[], total=total, limit=limit, offset=offset)

    ids = [row["id"] for row in rows]
    latest = _latest_runs(db, ids)
    index_ids = {row["last9_index_target_id"] for row in rows}
    cred_ids = {row["last9_credential_id"] for row in rows}
    nr_ids = {row["nr_credential_id"] for row in rows}

    indexes = dict(
        db.execute(
            select(IndexTarget.id, IndexTarget.name).where(IndexTarget.id.in_(index_ids))
        ).all()
    )
    cred_labels = dict(
        db.execute(
            select(Last9Credential.id, Last9Credential.label).where(
                Last9Credential.id.in_(cred_ids)
            )
        ).all()
    )
    nr_rows = db.execute(
        select(
            NewRelicCredential.id, NewRelicCredential.label, NewRelicCredential.account_id
        ).where(NewRelicCredential.id.in_(nr_ids))
    ).all()
    nr_labels = {row[0]: (row[1], row[2]) for row in nr_rows}

    items = [
        _to_summary(
            row,
            index_name=indexes.get(row["last9_index_target_id"]),
            cred_label=cred_labels.get(row["last9_credential_id"]),
            nr_label=nr_labels.get(row["nr_credential_id"], (None, None))[0],
            nr_account_id=nr_labels.get(row["nr_credential_id"], (None, None))[1],
            latest=latest.get(row["id"]),
        )
        for row in rows
    ]
    return ComparisonListOut(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=ComparisonOut, status_code=status.HTTP_201_CREATED)
def create_comparison(
    body: ComparisonCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ComparisonOut:
    idx, credential_id, pipeline, spec, nr_cred = _validate_create(db, body)
    comp = Comparison(
        name=body.name.strip(),
        description=body.description.strip() or None,
        last9_credential_id=credential_id,
        last9_index_target_id=idx.id,
        last9_region_code=idx.region_code,
        last9_pipeline=pipeline,
        last9_filter_spec=spec,
        nr_credential_id=nr_cred.id,
        nrql=body.nrql.strip(),
        nr_value_mode=body.nr_value_mode,
        nr_value_field=body.nr_value_field.strip() if body.nr_value_field else None,
        bucket_seconds=body.bucket_seconds,
        created_by=user.email,
    )
    db.add(comp)
    db.flush()
    audit.record(db, "create", "comparison", comp.id, {"name": comp.name}, user_id=user.email)
    db.commit()
    db.refresh(comp)
    return _to_out(
        comp,
        index_name=idx.name,
        cred_label=db.get(Last9Credential, credential_id).label,
        nr_label=nr_cred.label,
        nr_account_id=nr_cred.account_id,
        latest=None,
    )


@router.get("/{comparison_id}", response_model=ComparisonOut)
def get_comparison(comparison_id: int, db: Session = Depends(get_db)) -> ComparisonOut:
    comp = _get_or_404(db, comparison_id)
    idx = db.get(IndexTarget, comp.last9_index_target_id)
    cred = db.get(Last9Credential, comp.last9_credential_id)
    nr_cred = db.get(NewRelicCredential, comp.nr_credential_id)
    latest = _latest_runs(db, [comp.id]).get(comp.id)
    return _to_out(
        comp,
        index_name=idx.name if idx else None,
        cred_label=cred.label if cred else None,
        nr_label=nr_cred.label if nr_cred else None,
        nr_account_id=nr_cred.account_id if nr_cred else None,
        latest=latest,
    )


@router.put("/{comparison_id}", response_model=ComparisonOut)
def update_comparison(
    comparison_id: int,
    body: ComparisonCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ComparisonOut:
    comp = _get_or_404(db, comparison_id)
    idx, credential_id, pipeline, spec, nr_cred = _validate_create(db, body)
    comp.name = body.name.strip()
    comp.description = body.description.strip() or None
    comp.last9_credential_id = credential_id
    comp.last9_index_target_id = idx.id
    comp.last9_region_code = idx.region_code
    comp.last9_pipeline = pipeline
    comp.last9_filter_spec = spec
    comp.nr_credential_id = nr_cred.id
    comp.nrql = body.nrql.strip()
    comp.nr_value_mode = body.nr_value_mode
    comp.nr_value_field = body.nr_value_field.strip() if body.nr_value_field else None
    comp.bucket_seconds = body.bucket_seconds
    audit.record(db, "update", "comparison", comp.id, {"name": comp.name}, user_id=user.email)
    db.commit()
    db.refresh(comp)
    return _to_out(
        comp,
        index_name=idx.name,
        cred_label=db.get(Last9Credential, credential_id).label,
        nr_label=nr_cred.label,
        nr_account_id=nr_cred.account_id,
        latest=_latest_runs(db, [comp.id]).get(comp.id),
    )


@router.delete("/{comparison_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comparison(
    comparison_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = _get_or_404(db, comparison_id)
    db.query(ComparisonRun).filter(ComparisonRun.comparison_id == comparison_id).delete(
        synchronize_session=False
    )
    db.delete(comp)
    audit.record(db, "delete", "comparison", comparison_id, user_id=user.email)
    db.commit()


@router.post("/{comparison_id}/run", response_model=ComparisonRunOut)
def run_comparison(
    comparison_id: int,
    body: ComparisonRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ComparisonRunOut:
    comp = _get_or_404(db, comparison_id)
    window = body.end_epoch - body.start_epoch
    if window <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "end must be after start")
    settings = get_settings()
    if window > settings.comparison_max_window_days * 86400:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"comparison window is limited to {settings.comparison_max_window_days} days",
        )

    idx = db.get(IndexTarget, comp.last9_index_target_id)
    l9_cred = db.get(Last9Credential, comp.last9_credential_id)
    nr_cred = db.get(NewRelicCredential, comp.nr_credential_id)
    if idx is None or l9_cred is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "this comparison's Last9 source no longer exists"
        )
    if nr_cred is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "this comparison's New Relic connection no longer exists"
        )

    bucket = _bucket_seconds(comp, body.bucket_seconds, window)
    nrql = newrelic.effective_nrql(
        comp.nrql,
        start_epoch=body.start_epoch,
        end_epoch=body.end_epoch,
        bucket_seconds=bucket,
    )
    try:
        base_pipeline = validate_pipeline(comp.last9_pipeline or [])
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    total_pipeline, series_pipeline = pipelines_for_comparison(base_pipeline, bucket)
    last9_mode = infer_value_mode(series_pipeline or total_pipeline or base_pipeline)

    # Resolve the Last9 token in the request thread. If it fails, New Relic can
    # still produce half a comparison; the Last9 side reports the auth error.
    token: str | None = None
    token_error: str | None = None
    try:
        token = access_token(db, l9_cred)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user below
        token_error = f"Last9 authentication failed: {exc}"

    try:
        api_key = _decrypt_nr_key(nr_cred)
    except Exception:  # noqa: BLE001 - key rotation or a corrupted row
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "this comparison's New Relic API key could not be decrypted — re-add the connection",
        ) from None
    l9_cred_id = l9_cred.id
    # Capture everything the post-network code needs before ending the read
    # transaction. The request's pooled connection is then free while the
    # provider calls are in flight; the same session reacquires one to save.
    comparison_pk = comp.id
    l9_org_slug = l9_cred.org_slug
    l9_region = idx.region_code
    l9_index = idx.full_index_string
    nr_account_id = nr_cred.account_id
    nr_region = nr_cred.region
    nr_value_mode = comp.nr_value_mode
    nr_value_field = comp.nr_value_field
    created_by = user.email
    db.rollback()
    timeout = settings.comparison_query_timeout_seconds

    refresh_lock = threading.Lock()
    refreshed = False

    def refresh_token() -> str:
        # Runs in a query thread if Last9 says the token expired mid-flight.
        # A fresh session keeps this independent of the request's session. The
        # total and series queries can both hit a 401 at once; serializing means
        # the second one reuses the token the first persisted instead of spending
        # the same (possibly rotated) refresh token twice.
        nonlocal refreshed
        with refresh_lock:
            with SessionLocal() as fresh:
                cred = fresh.get(Last9Credential, l9_cred_id)
                if cred is None:
                    raise Last9QueryError("Last9 credential no longer exists")
                token = access_token(fresh, cred, force=not refreshed)
            refreshed = True
            return token

    nr_result: newrelic.NewRelicQueryResult | None = None
    nr_error: str | None = None
    total_rows: list[dict] | None = None
    series_rows: list[dict] | None = None
    total_error: str | None = None
    series_error: str | None = None
    total_elapsed: int | None = None
    series_elapsed: int | None = None

    with ThreadPoolExecutor(max_workers=3) as pool:
        nr_future = pool.submit(
            newrelic.execute_nrql,
            api_key=api_key,
            account_id=nr_account_id,
            region=nr_region,
            nrql=nrql,
            timeout=timeout,
        )
        total_future = (
            pool.submit(
                query_last9,
                org_slug=l9_org_slug,
                token=token,
                refresh=refresh_token,
                region=l9_region,
                index=l9_index,
                pipeline=total_pipeline,
                start_epoch=body.start_epoch,
                end_epoch=body.end_epoch,
                limit=5000,
                timeout=timeout,
            )
            if total_pipeline and token
            else None
        )
        series_future = (
            pool.submit(
                query_last9,
                org_slug=l9_org_slug,
                token=token,
                refresh=refresh_token,
                region=l9_region,
                index=l9_index,
                pipeline=series_pipeline,
                start_epoch=body.start_epoch,
                end_epoch=body.end_epoch,
                limit=5000,
                timeout=timeout,
            )
            if series_pipeline and token
            else None
        )

        try:
            nr_result = nr_future.result()
        except Exception as exc:  # noqa: BLE001
            nr_error = _friendly(exc)

        if total_future is not None:
            try:
                total_result = total_future.result()
                total_rows = total_result.rows
                total_elapsed = total_result.elapsed_ms
            except Exception as exc:  # noqa: BLE001
                total_error = _friendly(exc)
        if series_future is not None:
            try:
                series_result = series_future.result()
                series_rows = series_result.rows
                series_elapsed = series_result.elapsed_ms
            except Exception as exc:  # noqa: BLE001
                series_error = _friendly(exc)

    # New Relic side
    nr_total: float | None = None
    nr_series: list[dict] = []
    nr_raw: list[dict] = []
    nr_metadata = nr_result.metadata if nr_result else None
    nr_elapsed = nr_result.elapsed_ms if nr_result else None
    nr_ok = nr_result is not None
    if nr_result is not None:
        try:
            nr_total, nr_series, nr_field = newrelic.normalize_nr_results(
                nr_result.results,
                start_epoch=body.start_epoch,
                end_epoch=body.end_epoch,
                bucket_seconds=bucket,
                value_field=nr_value_field,
                mode=nr_value_mode,
            )
            nr_raw = nr_result.results[:_MAX_RAW_ROWS]
            nr_metadata = {**(nr_metadata or {}), "value_field": nr_field}
        except newrelic.NewRelicError as exc:
            nr_ok = False
            nr_error = str(exc)

    # Last9 side
    l9_total: float | None = None
    l9_series: list[dict] = []
    l9_raw: list[dict] = []
    l9_errors: list[str] = []
    if token_error:
        l9_errors.append(token_error)
    if total_pipeline is None:
        # A hand-written window_aggregate has no separate total; reduce its
        # buckets with the aggregate's own function.
        if series_rows is not None:
            l9_series = extract_series(
                series_rows,
                bucket_seconds=bucket,
                start_epoch=body.start_epoch,
                end_epoch=body.end_epoch,
                mode=last9_mode,
            )
            l9_total = (
                aggregate_values([float(point["value"]) for point in l9_series], last9_mode)
                if l9_series
                else 0.0
            )
    else:
        if total_error:
            l9_errors.append(f"total query: {total_error}")
        elif total_rows is not None:
            l9_total = extract_total(total_rows, mode=last9_mode)
    if series_pipeline is not None:
        if series_error:
            l9_errors.append(f"series query: {series_error}")
        elif series_rows is not None:
            l9_series = extract_series(
                series_rows,
                bucket_seconds=bucket,
                start_epoch=body.start_epoch,
                end_epoch=body.end_epoch,
                mode=last9_mode,
            )
            # If the total query failed but the series worked, its reduction is
            # the most accurate total available.
            if l9_total is None and l9_series:
                l9_total = aggregate_values(
                    [float(point["value"]) for point in l9_series], last9_mode
                )

    # The per-window rows are more useful to inspect than the single total row.
    if series_rows is not None:
        l9_raw = series_rows[:_MAX_RAW_ROWS]
    elif total_rows is not None:
        l9_raw = total_rows[:_MAX_RAW_ROWS]

    l9_ok = bool(
        token
        and (
            (total_pipeline is not None and total_rows is not None)
            or (series_pipeline is not None and series_rows is not None)
        )
    )
    l9_error = "; ".join(l9_errors) if l9_errors else None

    if l9_ok and nr_ok and not l9_errors:
        run_status = "ok"
    elif l9_ok or nr_ok:
        run_status = "partial"
    else:
        run_status = "failed"

    run = ComparisonRun(
        comparison_id=comparison_pk,
        start_epoch=body.start_epoch,
        end_epoch=body.end_epoch,
        bucket_seconds=bucket,
        status=run_status,
        last9_ok=l9_ok,
        last9_error=l9_error,
        last9_total=l9_total,
        last9_series=l9_series,
        last9_raw=l9_raw,
        last9_elapsed_ms=max(
            [value for value in (total_elapsed, series_elapsed) if value is not None],
            default=None,
        ),
        newrelic_ok=nr_ok,
        newrelic_error=nr_error,
        newrelic_total=nr_total,
        newrelic_series=nr_series,
        newrelic_raw=nr_raw,
        newrelic_metadata=nr_metadata,
        newrelic_elapsed_ms=nr_elapsed,
        nrql_effective=nrql,
        last9_pipeline_effective={
            "total": total_pipeline,
            "series": series_pipeline,
            "bucket_seconds": bucket,
            "value_mode": last9_mode,
        },
        created_by=created_by,
    )
    db.add(run)
    db.flush()
    audit.record(
        db,
        "run",
        "comparison",
        comparison_pk,
        {
            "run_id": run.id,
            "start_epoch": body.start_epoch,
            "end_epoch": body.end_epoch,
            "status": run_status,
        },
        user_id=created_by,
    )
    db.commit()
    db.refresh(run)
    return _run_out(run)


def _decrypt_nr_key(cred: NewRelicCredential) -> str:
    return crypto.decrypt(cred.encrypted_api_key)


def _friendly(exc: Exception) -> str:
    if isinstance(exc, newrelic.NewRelicError | Last9QueryError | ValueError):
        return str(exc)
    text = str(exc).strip()
    return text[:600] if text else type(exc).__name__


@router.get("/{comparison_id}/runs", response_model=list[ComparisonRunSummary])
def list_runs(
    comparison_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[ComparisonRunSummary]:
    _get_or_404(db, comparison_id)
    runs = db.scalars(
        select(ComparisonRun)
        .where(ComparisonRun.comparison_id == comparison_id)
        .order_by(ComparisonRun.id.desc())
        .limit(limit)
    ).all()
    return [_summary(run) for run in runs]


@router.get("/{comparison_id}/runs/{run_id}", response_model=ComparisonRunOut)
def get_run(comparison_id: int, run_id: int, db: Session = Depends(get_db)) -> ComparisonRunOut:
    run = db.get(ComparisonRun, run_id)
    if run is None or run.comparison_id != comparison_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    return _run_out(run)
