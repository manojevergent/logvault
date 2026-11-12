"""S3 artifact naming and upload behaviour without talking to AWS."""

from __future__ import annotations

from app import s3


def _job(**over):
    job = {
        "id": 42,
        "start_epoch": 0,
        "end_epoch": 7200,
        "output_format": "csv",
        "filter_spec": {"label": "Invoice Search", "customer": "ACME Corp"},
        "output_file_path": None,
        "summary_file_path": None,
        "counts_file_path": None,
    }
    job.update(over)
    return job


def _profile(**over):
    profile = {
        "id": 7,
        "name": "archive",
        "bucket": "acme-logs",
        "region": "us-east-1",
        "prefix": "logvault/exports",
        "endpoint_url": None,
        "encrypted_access_key_id": None,
        "encrypted_secret_access_key": None,
        "encrypted_session_token": None,
        "force_path_style": False,
    }
    profile.update(over)
    return profile


def test_destination_snapshot_names_the_bucket():
    assert s3.destination_snapshot(_profile()) == {
        "profile_id": 7,
        "name": "archive",
        "bucket": "acme-logs",
        "region": "us-east-1",
        "prefix": "logvault/exports",
    }
    assert s3.destination_snapshot(None) is None


def test_artifact_names_include_search_job_window_and_zip_suffix(tmp_path):
    raw = tmp_path / "job_42.csv.zip"
    raw.write_bytes(b"zip")
    job = _job(output_file_path=str(raw))
    assert s3._artifact_name(job, "raw", str(raw)) == (
        "Invoice_Search_42_1970-01-01_0000-0159.csv.zip"
    )
    assert s3._object_key(_profile(), job, s3._artifact_name(job, "raw", str(raw))) == (
        "logvault/exports/ACME_Corp/Invoice_Search_42_1970-01-01_0000-0159.csv.zip"
    )


def test_upload_job_artifacts_uploads_raw_summary_and_counts(tmp_path, monkeypatch):
    raw = tmp_path / "job_42.csv.zip"
    raw.write_bytes(b"raw")
    summary = tmp_path / "job_42.summary.csv.zip"
    summary.write_bytes(b"summary")
    counts = tmp_path / "job_42.counts.csv.zip"
    counts.write_bytes(b"counts")
    job = _job(
        output_file_path=str(raw),
        summary_file_path=str(summary),
        counts_file_path=str(counts),
    )

    calls = []

    class FakeClient:
        def upload_file(self, path, bucket, key, ExtraArgs=None):
            calls.append((path, bucket, key, ExtraArgs))

    monkeypatch.setattr(s3, "build_client", lambda _profile: FakeClient())
    uris, errors = s3.upload_job_artifacts(job, _profile())

    assert errors == []
    assert uris == {
        "raw": "s3://acme-logs/logvault/exports/ACME_Corp/"
        "Invoice_Search_42_1970-01-01_0000-0159.csv.zip",
        "summary": "s3://acme-logs/logvault/exports/ACME_Corp/"
        "Invoice_Search_42_1970-01-01_0000-0159_summary.csv.zip",
        "counts": "s3://acme-logs/logvault/exports/ACME_Corp/"
        "Invoice_Search_42_1970-01-01_0000-0159_counts.csv.zip",
    }
    assert [c[3]["ContentType"] for c in calls] == [
        "application/zip",
        "application/zip",
        "application/zip",
    ]


def test_upload_reports_a_missing_file_but_continues(tmp_path, monkeypatch):
    raw = tmp_path / "job_42.csv"
    raw.write_bytes(b"raw")

    class FakeClient:
        def upload_file(self, *args, **kwargs):
            return None

    monkeypatch.setattr(s3, "build_client", lambda _profile: FakeClient())
    uris, errors = s3.upload_job_artifacts(
        _job(
            output_file_path=str(raw),
            summary_file_path=str(tmp_path / "gone.csv"),
        ),
        _profile(),
    )
    assert "raw" in uris
    assert len(errors) == 1
    assert "summary: file disappeared" in errors[0]
