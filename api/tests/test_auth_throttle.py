"""Login throttle: repeated failures lock an email out for a fixed window.

These sessions reach production Last9 credentials for every region, and the
login endpoint had no attempt counter at all.
"""

from __future__ import annotations

import pytest

from app.routers import auth


class _FakeRedis:
    """Enough of Redis for the throttle. `down=True` makes every call raise."""

    def __init__(self, down: bool = False) -> None:
        self.store: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.down = down

    def _check(self) -> None:
        if self.down:
            raise ConnectionError("redis is down")

    def get(self, key):
        self._check()
        return self.store.get(key)

    def incr(self, key):
        self._check()
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def expire(self, key, ttl):
        self._check()
        self.ttls[key] = ttl

    def delete(self, key):
        self._check()
        self.store.pop(key, None)


@pytest.fixture(autouse=True)
def plaintext_passwords(monkeypatch):
    """Throttle tests should not ride on the hashing backend.

    They also cannot: passlib 1.7.4 cannot drive bcrypt >= 4.1, so a dev box with
    a newer bcrypt than the image pins (4.0.1) fails inside `_hash` before
    reaching anything this file is about.
    """
    monkeypatch.setattr(auth, "_verify", lambda pw, hashed: pw == hashed)


@pytest.fixture
def redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(auth, "get_redis", lambda: fake)
    return fake


def _seed_user(client, password: str = "correct-horse") -> None:
    from app.models import User

    db = client.session_factory()
    db.add(
        User(
            id=9,
            email="dev@example.com",
            name="Dev",
            hashed_password=password,
            role="member",
        )
    )
    db.commit()
    db.close()


def _login(client, password: str):
    return client.post("/auth/login", json={"email": "dev@example.com", "password": password})


def test_five_failures_then_lockout(client, redis) -> None:
    _seed_user(client)
    for _ in range(5):
        assert _login(client, "wrong").status_code == 401

    resp = _login(client, "wrong")
    assert resp.status_code == 429
    assert "15 minutes" in resp.json()["detail"]

    # Locked out even with the right password — otherwise the throttle is a
    # speed bump an attacker walks straight past on the winning guess.
    assert _login(client, "correct-horse").status_code == 429


def test_the_lockout_window_does_not_extend_itself(client, redis) -> None:
    _seed_user(client)
    for _ in range(5):
        _login(client, "wrong")
    _login(client, "wrong")  # while locked out
    assert redis.ttls[auth._fail_key("dev@example.com")] == 900


def test_a_successful_login_clears_the_counter(client, redis) -> None:
    _seed_user(client)
    for _ in range(3):
        _login(client, "wrong")
    assert _login(client, "correct-horse").status_code == 200
    assert redis.store == {}


def test_the_counter_is_case_insensitive(client, redis) -> None:
    """Otherwise five tries per capitalisation is not a limit at all."""
    _seed_user(client)
    for email in ("dev@example.com", "DEV@example.com", "Dev@Example.Com"):
        for _ in range(2):
            client.post("/auth/login", json={"email": email, "password": "wrong"})
    assert (
        client.post(
            "/auth/login", json={"email": "DEV@EXAMPLE.COM", "password": "wrong"}
        ).status_code
        == 429
    )


def test_an_unreachable_redis_fails_open(client, monkeypatch) -> None:
    """A broken throttle that locks every engineer out is the worse outage."""
    monkeypatch.setattr(auth, "get_redis", lambda: _FakeRedis(down=True))
    _seed_user(client)
    for _ in range(10):
        assert _login(client, "wrong").status_code == 401
    assert _login(client, "correct-horse").status_code == 200
