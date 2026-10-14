"""Shared test helpers: build httpx clients backed by scripted MockTransports.

Using httpx's built-in MockTransport (no extra deps) exercises real request
construction — URL, query params, headers, and JSON body.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable

from cryptography.fernet import Fernet

# Set before any app.config import (settings are cached).
os.environ.setdefault("LAST9_ENCRYPTION_KEY", Fernet.generate_key().decode())
# NOT setdefault: a real DATABASE_URL is already set in any container that also
# runs the actual worker (docker-compose sets it for every service), so
# setdefault was a no-op there and tests using the `worker_db` fixture were
# silently drop_all()/create_all()-ing the REAL production database with the
# worker's incomplete mirrored table defs. Force the test DB unconditionally.
os.environ["DATABASE_URL"] = (
    f"sqlite:///{os.path.join(tempfile.gettempdir(), 'logvault_worker_test.db')}"
)
os.environ["STORAGE_DIR"] = tempfile.mkdtemp()

import httpx
import pytest

API_BASE = "https://app.last9.io/api/v4"
ORG = "evergentapse1"


def mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def worker_db():
    """Fresh Core tables on the test SQLite DB for each test."""
    from app import db
    from app.config import get_settings

    url = get_settings().database_url
    # Defense in depth: never drop/create tables against anything but the
    # isolated test DB, no matter how it ended up configured.
    assert url.startswith("sqlite:"), f"refusing to touch a non-test database: {url}"
    db.metadata.drop_all(db.engine())
    db.metadata.create_all(db.engine())
    yield db


def query_response(rows: list[tuple[str, str]], *, nested: bool = True) -> httpx.Response:
    """A 200 query response carrying ``rows`` as ``[timestamp, raw_line]`` values.

    ``nested=True`` uses the documented ``data.data.result`` shape (§2.8).
    """
    values = [[ts, line] for ts, line in rows]
    result = [{"stream": {"app": "svc"}, "values": values}] if values else None
    inner = {"result": result}
    body = {"data": {"data": inner}} if nested else {"data": inner}
    return httpx.Response(200, json=body)


def empty_response(*, nested: bool = True) -> httpx.Response:
    return query_response([], nested=nested)


def read_export(path: str) -> list[str]:
    """An export's lines, whether or not it was compressed on completion.

    Exports are zipped when a job finishes (`zip_exports` defaults on), so tests
    that open `output_file_path` as text are reading a ZIP container. Reading
    through the archive here keeps the compressed path — the one that actually
    runs in production — covered rather than switched off.
    """
    import zipfile

    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            return zf.read(zf.namelist()[0]).decode("utf-8").splitlines()
    with open(path, encoding="utf-8") as fh:
        return fh.read().splitlines()
