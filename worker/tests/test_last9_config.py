"""The worker reads the Last9 endpoint an admin saved in the UI.

The worker runs baked images with no bind-mount, so a BYOC host change has to be
picked up from the database at job start — not from an env var that only changes
on a rebuild.
"""

from __future__ import annotations

from app import last9_config
from app.config import get_settings


def test_falls_back_to_the_env_default(worker_db):
    expected = get_settings().last9_api_base.rstrip("/")
    assert last9_config.api_base(worker_db.engine()) == expected


def test_reads_the_saved_endpoint(worker_db):
    with worker_db.engine().begin() as conn:
        conn.execute(
            worker_db.app_settings.insert().values(
                key="last9", value={"api_base": "https://l9.byoc.example.com/api/v4"}
            )
        )
    assert last9_config.api_base(worker_db.engine()) == "https://l9.byoc.example.com/api/v4"


def test_a_failed_read_falls_back_instead_of_raising(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(last9_config.db, "engine", boom)
    expected = get_settings().last9_api_base.rstrip("/")
    assert last9_config.api_base() == expected
