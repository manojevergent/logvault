"""S3 destination helpers for the API.

The worker owns the actual upload path; the API needs a client only to test a
profile (write a tiny object and remove it). Credentials are decrypted from the
same Fernet store as Last9/New Relic secrets.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app import crypto
from app.models import S3Profile


class S3ProfileError(ValueError):
    """A user-actionable S3 profile/connectivity failure."""


def destination_snapshot(profile: S3Profile | None) -> dict | None:
    if profile is None:
        return None
    return {
        "profile_id": profile.id,
        "name": profile.name,
        "bucket": profile.bucket,
        "region": profile.region,
        "prefix": profile.prefix or "",
    }


def profile_or_422(db, profile_id: int | None) -> S3Profile | None:
    if profile_id is None:
        return None
    profile = db.get(S3Profile, profile_id)
    if profile is None:
        from fastapi import HTTPException, status

        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "unknown S3 profile")
    return profile


def profile_by_name(db, name: str) -> S3Profile | None:
    from sqlalchemy import select

    return db.scalar(select(S3Profile).where(S3Profile.name == name))


def _attr(profile: S3Profile | dict[str, Any], name: str, default: Any = None) -> Any:
    if isinstance(profile, dict):
        return profile.get(name, default)
    return getattr(profile, name, default)


def _clean_prefix(prefix: str | None) -> str:
    return (prefix or "").strip().strip("/")


def build_client(profile: S3Profile | dict[str, Any]):
    access_key = _attr(profile, "encrypted_access_key_id")
    secret_key = _attr(profile, "encrypted_secret_access_key")
    session_token = _attr(profile, "encrypted_session_token")

    kwargs: dict[str, Any] = {
        "region_name": _attr(profile, "region") or "us-east-1",
        "config": Config(
            retries={"max_attempts": 4, "mode": "standard"},
            connect_timeout=10,
            read_timeout=60,
            signature_version="s3v4",
            s3={
                "addressing_style": "path" if _attr(profile, "force_path_style", False) else "auto"
            },
        ),
    }
    endpoint = _attr(profile, "endpoint_url")
    if endpoint:
        kwargs["endpoint_url"] = endpoint

    if access_key or secret_key:
        if not access_key or not secret_key:
            raise S3ProfileError("both access key id and secret access key are required")
        kwargs["aws_access_key_id"] = crypto.decrypt(access_key)
        kwargs["aws_secret_access_key"] = crypto.decrypt(secret_key)
        if session_token:
            kwargs["aws_session_token"] = crypto.decrypt(session_token)

    try:
        return boto3.client("s3", **kwargs)
    except Exception as exc:  # noqa: BLE001 - client construction errors are user-facing
        raise S3ProfileError(f"could not create S3 client: {exc}") from exc


def test_profile(profile: S3Profile) -> str:
    """Write and delete a small object, proving the bucket is usable."""
    bucket = (profile.bucket or "").strip()
    if not bucket:
        raise S3ProfileError("bucket is required")
    client = build_client(profile)
    key = "/".join(
        part
        for part in (
            _clean_prefix(profile.prefix),
            f".logvault-connection-test-{uuid4().hex}.txt",
        )
        if part
    )
    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=b"logvault s3 connection test",
            ContentType="text/plain",
        )
    except (ClientError, BotoCoreError) as exc:
        raise S3ProfileError(_friendly_error(exc)) from exc
    try:
        client.delete_object(Bucket=bucket, Key=key)
    except (ClientError, BotoCoreError):
        # A write-only policy is unusual but still proves the destination works;
        # leaving one tiny test object is preferable to a false failure.
        return f"write to s3://{bucket}/{key} succeeded (test object could not be removed)"
    return f"write to s3://{bucket}/{key} succeeded"


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, ClientError):
        error = exc.response.get("Error", {}) if hasattr(exc, "response") else {}
        code = error.get("Code", "")
        message = error.get("Message", "") or str(exc)
        return f"{code}: {message}"[:600] if code else message[:600]
    return str(exc)[:600]
