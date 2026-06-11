"""
B5 — Rate limiter partagé dans Redis

La limite doit tenir quel que soit le worker (compteur Redis), avec
fallback local par process si Redis est indisponible.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web', 'backend'))

pytest.importorskip("fastapi")


@pytest.fixture(scope="module")
def srv():
    import server
    return server


@pytest.fixture(autouse=True)
def small_limit(srv, monkeypatch):
    monkeypatch.setattr(srv, "_RATE_LIMIT", 5)
    monkeypatch.setattr(srv, "_rate_buckets", {})


def _redis_available():
    try:
        import redis as _sync_redis
        return _sync_redis.Redis(
            host='localhost', port=6379,
            password=os.environ.get('REDIS_PASSWORD') or None,
            socket_connect_timeout=2).ping()
    except Exception:
        return False


class TestLocalFallback:
    def test_local_blocks_over_limit(self, srv):
        ip = "10.0.0.1"
        for _ in range(5):
            assert srv._check_rate_limit_local(ip) is True
        assert srv._check_rate_limit_local(ip) is False

    def test_redis_down_falls_back_to_local(self, srv, monkeypatch):
        class BrokenPool:
            def pipeline(self):
                raise ConnectionError("redis down")

        monkeypatch.setattr(srv, "redis_pool", BrokenPool())
        # ne bloque pas tout le trafic : le fallback local répond
        assert asyncio.run(srv._check_rate_limit("10.0.0.2")) is True

    def test_no_redis_pool_uses_local(self, srv, monkeypatch):
        monkeypatch.setattr(srv, "redis_pool", None)
        ip = "10.0.0.3"
        for _ in range(5):
            assert asyncio.run(srv._check_rate_limit(ip)) is True
        assert asyncio.run(srv._check_rate_limit(ip)) is False


class TestSharedRedisCounter:
    def test_limit_shared_across_workers(self, srv, monkeypatch):
        """Deux 'workers' (états locaux distincts) partagent le compteur Redis."""
        if not _redis_available():
            pytest.skip("Redis indisponible")
        ip = "203.0.113.7"
        key = f"{srv.MA_PREFIX}:ratelimit:{ip}"

        async def scenario():
            import redis.asyncio as aredis
            client = aredis.Redis(
                host='localhost', port=6379,
                password=os.environ.get('REDIS_PASSWORD') or None,
                decode_responses=True, socket_connect_timeout=2)
            await client.delete(key)
            try:
                monkeypatch.setattr(srv, "redis_pool", client)
                allowed = 0
                # worker 1 : 3 requêtes
                for _ in range(3):
                    if await srv._check_rate_limit(ip):
                        allowed += 1
                # worker 2 simulé : état local vidé, MÊME Redis
                srv._rate_buckets.clear()
                for _ in range(3):
                    if await srv._check_rate_limit(ip):
                        allowed += 1
                # limite 5 globale → 5 acceptées sur 6, pas 6
                assert allowed == 5
                # 7e requête refusée
                assert await srv._check_rate_limit(ip) is False
                # la clé expire (fenêtre)
                ttl = await client.ttl(key)
                assert 0 < ttl <= srv._RATE_WINDOW
            finally:
                await client.delete(key)
                await client.aclose()

        asyncio.run(scenario())
