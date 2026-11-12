"""Upload completed extraction artifacts to a saved S3 destination.

The worker writes the checkpointed CSV/JSONL locally first (that file is what
makes pause/resume safe), then uploads the final artifacts. Local files remain
for the normal download/retention path; S3 is an additional delivery target.
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app import crypto

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class S3UploadError(ValueError):
    """A user-actionable upload failure."""


def destination_snapshot(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if not profile:
        return None
    return {
        "profile_id": profile.get("id"),
        "name": profile.get("name"),
        "bucket": profile.get("bucket"),
        "region": profile.get("region"),
        "prefix": profile.get("prefix") or "",
    }


def _attr(profile: dict[str, Any], name: str, default: Any = None) -> Any:
    return profile.get(name, default)


def _clean_segment(value: str | None) -> str:
    return _UNSAFE.sub("_", (value or "").strip()).strip("._-")


def build_client(profile: dict[str, Any]):
    access_key = _attr(profile, "encrypted_access_key_id")
    secret_key = _attr(profile, "encrypted_secret_access_key")
    session_token = _attr(profile, "encrypted_session_token")

    kwargs: dict[str, Any] = {
        "region_name": _attr(profile, "region") or "us-east-1",
        "config": Config(
            retries={"max_attempts": 5, "mode": "standard"},
            connect_timeout=10,
            read_timeout=120,
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
            raise S3UploadError("S3 profile has only one of access key / secret key")
        kwargs["aws_access_key_id"] = crypto.decrypt(access_key)
        kwargs["aws_secret_access_key"] = crypto.decrypt(secret_key)
        if session_token:
            kwargs["aws_session_token"] = crypto.decrypt(session_token)
    try:
        return boto3.client("s3", **kwargs)
    except Exception as exc:  # noqa: BLE001
        raise S3UploadError(f"could not create S3 client: {exc}") from exc


def _timeframe(start_epoch: int, end_epoch: int) -> str:
    start = datetime.fromtimestamp(start_epoch, UTC)
    last = datetime.fromtimestamp(max(start_epoch, end_epoch - 1), UTC)
    whole_day = end_epoch - start_epoch == 86400 and (start.hour, start.minute, start.second) == (
        0,
        0,
        0,
    )
    if whole_day:
        return start.strftime("%Y-%m-%d")
    if start.date() == last.date():
        return f"{start:%Y-%m-%d_%H%M}-{last:%H%M}"
    return f"{start:%Y-%m-%d_%H%M}-{last:%Y-%m-%d_%H%M}"


def _artifact_name(job: dict[str, Any], kind: str, path: str) -> str:
    label = (job.get("filter_spec") or {}).get("label")
    stem = _UNSAFE.sub("_", label or "").strip("_") or f"job_{job['id']}"
    stem = f"{stem}_{job['id']}"
    name = f"{stem}_{_timeframe(job['start_epoch'], job['end_epoch'])}"
    if kind in ("summary", "counts"):
        name = f"{name}_{kind}.csv"
    else:
        ext = "jsonl" if job.get("output_format") == "jsonl" else "csv"
        name = f"{name}.{ext}"
    return f"{name}.zip" if path.endswith(".zip") else name


def _object_key(profile: dict[str, Any], job: dict[str, Any], filename: str) -> str:
    prefix = (_attr(profile, "prefix") or "").strip().strip("/")
    customer = _clean_segment((job.get("filter_spec") or {}).get("customer"))
    parts = [part for part in (prefix, customer, filename) if part]
    return "/".join(parts)


def _content_type(path: str) -> str:
    if path.endswith(".zip"):
        return "application/zip"
    if path.endswith(".jsonl"):
        return "application/x-ndjson"
    if path.endswith(".csv"):
        return "text/csv"
    return "application/octet-stream"


def upload_job_artifacts(
    job: dict[str, Any], profile: dict[str, Any]
) -> tuple[dict[str, str], list[str]]:
    """Upload whichever final artifacts exist; return URIs and per-file errors.

    The three artifacts are independent, so they upload concurrently. boto3's
    transfer manager is thread-safe per client and already parallelizes chunks
    inside one large file; running the artifacts in parallel removes the serial
    wait between raw, summary and counts.
    """
    bucket = (_attr(profile, "bucket") or "").strip()
    if not bucket:
        raise S3UploadError("S3 profile has no bucket")

    client = build_client(profile)
    artifacts = [
        (kind, path)
        for kind, path in (
            ("raw", job.get("output_file_path")),
            ("summary", job.get("summary_file_path")),
            ("counts", job.get("counts_file_path")),
        )
        if path
    ]
    if not artifacts:
        return {}, []

    def upload_one(kind: str, path: str) -> tuple[str, str | None, str | None]:
        if not os.path.exists(path):
            return kind, None, f"{kind}: file disappeared before upload ({path})"
        key = _object_key(profile, job, _artifact_name(job, kind, path))
        try:
            client.upload_file(
                path,
                bucket,
                key,
                ExtraArgs={"ContentType": _content_type(path)},
            )
            return kind, f"s3://{bucket}/{key}", None
        except (ClientError, BotoCoreError, OSError) as exc:
            return kind, None, f"{kind}: {_friendly_error(exc)}"
        except Exception as exc:  # noqa: BLE001
            return kind, None, f"{kind}: {exc}"

    uris: dict[str, str] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=len(artifacts)) as pool:
        for kind, uri, error in pool.map(lambda item: upload_one(*item), artifacts):
            if uri:
                uris[kind] = uri
            if error:
                errors.append(error)
    return uris, errors


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, ClientError):
        error = exc.response.get("Error", {})
        code = error.get("Code", "")
        message = error.get("Message", "") or str(exc)
        return f"{code}: {message}"[:600] if code else message[:600]
    return str(exc)[:600]
