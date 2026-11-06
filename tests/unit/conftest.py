import fnmatch
from unittest.mock import AsyncMock

import pytest
from fastapi_cache import FastAPICache

from app import cache as response_cache


class FakeRedis:
    """Redis-shaped, byte-preserving fake with failure injection and command tracking."""

    def __init__(self):
        self.entries = {}
        self.ttls = {}
        self.fail = False
        self.calls = 0
        self.unlinked = []
        self.close = AsyncMock()
        self.connection_pool = type("Pool", (), {"disconnect": AsyncMock()})()

    def check(self):
        self.calls += 1
        if self.fail:
            raise ConnectionError("offline (credentials must not be logged)")

    async def ping(self):
        self.check()
        return True

    def pipeline(self, **kwargs):
        redis = self

        class Pipeline:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def ttl(self, key):
                self.key = key
                return self

            def get(self, key):
                return self

            async def execute(self):
                redis.check()
                return redis.ttls.get(self.key, -2), redis.entries.get(self.key)

        return Pipeline()

    async def set(self, key, value, ex):
        self.check()
        self.entries[key] = value
        self.ttls[key] = ex

    async def info(self, section):
        self.check()
        assert section == "memory"
        return {"used_memory": 1024, "maxmemory": 268435456}

    async def scan_iter(self, match, count):
        self.check()
        assert count == 500
        for key in list(self.entries):
            if fnmatch.fnmatch(key, match):
                yield key.encode()

    async def unlink(self, *keys):
        self.check()
        deleted = 0
        for key in keys:
            text = key.decode() if isinstance(key, bytes) else key
            self.unlinked.append(text)
            if text in self.entries:
                self.entries.pop(text)
                self.ttls.pop(text, None)
                deleted += 1
        return deleted


@pytest.fixture
def cache_redis(monkeypatch):
    redis = FakeRedis()
    backend = response_cache.FailOpenRedisBackend(redis)
    monkeypatch.setattr(response_cache, "_backend", backend)
    monkeypatch.setattr(response_cache, "policy", response_cache.CachePolicy())
    FastAPICache.reset()
    FastAPICache.init(
        backend,
        prefix="mdh",
        coder=response_cache.MdhJsonCoder,
        key_builder=response_cache.mdh_key_builder,
    )
    yield redis
    response_cache._disable_cache()
