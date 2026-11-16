"""
B7 — Durcissement de /api/upload et /api/logs/frontend

Upload : taille bornée, nom assaini (pas de ../), répertoire dédié,
liste blanche d'extensions optionnelle. Logs frontend : corps borné,
events objets uniquement, plafond journalier.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web', 'backend'))

pytest.importorskip("fastapi")
import httpx  # noqa: E402


@pytest.fixture(scope="module")
def srv():
    import server
    return server


@pytest.fixture
def sysmod():
    from multi_agent.routers import system
    return system


@pytest.fixture
def cfg():
    from multi_agent import config
    return config


@pytest.fixture
def client(srv, good_token):
    transport = httpx.ASGITransport(app=srv.app, raise_app_exceptions=False)
    return httpx.AsyncClient(
        transport=transport, base_url="http://test",
        headers={"Authorization": "Bearer good"})


@pytest.fixture
def good_token(srv, monkeypatch):
    monkeypatch.setattr(srv, "_verify_jwt_minimal", lambda t: t == "good")
    return "good"


@pytest.fixture
def upload_dir(cfg, tmp_path, monkeypatch):
    d = tmp_path / "uploads"
    monkeypatch.setattr(cfg, "UPLOAD_DIR", d)
    return d


@pytest.mark.anyio
class TestUploadHardening:
    async def test_upload_lands_in_dedicated_dir(self, client, upload_dir):
        async with client:
            r = await client.post("/api/upload",
                                  files={"file": ("notes.txt", b"hello")})
        assert r.status_code == 200
        data = r.json()
        assert data["path"].startswith(str(upload_dir))
        assert data["size"] == 5
        files = list(upload_dir.iterdir())
        assert len(files) == 1 and files[0].read_bytes() == b"hello"

    async def test_traversal_filename_neutralized(self, client, upload_dir):
        async with client:
            r = await client.post("/api/upload",
                                  files={"file": ("../../etc/x", b"data")})
        assert r.status_code == 200
        path = r.json()["path"]
        assert ".." not in path
        assert path.startswith(str(upload_dir))

    async def test_too_large_rejected_and_removed(self, client, upload_dir,
                                                  sysmod, monkeypatch):
        monkeypatch.setattr(sysmod, "MAX_UPLOAD_SIZE", 10)
        async with client:
            r = await client.post("/api/upload",
                                  files={"file": ("big.bin", b"x" * 100)})
        assert r.status_code == 413
        assert list(upload_dir.iterdir()) == []

    async def test_extension_whitelist(self, client, upload_dir, cfg, monkeypatch):
        monkeypatch.setattr(cfg, "UPLOAD_ALLOWED_EXT", {"txt"})
        async with client:
            r1 = await client.post("/api/upload",
                                   files={"file": ("evil.exe", b"MZ")})
            r2 = await client.post("/api/upload",
                                   files={"file": ("ok.txt", b"ok")})
        assert r1.status_code == 415
        assert r2.status_code == 200


@pytest.mark.anyio
class TestFrontendLogsHardening:
    @pytest.fixture
    def log_dir(self, cfg, tmp_path, monkeypatch):
        d = tmp_path / "frontend-logs"
        monkeypatch.setattr(cfg, "FRONTEND_LOG_DIR", d)
        return d

    async def test_normal_batch_written(self, client, log_dir):
        async with client:
            r = await client.post("/api/logs/frontend",
                                  json={"events": [{"type": "info", "msg": "a"}]})
        assert r.status_code == 200 and r.json()["written"] == 1
        content = next(log_dir.iterdir()).read_text()
        assert json.loads(content.strip())["msg"] == "a"

    async def test_oversized_body_rejected(self, client, log_dir,
                                           sysmod, monkeypatch):
        monkeypatch.setattr(sysmod, "MAX_FRONTEND_LOG_BODY", 100)
        async with client:
            r = await client.post("/api/logs/frontend",
                                  json={"events": [{"msg": "x" * 500}]})
        assert r.status_code == 413
        assert not log_dir.exists()

    async def test_non_object_events_rejected(self, client, log_dir):
        async with client:
            r1 = await client.post("/api/logs/frontend",
                                   json={"events": ["not-a-dict"]})
            r2 = await client.post("/api/logs/frontend",
                                   json={"events": [{}] * 21})
            r3 = await client.post("/api/logs/frontend", json=[1, 2])
        assert r1.status_code == 400
        assert r2.status_code == 400
        assert r3.status_code == 400

    async def test_daily_cap(self, client, log_dir):
        import time
        log_dir.mkdir(parents=True)
        date_str = time.strftime("%Y-%m-%d", time.gmtime())
        log_path = log_dir / f"frontend-{date_str}.jsonl"
        # Fichier sparse au-delà du plafond de 50 Mo
        with open(log_path, "wb") as f:
            f.truncate(51_000_000)
        async with client:
            r = await client.post("/api/logs/frontend",
                                  json={"events": [{"msg": "a"}]})
        assert r.status_code == 200 and r.json().get("capped") is True
        assert log_path.stat().st_size == 51_000_000
