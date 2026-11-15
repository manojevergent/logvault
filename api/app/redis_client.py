"""Shared Redis client accessor."""

from __future__ import annotations

from functools import lru_cache

import redis

from app.config import get_settings


@lru_cache
def get_redis() -> redis.Redis:
    settings = get_settings()
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


@lru_cache
def get_broker_redis() -> redis.Redis:
    """Client for the Celery broker database.

    The beat singleton lock and the task queue live in the broker DB, which is
    a different database index from ``REDIS_URL``. Anything that inspects them
    must use this client, not ``get_redis()``.
    """
    settings = get_settings()
    return redis.Redis.from_url(
        settings.celery_broker_url, decode_responses=True, socket_timeout=2
    )
