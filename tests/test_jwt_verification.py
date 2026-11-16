"""Tests B2 — durcissement JWT : audience (aud/azp) + issuer stricts + expiration.

La signature est produite localement (RSA 2048) et PyJWKClient est monkeypatché
pour retourner cette clé, afin de tester _verify_jwt_minimal sans Keycloak.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web', 'backend'))

pyjwt = pytest.importorskip("jwt")
pytest.importorskip("cryptography")

from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def srv():
    import server
    return server


@pytest.fixture
def patched_jwks(srv, rsa_key, monkeypatch):
    """PyJWKClient.get_signing_key_from_jwt retourne notre clé publique locale."""
    class FakeSigningKey:
        key = rsa_key.public_key()

    class FakePyJWKClient:
        def __init__(self, *a, **kw):
            pass

        def get_signing_key_from_jwt(self, token):
            return FakeSigningKey()

    monkeypatch.setattr(pyjwt, "PyJWKClient", FakePyJWKClient)
    return rsa_key


def _make_token(rsa_key, srv, *, iss=None, aud="account", azp=None, exp_delta=300, **extra):
    claims = {
        "iss": iss if iss is not None else srv._EXPECTED_ISSUER,
        "aud": aud,
        "exp": int(time.time()) + exp_delta,
        "iat": int(time.time()) - 5,
        "sub": "test-user",
    }
    if azp is not None:
        claims["azp"] = azp
    claims.update(extra)
    return pyjwt.encode(claims, rsa_key, algorithm="RS256")


class TestJwtHardening:
    def test_valid_token_azp_accepted(self, srv, patched_jwks):
        token = _make_token(patched_jwks, srv, azp=srv._EXPECTED_AUDIENCE)
        assert srv._verify_jwt_minimal(token) is True

    def test_valid_token_aud_accepted(self, srv, patched_jwks):
        token = _make_token(patched_jwks, srv, aud=srv._EXPECTED_AUDIENCE)
        assert srv._verify_jwt_minimal(token) is True

    def test_other_client_rejected(self, srv, patched_jwks):
        token = _make_token(patched_jwks, srv, aud="account", azp="other-client")
        assert srv._verify_jwt_minimal(token) is False

    def test_missing_audience_and_azp_rejected(self, srv, patched_jwks):
        token = _make_token(patched_jwks, srv, aud="account")
        assert srv._verify_jwt_minimal(token) is False

    def test_evil_issuer_suffix_rejected(self, srv, patched_jwks):
        evil = "https://evil.tld/realms/multi-agent"
        token = _make_token(patched_jwks, srv, iss=evil, azp=srv._EXPECTED_AUDIENCE)
        assert srv._verify_jwt_minimal(token) is False

    def test_wrong_issuer_rejected(self, srv, patched_jwks):
        token = _make_token(patched_jwks, srv, iss="http://localhost:8080/realms/other",
                            azp=srv._EXPECTED_AUDIENCE)
        assert srv._verify_jwt_minimal(token) is False

    def test_expired_token_rejected(self, srv, patched_jwks):
        token = _make_token(patched_jwks, srv, azp=srv._EXPECTED_AUDIENCE, exp_delta=-120)
        assert srv._verify_jwt_minimal(token) is False

    def test_bad_signature_rejected(self, srv, patched_jwks):
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = _make_token(other_key, srv, azp=srv._EXPECTED_AUDIENCE)
        assert srv._verify_jwt_minimal(token) is False

    def test_garbage_token_rejected(self, srv, patched_jwks):
        assert srv._verify_jwt_minimal("not-a-jwt") is False


class TestIssuerConfig:
    """Issuer public découplé de l'URL interne (KEYCLOAK_PUBLIC_URL / KEYCLOAK_ISSUER)."""

    def _reload(self):
        import importlib
        from multi_agent import config as cfg
        return importlib.reload(cfg)

    def test_public_url_drives_issuer(self, monkeypatch):
        monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", "https://pub.example.com")
        cfg = self._reload()
        assert cfg._EXPECTED_ISSUER == f"https://pub.example.com/realms/{cfg.KEYCLOAK_REALM}"
        monkeypatch.delenv("KEYCLOAK_PUBLIC_URL")
        self._reload()

    def test_explicit_issuer_wins_over_public_url(self, monkeypatch):
        monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", "https://pub.example.com")
        monkeypatch.setenv("KEYCLOAK_ISSUER", "https://autre.example.com/realms/x")
        cfg = self._reload()
        assert cfg._EXPECTED_ISSUER == "https://autre.example.com/realms/x"
        monkeypatch.delenv("KEYCLOAK_ISSUER")
        monkeypatch.delenv("KEYCLOAK_PUBLIC_URL")
        self._reload()

    def test_empty_vars_fall_back_to_internal_url(self, monkeypatch):
        """Compose passe KEYCLOAK_PUBLIC_URL/ISSUER vides quand non configurés."""
        monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", "")
        monkeypatch.setenv("KEYCLOAK_ISSUER", "")
        cfg = self._reload()
        assert cfg._EXPECTED_ISSUER == f"{cfg.KEYCLOAK_URL}/realms/{cfg.KEYCLOAK_REALM}"
        monkeypatch.delenv("KEYCLOAK_PUBLIC_URL")
        monkeypatch.delenv("KEYCLOAK_ISSUER")
        self._reload()
