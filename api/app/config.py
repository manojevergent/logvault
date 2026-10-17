"""Application configuration, loaded entirely from environment variables.

All config flows through `Settings`; nothing is hard-coded. Import the cached
`get_settings()` accessor rather than instantiating directly.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # Meta
    environment: str = "development"
    log_level: str = "INFO"

    # Infrastructure
    database_url: str = "postgresql+psycopg://logvault:change-me@localhost:5432/logvault"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"

    # Secrets
    last9_encryption_key: str = "replace-with-generated-fernet-key"
    jwt_secret: str = "replace-with-random-secret"

    # Last9 defaults (configurable, never hard-coded at call sites)
    default_org_slug: str = "evergentapse1"
    last9_api_base: str = "https://app.last9.io/api/v4"

    # CORS
    cors_origins: str = "http://localhost:3000"

    # Bootstrap admin (creates first user on startup if no users exist)
    initial_admin_email: str = ""
    initial_admin_password: str = ""

    # Google sign-in (OAuth authorization-code flow). Empty client id/secret
    # disables it entirely and the login page shows password auth only.
    google_client_id: str = ""
    google_client_secret: str = ""
    # Comma-separated Workspace domains allowed to sign in, e.g.
    # "evergent.com". Empty allows any Google account (verified email still
    # required) — set this before exposing the app beyond a trusted network.
    google_allowed_domains: str = ""
    # Public bases used to build the OAuth redirect URI and the post-login
    # landing page. redirect_uri sent to Google is
    # {public_api_base}/auth/google/callback and must match an Authorized
    # redirect URI in the Google Cloud console exactly.
    public_api_base: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:3001"

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def google_domain_list(self) -> list[str]:
        return [d.strip().lower() for d in self.google_allowed_domains.split(",") if d.strip()]

    # Storage
    storage_dir: str = "/data/exports"
    download_url_ttl_seconds: int = 604800
    export_retention_days: int = 30
    zip_exports: bool = True

    # Operational health (reported by /health/ops, not by /ready — a dead worker
    # or a missing backup must not pull this process out of rotation).
    backup_dir: str = "/backups"
    backup_stale_hours: int = 36
    worker_beat_stale_seconds: int = 300

    # Login throttle. The window starts at the first failure and does not extend,
    # so a locked-out account always recovers on its own.
    login_max_attempts: int = 5
    login_lockout_seconds: int = 900

    # Notifications
    slack_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "logvault@example.com"
    notification_max_retries: int = 3
    notification_retry_delay_seconds: int = 5

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


# Placeholder values that shipped as defaults or examples. `jwt_secret` also
# signs download URLs, so a known value here forges both admin sessions and
# links to any job's export — checked in every environment, not just
# production: ENVIRONMENT is routinely left unset, so a production-only guard
# is exactly the guard that never fires.
_PLACEHOLDER_SECRETS: dict[str, set[str]] = {
    "jwt_secret": {"replace-with-random-secret", "dev-secret-change-in-production", ""},
    "last9_encryption_key": {"replace-with-generated-fernet-key", ""},
}


def placeholder_secrets(settings: Settings) -> list[str]:
    """Names of secrets still set to a shipped placeholder."""
    return [
        name
        for name, placeholders in _PLACEHOLDER_SECRETS.items()
        if getattr(settings, name) in placeholders
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
