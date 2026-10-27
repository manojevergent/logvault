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
    # Wrap Excel-coerced values (long ids, timestamps) as ="..." so a
    # spreadsheet keeps them verbatim. OFF by default: those quotes and the
    # leading `=` become literal data for a warehouse loading the CSV. Turn on
    # only for spreadsheet-first workflows.
    excel_escape: bool = False
    # Exports and pgdata share one host filesystem, so a job that fills the disk
    # does not just fail itself — it stops Postgres writing and takes every other
    # job, every schedule and every login down with it. Refuse to start below this.
    min_free_disk_gb: int = 10
    # A `running` job silent for this long is presumed dead. Generous on purpose:
    # a single request can legitimately retry for ~14 minutes (10 attempts,
    # backoff capped at 300s) without emitting an event.
    stale_job_minutes: int = 60

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
