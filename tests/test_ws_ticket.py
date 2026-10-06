"""
B4 — Ticket WebSocket à usage unique (plus de JWT en query string)

POST /api/ws-ticket (authentifié) pose un ticket opaque en Redis (TTL 30 s) ;
les handlers WS le consomment atomiquement (DEL) : non rejouable, expirant.
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web', 'backend'))

pytest.importorskip("fastapi")
import httpx  # noqa: E402


class _StubRedis:
    def __init__(self):
        self.store = {}
        self.ttls = {}

    async def setex(self, key, ttl, val):
        self.store[key] = val
        self.ttls[key] = ttl

    async def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0


@pytest.fixture(scope="module")
def srv():
    import server
    return server


@pytest.fixture
def client(srv):
    transport = httpx.ASGITransport(app=srv.app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def st():
    from multi_agent import state
    return state


@pytest.fixture
def stub_redis(st, monkeypatch):
    stub = _StubRedis()
    monkeypatch.setattr(st, "redis_pool", stub)
    return stub


@pytest.fixture
def good_token(srv, monkeypatch):
    monkeypatch.setattr(srv, "_verify_jwt_minimal", lambda t: t == "good")
    return "good"


@pytest.mark.anyio
class TestWsTicketEndpoint:
    async def test_requires_auth(self, client):
        async with client:
            r = await client.post("/api/ws-ticket")
        assert r.status_code == 401

    async def test_creates_ticket_in_redis(self, client, stub_redis, good_token):
        from multi_agent import config as cfg
        async with client:
            r = await client.post("/api/ws-ticket",
                                  headers={"Authorization": f"Bearer {good_token}"})
        assert r.status_code == 200
        ticket = r.json()["ticket"]
        key = f"wsticket:{ticket}"
        assert key in stub_redis.store
        assert stub_redis.ttls[key] == 30

    async def test_503_without_redis(self, client, st, good_token, monkeypatch):
        monkeypatch.setattr(st, "redis_pool", None)
        async with client:
            r = await client.post("/api/ws-ticket",
                                  headers={"Authorization": f"Bearer {good_token}"})
        assert r.status_code == 503


@pytest.mark.anyio
class TestTicketConsumption:
    async def test_valid_once_then_replay_refused(self, stub_redis):
        from multi_agent import config as cfg
        from multi_agent.routers.ws import _consume_ws_ticket
        ticket = "a" * 43
        stub_redis.store[f"wsticket:{ticket}"] = "1"
        assert await _consume_ws_ticket(ticket) is True
        # Rejoué → refusé (le DEL a invalidé le ticket)
        assert await _consume_ws_ticket(ticket) is False

    async def test_expired_or_unknown_refused(self, stub_redis):
        assert await _consume_ws_ticket_helper("b" * 43) is False

    async def test_bad_format_refused(self, stub_redis):
        assert await _consume_ws_ticket_helper("short") is False
        assert await _consume_ws_ticket_helper("x" * 43 + ";DEL *") is False
        assert await _consume_ws_ticket_helper("") is False

    async def test_no_redis_refused(self, st, monkeypatch):
        monkeypatch.setattr(st, "redis_pool", None)
        assert await _consume_ws_ticket_helper("c" * 43) is False


async def _consume_ws_ticket_helper(ticket):
    from multi_agent.routers.ws import _consume_ws_ticket
    return await _consume_ws_ticket(ticket)


@pytest.mark.anyio
class TestWsAuthenticated:
    def _ws(self, ticket=None, cookies=None):
        return SimpleNamespace(
            query_params={"ticket": ticket} if ticket else {},
            cookies=cookies or {},
        )

    async def test_valid_ticket_accepted(self, stub_redis):
        from multi_agent import config as cfg
        from multi_agent.routers.ws import _ws_authenticated
        ticket = "d" * 43
        stub_redis.store[f"wsticket:{ticket}"] = "1"
        assert await _ws_authenticated(self._ws(ticket=ticket)) is True

    async def test_cookie_fallback(self, stub_redis, srv, monkeypatch):
        import multi_agent.routers.ws as ws_mod
        monkeypatch.setattr(ws_mod, "_verify_jwt_minimal", lambda t: t == "good")
        assert await ws_mod._ws_authenticated(
            self._ws(cookies={"ma_access": "good"})) is True
        assert await ws_mod._ws_authenticated(
            self._ws(cookies={"ma_access": "evil"})) is False

    async def test_nothing_refused(self, stub_redis):
        from multi_agent.routers.ws import _ws_authenticated
        assert await _ws_authenticated(self._ws()) is False
