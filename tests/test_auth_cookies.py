"""
B3 — JWT en cookie HttpOnly + anti-CSRF double-submit

Le proxy /auth/* pose les jetons en cookies HttpOnly et renvoie un corps
sans jetons ; le middleware accepte le cookie ma_access et exige le header
X-CSRF-Token (== cookie ma_csrf) sur les requêtes mutatives en auth cookie.
"""
import base64
import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web', 'backend'))

pytest.importorskip("fastapi")
import httpx  # noqa: E402


def _b64url(data: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    return raw.rstrip("=")


def _fake_jwt(claims: dict) -> str:
    return f"{_b64url({'alg': 'RS256'})}.{_b64url(claims)}.fakesig"


@pytest.fixture(scope="module")
def srv():
    import server
    return server


@pytest.fixture
def client(srv):
    transport = httpx.ASGITransport(app=srv.app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def good_token(srv, monkeypatch):
    """Le middleware accepte uniquement le jeton 'good'."""
    monkeypatch.setattr(srv, "_verify_jwt_minimal", lambda t: t == "good")
    return "good"


class TestTokenCookies:
    def _upstream(self, payload: dict):
        content = json.dumps(payload).encode()
        return SimpleNamespace(json=lambda: payload, content=content, status_code=200)

    def _request(self, scheme="http"):
        return SimpleNamespace(url=SimpleNamespace(scheme=scheme), headers={})

    def test_tokens_moved_to_httponly_cookies(self):
        from multi_agent.routers.system import _token_response_with_cookies
        access = _fake_jwt({
            "preferred_username": "alice", "email": "a@b.c",
            "name": "Alice", "realm_access": {"roles": ["admin"]},
        })
        resp = _token_response_with_cookies(self._request(), self._upstream({
            "access_token": access, "refresh_token": "r-secret",
            "expires_in": 300, "refresh_expires_in": 1800, "token_type": "Bearer",
        }))
        body = json.loads(resp.body)
        assert "access_token" not in body and "refresh_token" not in body
        assert body["user"]["username"] == "alice"
        assert body["user"]["roles"] == ["admin"]
        assert body["expires_in"] == 300

        cookies = resp.headers.getlist("set-cookie")
        access_c = next(c for c in cookies if c.startswith("ma_access="))
        refresh_c = next(c for c in cookies if c.startswith("ma_refresh="))
        csrf_c = next(c for c in cookies if c.startswith("ma_csrf="))
        assert "HttpOnly" in access_c and "SameSite=strict" in access_c
        assert "HttpOnly" in refresh_c and "Path=/auth" in refresh_c
        assert "r-secret" in refresh_c
        # ma_csrf lisible par le JS (double-submit) : PAS HttpOnly
        assert "HttpOnly" not in csrf_c

    def test_secure_flag_on_https(self):
        from multi_agent.routers.system import _token_response_with_cookies
        access = _fake_jwt({"preferred_username": "alice"})
        resp = _token_response_with_cookies(self._request(scheme="https"), self._upstream({
            "access_token": access, "expires_in": 300,
        }))
        for c in resp.headers.getlist("set-cookie"):
            assert "Secure" in c

    def test_non_json_upstream_passthrough(self):
        from multi_agent.routers.system import _token_response_with_cookies

        def _boom():
            raise ValueError("not json")

        upstream = SimpleNamespace(json=_boom, content=b"oops", status_code=200)
        resp = _token_response_with_cookies(self._request(), upstream)
        assert resp.body == b"oops"
        assert not resp.headers.getlist("set-cookie")


@pytest.mark.anyio
class TestCookieAuthMiddleware:
    async def test_no_token_rejected(self, client):
        async with client:
            r = await client.get("/api/agents")
        assert r.status_code == 401

    async def test_cookie_auth_get_accepted(self, client, good_token):
        async with client:
            r = await client.get("/api/agents",
                                 headers={"cookie": f"ma_access={good_token}"})
        assert r.status_code == 200

    async def test_bad_cookie_rejected(self, client, good_token):
        async with client:
            r = await client.get("/api/agents",
                                 headers={"cookie": "ma_access=evil"})
        assert r.status_code == 401

    async def test_cookie_post_without_csrf_rejected(self, client, good_token):
        async with client:
            r = await client.post("/api/chat", json={"text": "hi"},
                                  headers={"cookie": f"ma_access={good_token}"})
        assert r.status_code == 403

    async def test_cookie_post_with_wrong_csrf_rejected(self, client, good_token):
        async with client:
            r = await client.post(
                "/api/chat", json={"text": "hi"},
                headers={"cookie": f"ma_access={good_token}; ma_csrf=abc",
                         "X-CSRF-Token": "xyz"})
        assert r.status_code == 403

    async def test_cookie_post_with_csrf_accepted(self, client, good_token):
        async with client:
            r = await client.post(
                "/api/chat", json={"text": "hi"},
                headers={"cookie": f"ma_access={good_token}; ma_csrf=abc",
                         "X-CSRF-Token": "abc"})
        # Passe l'auth + CSRF (503 = Redis absent dans ce test, pas un refus auth)
        assert r.status_code not in (401, 403)

    async def test_bearer_post_exempt_from_csrf(self, client, good_token):
        async with client:
            r = await client.post(
                "/api/chat", json={"text": "hi"},
                headers={"Authorization": f"Bearer {good_token}"})
        assert r.status_code not in (401, 403)
