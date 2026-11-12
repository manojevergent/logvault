"""Worker configuration, loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://logvault:change-me@localhost:5432/logvault"

    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    # Same db the API reads. Only carries the beat heartbeat; broker traffic
    # stays on its own dbs above.
    redis_url: str = "redis://localhost:6379/0"

    last9_encryption_key: str = "replace-with-generated-fernet-key"
    last9_api_base: str = "https://app.last9.io/api/v4"
    default_org_slug: str = "evergentapse1"

    storage_dir: str = "/data/exports"
    export_retention_days: int = 30
    zip_exports: bool = True
    # Comparison runs carry a full series plus raw provider rows each. Keep the
    # newest N per saved comparison (history is for replaying recent checks, not
    # an archive) so the table and its indexes stay small.
    comparison_run_retention_count: int = 50
    # Wrap Excel-coerced values (long ids, timestamps) as ="..." so a
    # spreadsheet keeps them verbatim. OFF by default: those quotes and the
    # leading `=` become literal data for a warehouse loading the CSV. Turn on
    # only for spreadsheet-first workflows.
    excel_escape: bool = False
    # Exports and pgdata share one host filesystem, so a job that fills the disk
    # does not just fail itself — it stops Postgres writing and takes every other
    # job, every schedule and every login down with it. Refuse to start below this.
    min_free_disk_gb: int = 10

    # Extraction slots. One slot = one job streaming at a time; the rest queue.
    # Raising this multiplies Last9 request volume and per-process memory, so it
    # is a deliberate capacity decision, not a default to maximise.
    worker_concurrency: int = 4

    # System health sampling/alerts. The sampler runs on the beat; thresholds and
    # destinations live in the admin UI (app_settings "health_alerts").
    health_check_interval_seconds: int = 60
    # A `running` job silent for this long is presumed dead. Generous on purpose:
    # a single request can legitimately retry for ~14 minutes (10 attempts,
    # backoff capped at 300s) without emitting an event.
    stale_job_minutes: int = 60
    # A re-delivered task (the previous worker died) may take over a `running`
    # job once it has been this quiet. Must stay well above the runner's 5-minute
    # heartbeat, or a live job could be stolen from itself.
    stale_reclaim_minutes: int = 10

    # Notifications
    slack_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "logvault@example.com"
    notification_max_retries: int = 3
    notification_retry_delay_seconds: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
