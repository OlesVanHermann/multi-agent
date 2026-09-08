"""
D2 — Périmètre de l'extension Chrome CDP

Le manifest est réduit aux permissions réellement utilisées par le code
(debugger, tabs, nativeMessaging, alarms), sans host_permissions :
chrome.debugger n'en a pas besoin et l'extension n'injecte aucun
content script. Le native host reste confiné à 127.0.0.1 et à l'ID
exact de l'extension.
"""
import json
import os
import re

BASE = os.path.join(os.path.dirname(__file__), '..')
EXT_DIR = os.path.join(BASE, 'framework', 'cdp-bridge', 'extension')
HOST_DIR = os.path.join(BASE, 'framework', 'cdp-bridge', 'native-host')

ALLOWED_PERMISSIONS = {"debugger", "tabs", "nativeMessaging", "alarms"}


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _manifest():
    return json.loads(_read(os.path.join(EXT_DIR, 'manifest.json')))


def _extension_js():
    return _read(os.path.join(EXT_DIR, 'background.js')) + \
           _read(os.path.join(EXT_DIR, 'popup.js'))


class TestManifestScope:
    def test_no_host_permissions(self):
        m = _manifest()
        assert not m.get("host_permissions"), \
            "host_permissions doit rester vide (chrome.debugger n'en requiert pas)"
        assert "<all_urls>" not in _read(os.path.join(EXT_DIR, 'manifest.json'))

    def test_permissions_minimal_whitelist(self):
        perms = set(_manifest()["permissions"])
        assert perms <= ALLOWED_PERMISSIONS, \
            f"permissions hors whitelist D2 : {perms - ALLOWED_PERMISSIONS}"

    def test_no_unused_permissions(self):
        perms = set(_manifest()["permissions"])
        for p in ("activeTab", "downloads", "scripting", "pageCapture", "storage"):
            assert p not in perms, f"permission inutilisée présente : {p}"

    def test_manifest_v3(self):
        assert _manifest()["manifest_version"] == 3


class TestCodeMatchesPermissions:
    """Chaque permission gardée est utilisée ; aucune API retirée n'est appelée."""

    def test_kept_permissions_are_used(self):
        js = _extension_js()
        assert "chrome.debugger." in js
        assert "chrome.tabs." in js
        assert "chrome.runtime.connectNative" in js
        assert "chrome.alarms." in js

    def test_removed_apis_not_called(self):
        js = _extension_js()
        for api in ("chrome.scripting.", "chrome.downloads.",
                    "chrome.storage.", "chrome.pageCapture."):
            assert api not in js, f"API appelée sans permission : {api}"


class TestNativeHostIsolation:
    def test_allowed_origins_pinned_to_extension_id(self):
        tpl = json.loads(_read(os.path.join(HOST_DIR, 'com.cdpbridge.host.json.template')))
        origins = tpl["allowed_origins"]
        assert len(origins) == 1
        assert re.fullmatch(r"chrome-extension://__EXTENSION_ID__/", origins[0])
        assert tpl["type"] == "stdio"

    def test_http_server_binds_loopback_only(self):
        src = _read(os.path.join(HOST_DIR, 'cdp-bridge-host.js'))
        assert 'server.listen(PORT, "127.0.0.1"' in src
        assert 'listen(PORT, "0.0.0.0"' not in src
