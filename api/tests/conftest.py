"""Test fixtures: a valid encryption key + an in-memory SQLite DB wired into the
app via dependency override. No Postgres/Redis needed."""

from __future__ import annotations

import os

from cryptography.fernet import Fernet

# Must be set before app.config is imported (settings are cached).
os.environ.setdefault("LAST9_ENCRYPTION_KEY", Fernet.generate_key().decode())
# Keep the catalog empty by default so tests that count or match formats are not
# polluted by the patterns their fixtures create. The registry tests opt in.
os.environ.setdefault("AUTO_REGISTER_FORMATS", "false")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402,F401  (register tables)
from app.database import Base, get_db  # noqa: E402
from app.deps import get_current_user  # noqa: E402
from app.main import app  # noqa: E402
from app.models import IndexTarget, Last9Credential, User  # noqa: E402


def _test_user() -> User:
    return User(id=1, email="test@example.com", name="Test User", role="admin")


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = _test_user
    test_client = TestClient(app)
    test_client.session_factory = TestingSession  # for tests that seed rows directly
    yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


@pytest.fixture
def member_client(client):
    """The same app, signed in as a non-admin — for asserting role guards."""
    app.dependency_overrides[get_current_user] = lambda: User(
        id=2, email="member@example.com", name="Member", role="member"
    )
    return client


@pytest.fixture
def job_refs(client):
    """Credential 1 + index target 1, which every job-creating test posts. Opt-in
    rather than seeded for all: the credential/index list tests count rows."""
    db = client.session_factory()
    db.add(
        Last9Credential(
            id=1,
            label="test",
            org_slug="testorg",
            encrypted_refresh_token="x",
            refresh_token_last4="abcd",
        )
    )
    db.add(
        IndexTarget(
            id=1,
            name="test-index",
            region_code="ap-southeast-1",
            full_index_string="testorg:UMServices",
            credential_id=1,
        )
    )
    db.commit()
    db.close()
