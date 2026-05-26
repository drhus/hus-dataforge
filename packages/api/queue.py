"""Thin RQ wrapper. Workers live in packages/api/worker.py."""
from __future__ import annotations

from functools import lru_cache

import redis
from rq import Queue

from packages.api.settings import REDIS_URL


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    return redis.from_url(REDIS_URL)


@lru_cache(maxsize=1)
def get_queue() -> Queue:
    return Queue("dataforge", connection=get_redis())
