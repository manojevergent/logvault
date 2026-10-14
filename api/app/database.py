"""SQLAlchemy engine, session factory, and declarative base.

Phase 1 wires the connection and a session dependency; concrete models arrive
in later phases (see CLAUDE_CODE_PROMPT.md §4).
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    # SQLAlchemy's default (5 + 10 overflow) is small for an API whose pages
    # poll every few seconds across 60-180 engineers; a queued checkout waits
    # pool_timeout seconds and then errors, which reads as "the API is down".
    pool_size=20,
    max_overflow=20,
    pool_timeout=10,
    pool_recycle=1800,  # below Postgres/proxy idle timeouts, so no dead sockets
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
