"""Reusable filter templates ("save the search") — a named phrase/ID/message-type
set that can be loaded into a new job or schedule instead of retyped. Not tied
to a credential/region/index, so the same template applies to any of them."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.aggregation import validate_aggregation
from app.database import get_db
from app.deps import get_current_user
from app.models import FilterTemplate, IndexTarget, Last9Credential, User
from app.schemas import FilterTemplateCreate, FilterTemplateOut

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[FilterTemplateOut])
def list_templates(db: Session = Depends(get_db)) -> list[FilterTemplate]:
    return list(db.scalars(select(FilterTemplate).order_by(FilterTemplate.name)))


# raw_column_defaults, timestamp_column and column_labels have no control in
# either the New Extraction wizard or the Saved Searches edit form — they're
# only ever populated via the job-export JSON or a direct API call. A value
# still sitting at its schema default is read as "this submission didn't touch
# it", so routing an edit through either form never silently resets one back
# to default. (A direct API call that genuinely wants to clear one of these
# back to its default can't via this endpoint — the acceptable side of the
# trade, since nothing today does that.)
#
# raw_columns and include_message do NOT belong here: both forms have real
# checkboxes for them now, so "sitting at default" is a submission that
# genuinely wants the default — inheriting the prior value instead would
# silently undo an unchecked box the moment it happened to land back on the
# default set, which is exactly the box someone unchecking it would hit.
_HIDDEN_AGG_DEFAULTS = {
    "raw_column_defaults": {},
    "timestamp_column": "timestamp_utc",
    "column_labels": {},
}


def _check_source(db: Session, credential_id: int | None, index_target_id: int | None) -> None:
    """A remembered source must point at rows that still exist — a batch run
    trusts it blindly, so dangling ids fail here instead of mid-batch."""
    if credential_id is not None and db.get(Last9Credential, credential_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "unknown credential_id")
    if index_target_id is not None and db.get(IndexTarget, index_target_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "unknown index_target_id")


def _build_aggregation(body: FilterTemplateCreate, prior: dict | None) -> dict | None:
    # A saved search is filed under a customer: it names the export folder and
    # is what the jobs list shows instead of a region. Without it a search's
    # extractions are unidentifiable, so it is not optional at save time.
    if not (body.customer or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "a saved search needs a customer name",
        )
    agg = body.aggregation if body.aggregation and body.aggregation.enabled else None
    if not body.phrases and not body.ids and not body.message_types and not agg:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "a template needs at least one phrase, ID, message type, or a parse pattern",
        )
    if not agg:
        return None
    # Validated on save so a broken pattern is caught here rather than
    # resurfacing on every job loaded from this template.
    try:
        validate_aggregation(
            agg.regex,
            agg.group_by,
            agg.unique_fields,
            agg.raw_columns,
            agg.raw_column_defaults,
            agg.use_library,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    agg_dict = agg.model_dump()
    if prior:
        for field, default in _HIDDEN_AGG_DEFAULTS.items():
            # `field in prior`, not truthiness — `include_message: False` is a
            # meaningful non-default value that a truthiness check would treat
            # as "nothing to inherit" and silently flip back to True.
            if agg_dict[field] == default and field in prior:
                agg_dict[field] = prior[field]
    return agg_dict


@router.post("", response_model=FilterTemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    body: FilterTemplateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FilterTemplate:
    agg_dict = _build_aggregation(body, prior=None)
    _check_source(db, body.credential_id, body.index_target_id)
    tpl = FilterTemplate(
        name=body.name,
        phrases=body.phrases,
        ids=body.ids,
        message_types=body.message_types,
        customer=body.customer.strip() or None,
        aggregation=agg_dict,
        credential_id=body.credential_id,
        region_code=body.region_code,
        index_target_id=body.index_target_id,
    )
    db.add(tpl)
    try:
        db.flush()
        audit.record(
            db, "create", "filter_template", tpl.id, {"name": tpl.name}, user_id=user.email
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "a template with this name already exists"
        ) from exc
    db.refresh(tpl)
    return tpl


@router.put("/{template_id}", response_model=FilterTemplateOut)
def update_template(
    template_id: int,
    body: FilterTemplateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FilterTemplate:
    tpl = db.get(FilterTemplate, template_id)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "template not found")
    agg_dict = _build_aggregation(body, prior=tpl.aggregation)
    _check_source(db, body.credential_id, body.index_target_id)
    tpl.name = body.name
    tpl.phrases = body.phrases
    tpl.ids = body.ids
    tpl.message_types = body.message_types
    tpl.customer = body.customer.strip() or None
    tpl.aggregation = agg_dict
    tpl.credential_id = body.credential_id
    tpl.region_code = body.region_code
    tpl.index_target_id = body.index_target_id
    try:
        db.flush()
        audit.record(
            db, "update", "filter_template", tpl.id, {"name": tpl.name}, user_id=user.email
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "a template with this name already exists"
        ) from exc
    db.refresh(tpl)
    return tpl


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    tpl = db.get(FilterTemplate, template_id)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "template not found")
    db.delete(tpl)
    audit.record(db, "delete", "filter_template", template_id, user_id=user.email)
    db.commit()
