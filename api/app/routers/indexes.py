"""Index targets CRUD + regions list.

The index dropdown is region-dependent: GET /indexes?region=<code> returns only
that region's targets. full_index_string is derived as physical_index:<name>,
except an explicitly blank physical index means the org's Default index: Last9
resolves it server-side, so the worker sends no `index` parameter at all (any
value 400s). Omitted (None) still derives from the label, as before.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.database import get_db
from app.deps import get_current_user
from app.models import IndexTarget, Last9Credential, User
from app.redis_client import get_redis
from app.schemas import IndexCreate, IndexOut, IndexUpdate, RegionOut

_INDEX_TTL = 900  # 15 minutes


def _cache_key(region: str | None) -> str:
    return f"logvault:indexes:{region or 'all'}"


def _invalidate_index_cache(region_code: str | None = None) -> None:
    try:
        r = get_redis()
        r.delete(_cache_key(None))
        if region_code:
            r.delete(_cache_key(region_code))
    except Exception:
        pass  # ponytail: cache invalidation failure must never break writes


# §2.11 ground truth. ponytail: duplicated from worker/app/last9.constants to avoid
# a cross-package import; promote to a shared package if a third consumer needs it.
REGIONS = {
    "ap-south-1": "India",
    "us-east-1": "Virginia",
    "ap-southeast-1": "Singapore",
    "eu-central-1": "Frankfurt",
}

router = APIRouter(tags=["indexes"])


@router.get("/regions", response_model=list[RegionOut])
def list_regions() -> list[RegionOut]:
    return [RegionOut(code=code, label=label) for code, label in REGIONS.items()]


def _check_credential(db: Session, credential_id: int | None) -> None:
    if credential_id is not None and db.get(Last9Credential, credential_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "unknown credential_id")


def full_for(physical: str) -> str:
    """The query string for a physical index name — "" for the org Default."""
    return f"physical_index:{physical}" if physical else ""


@router.post("/indexes", response_model=IndexOut, status_code=status.HTTP_201_CREATED)
def create_index(
    body: IndexCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> IndexTarget:
    if body.region_code not in REGIONS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "unknown region_code")
    _check_credential(db, body.credential_id)
    # None (omitted) derives from the label; an explicit blank selects the
    # org's Default index (full string "" => worker omits `index`).
    physical = body.name.strip() if body.physical_index is None else body.physical_index.strip()
    idx = IndexTarget(
        name=body.name,
        region_code=body.region_code,
        physical_index=physical,
        # Derived from the PHYSICAL index, never the label — the label is free
        # text and renaming it must not repoint the target.
        full_index_string=full_for(physical),
        credential_id=body.credential_id,
        description=body.description,
    )
    db.add(idx)
    try:
        db.flush()
        audit.record(
            db,
            "create",
            "index",
            idx.id,
            {"name": idx.name, "region": idx.region_code},
            user_id=user.email,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "an index with this name already exists in this region"
        ) from exc
    db.refresh(idx)
    _invalidate_index_cache(idx.region_code)
    return idx


@router.get("/indexes", response_model=list[IndexOut])
def list_indexes(
    region: str | None = Query(default=None), db: Session = Depends(get_db)
) -> list[IndexOut]:
    try:
        cached = get_redis().get(_cache_key(region))
        if cached:
            return [IndexOut.model_validate(item) for item in json.loads(cached)]
    except Exception:
        pass  # Redis miss or down — fall through to DB

    stmt = select(IndexTarget).order_by(IndexTarget.region_code, IndexTarget.name)
    if region:
        stmt = stmt.where(IndexTarget.region_code == region)
    rows = list(db.scalars(stmt).all())
    out = [IndexOut.model_validate(r) for r in rows]
    # One extra query, not N: the label is what the source picker shows, so it
    # has to come back with the profile.
    cred_ids = {r.credential_id for r in rows if r.credential_id}
    if cred_ids:
        labels = {
            c.id: c.label
            for c in db.scalars(select(Last9Credential).where(Last9Credential.id.in_(cred_ids)))
        }
        for item in out:
            item.credential_label = labels.get(item.credential_id or -1)

    try:
        get_redis().setex(
            _cache_key(region), _INDEX_TTL, json.dumps([o.model_dump(mode="json") for o in out])
        )
    except Exception:
        pass

    return out


@router.put("/indexes/{index_id}", response_model=IndexOut)
def update_index(index_id: int, body: IndexUpdate, db: Session = Depends(get_db)) -> IndexTarget:
    idx = db.get(IndexTarget, index_id)
    if idx is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "index not found")
    if body.name is not None:
        idx.name = body.name  # label only — see create_index
    if body.physical_index is not None:
        idx.physical_index = body.physical_index.strip()
        idx.full_index_string = full_for(idx.physical_index)
    if body.credential_id is not None:
        _check_credential(db, body.credential_id)
        idx.credential_id = body.credential_id
    if body.description is not None:
        idx.description = body.description
    db.commit()
    db.refresh(idx)
    _invalidate_index_cache(idx.region_code)
    return idx


@router.delete("/indexes/{index_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_index(
    index_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    idx = db.get(IndexTarget, index_id)
    if idx is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "index not found")
    region_code = idx.region_code
    db.delete(idx)
    audit.record(db, "delete", "index", index_id, user_id=user.email)
    db.commit()
    _invalidate_index_cache(region_code)
