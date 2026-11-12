"""S3 destination profiles: encrypted credentials + reusable bucket targets."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit, crypto, s3
from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models import FilterTemplate, S3Profile, Schedule, User
from app.schemas import (
    S3ProfileCreate,
    S3ProfileOut,
    S3ProfileUpdate,
    S3TestResult,
)

router = APIRouter(prefix="/s3-profiles", tags=["s3"])


def _to_out(profile: S3Profile) -> S3ProfileOut:
    return S3ProfileOut(
        id=profile.id,
        name=profile.name,
        bucket=profile.bucket,
        region=profile.region,
        prefix=profile.prefix or "",
        endpoint_url=profile.endpoint_url,
        key_preview=f"••••{profile.key_last4}" if profile.key_last4 else "instance role",
        force_path_style=profile.force_path_style,
        created_by=profile.created_by,
        created_at=profile.created_at,
    )


def _validate_name_bucket(name: str, bucket: str, region: str) -> tuple[str, str, str]:
    name = name.strip()
    bucket = bucket.strip()
    region = (region or "").strip() or "us-east-1"
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "profile name is required")
    if not bucket:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "bucket is required")
    return name, bucket, region


def _credential_values(body) -> tuple[str | None, str | None, str | None] | None:
    access = (getattr(body, "access_key_id", None) or "").strip()
    secret = (getattr(body, "secret_access_key", None) or "").strip()
    token = (getattr(body, "session_token", None) or "").strip()
    if not access and not secret:
        if token:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "a session token requires an access key id and secret access key",
            )
        return None
    if not access or not secret:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "provide both the access key id and secret access key, or leave both blank for the instance role",
        )
    return access, secret, token or None


@router.get("", response_model=list[S3ProfileOut])
def list_profiles(db: Session = Depends(get_db)) -> list[S3ProfileOut]:
    rows = db.scalars(select(S3Profile).order_by(S3Profile.name)).all()
    return [_to_out(row) for row in rows]


@router.post("", response_model=S3ProfileOut, status_code=status.HTTP_201_CREATED)
def create_profile(
    body: S3ProfileCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> S3ProfileOut:
    name, bucket, region = _validate_name_bucket(body.name, body.bucket, body.region)
    credentials = _credential_values(body)
    profile = S3Profile(
        name=name,
        bucket=bucket,
        region=region,
        prefix=(body.prefix or "").strip().strip("/"),
        endpoint_url=(body.endpoint_url or "").strip() or None,
        force_path_style=body.force_path_style,
        created_by=user.email,
    )
    if credentials:
        access, secret, token = credentials
        profile.encrypted_access_key_id = crypto.encrypt(access)
        profile.encrypted_secret_access_key = crypto.encrypt(secret)
        profile.encrypted_session_token = crypto.encrypt(token) if token else None
        profile.key_last4 = access[-4:]
    db.add(profile)
    try:
        db.flush()
        audit.record(
            db,
            "create",
            "s3_profile",
            profile.id,
            {"name": profile.name, "bucket": profile.bucket, "region": profile.region},
            user_id=user.email,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "an S3 profile with this name already exists"
        ) from exc
    db.refresh(profile)
    return _to_out(profile)


@router.put("/{profile_id}", response_model=S3ProfileOut)
def update_profile(
    profile_id: int,
    body: S3ProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> S3ProfileOut:
    profile = db.get(S3Profile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "S3 profile not found")

    name, bucket, region = _validate_name_bucket(
        body.name if body.name is not None else profile.name,
        body.bucket if body.bucket is not None else profile.bucket,
        body.region if body.region is not None else profile.region,
    )
    profile.name = name
    profile.bucket = bucket
    profile.region = region
    if body.prefix is not None:
        profile.prefix = body.prefix.strip().strip("/")
    if body.endpoint_url is not None:
        profile.endpoint_url = body.endpoint_url.strip() or None
    if body.force_path_style is not None:
        profile.force_path_style = body.force_path_style

    if body.clear_credentials:
        profile.encrypted_access_key_id = None
        profile.encrypted_secret_access_key = None
        profile.encrypted_session_token = None
        profile.key_last4 = None
    else:
        credentials = _credential_values(body)
        if credentials:
            access, secret, token = credentials
            profile.encrypted_access_key_id = crypto.encrypt(access)
            profile.encrypted_secret_access_key = crypto.encrypt(secret)
            profile.encrypted_session_token = crypto.encrypt(token) if token else None
            profile.key_last4 = access[-4:]

    try:
        db.flush()
        audit.record(
            db,
            "update",
            "s3_profile",
            profile.id,
            {"name": profile.name, "bucket": profile.bucket, "region": profile.region},
            user_id=user.email,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "an S3 profile with this name already exists"
        ) from exc
    db.refresh(profile)
    return _to_out(profile)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    profile = db.get(S3Profile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "S3 profile not found")
    used_by = []
    used_by += [
        f"search: {name}"
        for name in db.scalars(
            select(FilterTemplate.name).where(FilterTemplate.s3_profile_id == profile_id)
        ).all()
    ]
    used_by += [
        f"schedule: {name}"
        for name in db.scalars(
            select(Schedule.name).where(Schedule.s3_profile_id == profile_id)
        ).all()
    ]
    if used_by:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "S3 profile is still used by " + ", ".join(used_by[:8]),
        )
    db.delete(profile)
    audit.record(db, "delete", "s3_profile", profile_id, user_id=user.email)
    db.commit()


@router.post("/{profile_id}/test", response_model=S3TestResult)
def test_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> S3TestResult:
    profile = db.get(S3Profile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "S3 profile not found")
    try:
        message = s3.test_profile(profile)
    except s3.S3ProfileError as exc:
        return S3TestResult(ok=False, message=str(exc))
    except Exception as exc:  # noqa: BLE001 - key decryption / boto failures
        return S3TestResult(ok=False, message=f"S3 test failed: {exc}")
    return S3TestResult(ok=True, message=message)
