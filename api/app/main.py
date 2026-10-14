"""LogVault API entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings, placeholder_secrets
from app.deps import get_current_user
from app.logging_config import configure_logging, get_logger
from app.routers import (
    admin,
    auth,
    credentials,
    health,
    indexes,
    jobs,
    labels,
    log_formats,
    schedules,
    templates,
)

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger("logvault.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to serve with a guessable secret rather than warn about it: a known
    # jwt_secret means forged admin tokens and forged download links, and a
    # warning in a log nobody reads is how it survived this long.
    if stale := placeholder_secrets(settings):
        raise RuntimeError(
            f"refusing to start: {', '.join(stale)} still set to a shipped placeholder. "
            "Generate real values (e.g. `openssl rand -base64 48`) and set them in .env."
        )
    log.info("api.startup", environment=settings.environment, version=__version__)
    yield
    log.info("api.shutdown")


app = FastAPI(
    title="LogVault API",
    version=__version__,
    description="Internal Last9 log extraction platform.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_auth_dep = [Depends(get_current_user)]

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(credentials.router, dependencies=_auth_dep)
app.include_router(indexes.router, dependencies=_auth_dep)
app.include_router(jobs.router, dependencies=_auth_dep)
app.include_router(jobs.public_router)  # /download (signed URL) + /progress (SSE) do their own auth
app.include_router(schedules.router, dependencies=_auth_dep)
app.include_router(labels.router, dependencies=_auth_dep)
app.include_router(admin.router, dependencies=_auth_dep)
app.include_router(templates.router, dependencies=_auth_dep)
app.include_router(log_formats.router, dependencies=_auth_dep)


@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    return {"name": "LogVault API", "version": __version__, "docs": "/docs"}
