"""
Montage statique inconditionnel (web/backend/server.py)

Un restart du backend pendant un rebuild du frontend (dist/ absent ou
partiel) ne doit ni faire échouer l'import, ni laisser un backend sans
routes frontend jusqu'au restart suivant. La résolution se fait à la
requête : 503 Retry-After tant qu'index.html manque, 200 dès qu'il
réapparaît — sans redémarrage.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web', 'backend'))

pytest.importorskip("fastapi")
import httpx  # noqa: E402


def _purge_backend_modules():
    saved = {}
    for name in list(sys.modules):
        if name == "server" or name == "multi_agent" or name.startswith("multi_agent."):
            saved[name] = sys.modules.pop(name)
    return saved


@pytest.fixture
def srv_dist(tmp_path, monkeypatch):
    """server importé avec un dist/ ABSENT (fenêtre de rebuild)."""
    dist = tmp_path / "dist"  # volontairement jamais créé ici
    monkeypatch.setenv("FRONTEND_DIR", str(dist))
    saved = _purge_backend_modules()
    try:
        import server
        yield server, dist
    finally:
        _purge_backend_modules()
        sys.modules.update(saved)


@pytest.fixture
def client(srv_dist):
    server, dist = srv_dist
    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test"), dist


@pytest.mark.anyio
class TestStaticMountRebuildWindow:
    async def test_import_survit_sans_dist(self, srv_dist):
        _, dist = srv_dist
        assert not dist.exists()  # l'import n'a ni planté ni exigé dist/

    async def test_index_503_retry_after_pendant_rebuild(self, client):
        c, _ = client
        r = await c.get("/")
        assert r.status_code == 503
        assert r.headers.get("Retry-After") == "5"

    async def test_asset_absent_404_pas_crash(self, client):
        c, _ = client
        r = await c.get("/assets/app.js")
        assert r.status_code == 404

    async def test_resolution_a_la_requete_apres_rebuild(self, client):
        c, dist = client
        # le frontend apparaît APRÈS le démarrage du backend
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<html>ok</html>")
        (dist / "assets" / "app.js").write_text("console.log(1)")
        assert (await c.get("/")).status_code == 200
        assert (await c.get("/assets/app.js")).status_code == 200
        # route SPA quelconque → index.html
        assert (await c.get("/agents/300")).status_code == 200
