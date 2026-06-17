"""
B5 — Rate limiter partagé dans Redis

La limite doit tenir quel que soit le worker (compteur Redis), avec
fallback local par process si Redis est indisponible.
Depuis B1, le limiteur vit dans multi_agent.ratelimit et l'état partagé
(redis_pool) dans multi_agent.state.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web', 'backend'))

pytest.importorskip("fastapi")


@pytest.fixture(scope="module")
def rl():
    from multi_agent import ratelimit
    return ratelimit


@pytest.fixture(scope="module")
def st():
    from multi_agent import state
    return state


@pytest.fixture(autouse=True)
def small_limit(rl, monkeypatch):
    monkeypatch.setattr(rl, "_RATE_LIMIT", 5)
    monkeypatch.setattr(rl, "_rate_buckets", {})


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
    def test_local_blocks_over_limit(self, rl):
        ip = "10.0.0.1"
        for _ in range(5):
            assert rl._check_rate_limit_local(ip) is True
        assert rl._check_rate_limit_local(ip) is False

    def test_redis_down_falls_back_to_local(self, rl, st, monkeypatch):
        class BrokenPool:
            def pipeline(self):
                raise ConnectionError("redis down")

        monkeypatch.setattr(st, "redis_pool", BrokenPool())
        # ne bloque pas tout le trafic : le fallback local répond
        assert asyncio.run(rl._check_rate_limit("10.0.0.2")) is True

    def test_no_redis_pool_uses_local(self, rl, st, monkeypatch):
        monkeypatch.setattr(st, "redis_pool", None)
        ip = "10.0.0.3"
        for _ in range(5):
            assert asyncio.run(rl._check_rate_limit(ip)) is True
        assert asyncio.run(rl._check_rate_limit(ip)) is False


class TestSharedRedisCounter:
    def test_limit_shared_across_workers(self, rl, st, monkeypatch):
        """Deux 'workers' (états locaux distincts) partagent le compteur Redis."""
        if not _redis_available():
            pytest.skip("Redis indisponible")
        from multi_agent import config as cfg
        ip = "203.0.113.7"
        key = f"{cfg.MA_PREFIX}:ratelimit:{ip}"

        async def scenario():
            import redis.asyncio as aredis
            client = aredis.Redis(
                host='localhost', port=6379,
                password=os.environ.get('REDIS_PASSWORD') or None,
                decode_responses=True, socket_connect_timeout=2)
            await client.delete(key)
            try:
                monkeypatch.setattr(st, "redis_pool", client)
                allowed = 0
                # worker 1 : 3 requêtes
                for _ in range(3):
                    if await rl._check_rate_limit(ip):
                        allowed += 1
                # worker 2 simulé : état local vidé, MÊME Redis
                rl._rate_buckets.clear()
                for _ in range(3):
                    if await rl._check_rate_limit(ip):
                        allowed += 1
                # limite 5 globale → 5 acceptées sur 6, pas 6
                assert allowed == 5
                # 7e requête refusée
                assert await rl._check_rate_limit(ip) is False
                # la clé expire (fenêtre)
                ttl = await client.ttl(key)
                assert 0 < ttl <= rl._RATE_WINDOW
            finally:
                await client.delete(key)
                await client.aclose()

        asyncio.run(scenario())


class _StubWebSocket:
    """WebSocket minimal : juste ce que lisent les handlers avant accept()."""

    def __init__(self):
        from types import SimpleNamespace
        self.headers = {}
        self.client = SimpleNamespace(host="203.0.113.9")
        self.query_params = {}
        self.cookies = {}
        self.close_code = None
        self.accepted = False

    async def accept(self):
        # _reject() accepte avant de fermer pour que le navigateur reçoive le
        # vrai code 4xxx (au lieu d'un 1006 générique sur close-avant-accept).
        self.accepted = True

    async def close(self, code=1000):
        self.close_code = code


class TestWsCloseCodes:
    """G2 — dépassement de limite sur les endpoints WS : fermeture immédiate
    avec le code dédié (4002 sur /ws/agent), avant origin/auth. Sous la
    limite, la requête atteint la barrière suivante (auth → 4001)."""

    def test_over_limit_closes_4002(self, rl, st, monkeypatch):
        from multi_agent.routers.ws import websocket_agent_output
        monkeypatch.setattr(st, "redis_pool", None)  # compteur local
        monkeypatch.setattr(rl, "_RATE_LIMIT", 0)    # tout dépasse
        ws = _StubWebSocket()
        asyncio.run(websocket_agent_output(ws, "300"))
        assert ws.close_code == 4002

    def test_under_limit_reaches_auth_gate(self, st, monkeypatch):
        from multi_agent.routers.ws import websocket_agent_output
        monkeypatch.setattr(st, "redis_pool", None)
        # limite à 5 (fixture small_limit) : la 1re requête passe le rate
        # limiter et échoue plus loin, sur l'auth (4001) — pas sur 4002
        ws = _StubWebSocket()
        asyncio.run(websocket_agent_output(ws, "300"))
        assert ws.close_code == 4001

    def test_status_endpoint_over_limit_closes_1008(self, rl, st, monkeypatch):
        from multi_agent.routers.ws import websocket_status
        monkeypatch.setattr(st, "redis_pool", None)
        monkeypatch.setattr(rl, "_RATE_LIMIT", 0)
        ws = _StubWebSocket()
        asyncio.run(websocket_status(ws))
        assert ws.close_code == 1008
