"""
Tests unitaires pour chrome-bridge (anciennement chrome-shared.py)
EF-003 — Couverture : isolation tabs, commandes CDP, gestion erreurs WebSocket

Tests sur la nouvelle structure modulaire (EF-005) :
  - redis_integration : mapping agent→tab
  - tab_manager : création/fermeture tabs, identification agent
  - cdp_connection : connexion WebSocket, validation Chrome
  - cdp_commands : navigate, screenshot, click, timeout

Réf spec 342 : CA-004 (≥300 LOC, 5+ fonctions CDP couvertes avec mocks)
CT-003 : Port 9222 préservé
"""
import pytest
import json
import sys
import os
import time
from unittest.mock import MagicMock, patch, PropertyMock

# Add refactoring modules to path
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'refactoring'
)))


# =============================================================================
# Tests redis_integration.py
# =============================================================================

class TestRedisIntegration:
    """EF-003 — Tests du module redis_integration"""

    @patch('redis_integration.r')
    def test_get_agent_tab_found(self, mock_r):
        """Récupère le tab_id d'un agent existant (EF-003)"""
        from redis_integration import get_agent_tab
        mock_r.get.return_value = "ABC123DEF456"
        result = get_agent_tab("300")
        mock_r.get.assert_called_with("ma:chrome:tab:300")
        assert result == "ABC123DEF456"

    @patch('redis_integration.r')
    def test_get_agent_tab_not_found(self, mock_r):
        """Retourne None si aucun mapping n'existe (EF-003)"""
        from redis_integration import get_agent_tab
        mock_r.get.return_value = None
        assert get_agent_tab("999") is None

    @patch('redis_integration.r', None)
    def test_get_agent_tab_redis_unavailable(self):
        """Retourne None si Redis n'est pas disponible (EF-003)"""
        from redis_integration import get_agent_tab
        assert get_agent_tab("300") is None

    @patch('redis_integration.r')
    def test_set_agent_tab(self, mock_r):
        """Stocke le mapping agent→tab dans Redis (EF-003)"""
        from redis_integration import set_agent_tab
        result = set_agent_tab("300", "TAB_ID_123")
        mock_r.set.assert_called_with("ma:chrome:tab:300", "TAB_ID_123")
        assert result is True

    @patch('redis_integration.r', None)
    def test_set_agent_tab_redis_unavailable(self):
        """Retourne False si Redis n'est pas disponible (EF-003)"""
        from redis_integration import set_agent_tab
        assert set_agent_tab("300", "TAB_ID") is False

    @patch('redis_integration.r')
    def test_del_agent_tab(self, mock_r):
        """Supprime le mapping agent→tab (EF-003)"""
        from redis_integration import del_agent_tab
        del_agent_tab("300")
        mock_r.delete.assert_called_with("ma:chrome:tab:300")

    @patch('redis_integration.r')
    def test_list_all_mappings(self, mock_r):
        """Liste tous les mappings agent→tab (EF-003)"""
        from redis_integration import list_all_mappings
        mock_r.keys.return_value = ["ma:chrome:tab:300", "ma:chrome:tab:301"]
        mock_r.get.side_effect = lambda k: {
            "ma:chrome:tab:300": "TAB_A",
            "ma:chrome:tab:301": "TAB_B"
        }[k]
        result = list_all_mappings()
        assert result == {"300": "TAB_A", "301": "TAB_B"}

    @patch('redis_integration.r')
    def test_cleanup_stale_target(self, mock_r):
        """Nettoie un mapping stale en supprimant la clé Redis (EF-003)"""
        from redis_integration import cleanup_stale_target
        mock_r.get.return_value = "STALE_TARGET_ID_ABCDEF"
        cleanup_stale_target("300")
        mock_r.delete.assert_called_with("ma:chrome:tab:300")


# =============================================================================
# Tests tab_manager.py
# =============================================================================

class TestTabManager:
    """EF-003 — Tests du module tab_manager"""

    @patch.dict(os.environ, {"AGENT_ID": "300"})
    def test_get_my_agent_id_from_env(self):
        """Détecte l'agent_id depuis la variable d'environnement (EF-003)"""
        from tab_manager import get_my_agent_id
        assert get_my_agent_id() == "300"

    @patch.dict(os.environ, {}, clear=True)
    @patch('tab_manager.subprocess.run')
    def test_get_my_agent_id_from_tmux(self, mock_run):
        """Détecte l'agent_id depuis le nom de session tmux (EF-003)"""
        # Remove AGENT_ID from env if present
        os.environ.pop("AGENT_ID", None)
        from tab_manager import get_my_agent_id
        mock_run.return_value = MagicMock(stdout="ma-agent-301\n")
        assert get_my_agent_id() == "301"

    @patch.dict(os.environ, {}, clear=True)
    @patch('tab_manager.subprocess.run')
    def test_get_my_agent_id_from_tmux_alt_format(self, mock_run):
        """Détecte l'agent_id au format 'agent-XXX' (EF-003)"""
        os.environ.pop("AGENT_ID", None)
        from tab_manager import get_my_agent_id
        mock_run.return_value = MagicMock(stdout="agent-302\n")
        assert get_my_agent_id() == "302"

    @patch('tab_manager.urllib.request.urlopen')
    def test_get_tabs_success(self, mock_urlopen):
        """Liste les tabs Chrome via /json endpoint (EF-003)"""
        from tab_manager import get_tabs
        tabs_data = [
            {"id": "TAB1", "type": "page", "url": "https://example.com"},
            {"id": "TAB2", "type": "page", "url": "about:blank"},
        ]
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(tabs_data).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = get_tabs()
        assert len(result) == 2
        assert result[0]["id"] == "TAB1"

    @patch('tab_manager.urllib.request.urlopen')
    def test_get_tabs_chrome_not_running(self, mock_urlopen):
        """Retourne liste vide si Chrome n'est pas accessible (EF-003)"""
        from tab_manager import get_tabs
        mock_urlopen.side_effect = Exception("Connection refused")
        assert get_tabs() == []

    @patch('tab_manager.get_tabs')
    def test_count_page_tabs(self, mock_get_tabs):
        """Compte uniquement les tabs de type 'page' (EF-003)"""
        from tab_manager import count_page_tabs
        mock_get_tabs.return_value = [
            {"id": "T1", "type": "page"},
            {"id": "T2", "type": "service_worker"},
            {"id": "T3", "type": "page"},
        ]
        assert count_page_tabs() == 2

    @patch('tab_manager.urllib.request.urlopen')
    def test_create_tab_success(self, mock_urlopen):
        """Crée un nouvel onglet Chrome via /json/new (EF-003)"""
        from tab_manager import create_tab
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"id": "NEW_TAB_ID"}).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = create_tab("https://example.com")
        assert result == "NEW_TAB_ID"

    @patch('tab_manager.urllib.request.urlopen')
    def test_create_tab_failure(self, mock_urlopen):
        """Retourne None si la création de tab échoue (EF-003)"""
        from tab_manager import create_tab
        mock_urlopen.side_effect = Exception("Chrome error")
        assert create_tab() is None

    @patch('tab_manager.urllib.request.urlopen')
    def test_close_tab_by_id_success(self, mock_urlopen):
        """Ferme un onglet via /json/close/{id} (EF-003)"""
        from tab_manager import close_tab_by_id
        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response
        assert close_tab_by_id("TAB_123") is True

    @patch('tab_manager.urllib.request.urlopen')
    def test_close_tab_by_id_failure(self, mock_urlopen):
        """Retourne False si la fermeture échoue (EF-003)"""
        from tab_manager import close_tab_by_id
        mock_urlopen.side_effect = Exception("Not found")
        assert close_tab_by_id("INVALID") is False


# =============================================================================
# Tests cdp_connection.py
# =============================================================================

class TestCDPConnection:
    """EF-003 — Tests du module cdp_connection (classe CDP de base)"""

    @patch('cdp_connection.urllib.request.urlopen')
    def test_check_chrome_running_true(self, mock_urlopen):
        """Détecte Chrome actif sur port 9222 (EF-003)"""
        from cdp_connection import check_chrome_running
        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response
        assert check_chrome_running() is True

    @patch('cdp_connection.urllib.request.urlopen')
    def test_check_chrome_running_false(self, mock_urlopen):
        """Détecte Chrome inactif (EF-003)"""
        from cdp_connection import check_chrome_running
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        assert check_chrome_running() is False

    @patch('cdp_connection.get_tabs')
    def test_validate_target_exists(self, mock_get_tabs):
        """Valide qu'un target_id existe dans Chrome (EF-003)"""
        from cdp_connection import validate_target
        mock_get_tabs.return_value = [
            {"id": "TAB_VALID", "type": "page"},
            {"id": "TAB_OTHER", "type": "page"},
        ]
        assert validate_target("TAB_VALID") is True

    @patch('cdp_connection.get_tabs')
    def test_validate_target_stale(self, mock_get_tabs):
        """Détecte un target_id stale (n'existe plus) (EF-003)"""
        from cdp_connection import validate_target
        mock_get_tabs.return_value = [{"id": "TAB_OTHER", "type": "page"}]
        assert validate_target("TAB_GONE") is False

    def test_cdp_init(self):
        """CDP s'initialise avec tab_id, ws=None, msg_id=0 (EF-003)"""
        from cdp_connection import CDP
        cdp = CDP("TAB_123")
        assert cdp.tab_id == "TAB_123"
        assert cdp.ws is None
        assert cdp.msg_id == 0

    def test_cdp_close_no_ws(self):
        """CDP.close() ne crashe pas si ws est None (EF-003)"""
        from cdp_connection import CDP
        cdp = CDP("TAB_123")
        cdp.close()  # Should not raise

    def test_cdp_close_with_ws(self):
        """CDP.close() ferme le WebSocket correctement (EF-003)"""
        from cdp_connection import CDP
        cdp = CDP("TAB_123")
        cdp.ws = MagicMock()
        cdp.close()
        cdp.ws.close.assert_called_once()

    def test_cdp_send_increments_msg_id(self):
        """CDP.send() auto-incrémente le message ID (EF-003)"""
        from cdp_connection import CDP
        cdp = CDP("TAB_123")
        cdp.ws = MagicMock()

        # Mock recv to return matching response
        cdp.ws.recv.return_value = json.dumps({"id": 1, "result": {}})
        cdp.send("Page.enable")
        assert cdp.msg_id == 1

        cdp.ws.recv.return_value = json.dumps({"id": 2, "result": {"value": "ok"}})
        cdp.send("Runtime.evaluate", {"expression": "1+1"})
        assert cdp.msg_id == 2

    def test_cdp_send_raises_on_error(self):
        """CDP.send() lève une exception si Chrome retourne une erreur (EF-003)"""
        from cdp_connection import CDP
        cdp = CDP("TAB_123")
        cdp.ws = MagicMock()
        cdp.ws.recv.return_value = json.dumps({
            "id": 1,
            "error": {"message": "Element not found"}
        })
        with pytest.raises(Exception, match="Element not found"):
            cdp.send("DOM.querySelector", {"selector": "#missing"})

    def test_cdp_send_timeout(self):
        """CDP.send() lève une exception après timeout (EF-003)"""
        from cdp_connection import CDP
        cdp = CDP("TAB_123")
        cdp.ws = MagicMock()

        # Simulate WebSocket timeout on every recv
        import websocket as ws_module
        if ws_module:
            cdp.ws.recv.side_effect = ws_module.WebSocketTimeoutException()
            with pytest.raises(Exception, match="CDP timeout"):
                cdp.send("Page.navigate", {"url": "https://example.com"}, timeout=1)

    def test_cdp_evaluate(self):
        """CDP.evaluate() exécute du JS et retourne la valeur (EF-003)"""
        from cdp_connection import CDP
        cdp = CDP("TAB_123")
        cdp.ws = MagicMock()
        cdp.ws.recv.return_value = json.dumps({
            "id": 1,
            "result": {"result": {"type": "string", "value": "Hello World"}}
        })
        result = cdp.evaluate("document.title")
        assert result == "Hello World"

    def test_cdp_port_constant(self):
        """Le port CDP est 9222 (CT-003) (EF-003)"""
        from cdp_connection import CHROME_PORT
        assert CHROME_PORT == 9222


# =============================================================================
# Tests cdp_commands.py (CDPCommands)
# =============================================================================

class TestCDPCommands:
    """EF-003 — Tests des commandes CDP de haut niveau"""

    def _make_cdp(self):
        """Helper : crée un CDPCommands avec mock WebSocket"""
        from cdp_commands import CDPCommands
        cdp = CDPCommands("MOCK_TAB")
        cdp.ws = MagicMock()
        return cdp

    def _mock_response(self, cdp, result=None):
        """Helper : configure le mock pour retourner une réponse CDP"""
        resp = {"id": cdp.msg_id + 1, "result": result or {}}
        cdp.ws.recv.return_value = json.dumps(resp)

    def test_navigate(self):
        """CDPCommands.navigate() envoie Page.enable + Page.navigate (EF-003)"""
        cdp = self._make_cdp()
        calls = []

        def mock_send(data):
            calls.append(json.loads(data))

        cdp.ws.send = mock_send
        cdp.ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {}}),
            json.dumps({"id": 2, "result": {}}),
        ]
        cdp.navigate("https://example.com")

        assert len(calls) == 2
        assert calls[0]["method"] == "Page.enable"
        assert calls[1]["method"] == "Page.navigate"
        assert calls[1]["params"]["url"] == "https://example.com"

    def test_get_title(self):
        """CDPCommands.get_title() retourne le titre via JS (EF-003)"""
        cdp = self._make_cdp()
        cdp.ws.recv.return_value = json.dumps({
            "id": 1,
            "result": {"result": {"type": "string", "value": "Example"}}
        })
        assert cdp.get_title() == "Example"

    def test_get_url(self):
        """CDPCommands.get_url() retourne l'URL courante (EF-003)"""
        cdp = self._make_cdp()
        cdp.ws.recv.return_value = json.dumps({
            "id": 1,
            "result": {"result": {"type": "string", "value": "https://example.com"}}
        })
        assert cdp.get_url() == "https://example.com"

    def test_click_element_found(self):
        """CDPCommands.click() envoie les événements souris (EF-003)"""
        cdp = self._make_cdp()
        calls_sent = []

        def mock_send(data):
            calls_sent.append(json.loads(data))

        cdp.ws.send = mock_send
        # First call returns coordinates, then 2 mouse events
        cdp.ws.recv.side_effect = [
            json.dumps({
                "id": 1,
                "result": {"result": {"type": "object", "value": {"x": 100, "y": 200}}}
            }),
            json.dumps({"id": 2, "result": {}}),  # mousePressed
            json.dumps({"id": 3, "result": {}}),  # mouseReleased
        ]
        cdp.click("#button")

        methods = [c["method"] for c in calls_sent]
        assert "Runtime.evaluate" in methods
        assert "Input.dispatchMouseEvent" in methods

    def test_click_element_not_found(self):
        """CDPCommands.click() lève une exception si élément absent (EF-003)"""
        cdp = self._make_cdp()
        cdp.ws.recv.return_value = json.dumps({
            "id": 1,
            "result": {"result": {"type": "object", "value": None}}
        })
        with pytest.raises(Exception, match="Element not found"):
            cdp.click("#nonexistent")

    def test_screenshot_viewport(self):
        """CDPCommands.screenshot() capture le viewport (EF-003)"""
        import base64
        cdp = self._make_cdp()
        # Return base64-encoded fake PNG
        fake_png = base64.b64encode(b"\x89PNG\r\n\x1a\n fake").decode()
        cdp.ws.recv.return_value = json.dumps({
            "id": 1, "result": {"data": fake_png}
        })
        data = cdp.screenshot(full_page=False)
        assert isinstance(data, bytes)
        assert data[:4] == b"\x89PNG"

    def test_type_text(self):
        """CDPCommands.type_text() focus + clear + insert (EF-003)"""
        cdp = self._make_cdp()
        calls = []
        cdp.ws.send = lambda d: calls.append(json.loads(d))
        cdp.ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {"result": {"value": None}}}),  # focus
            json.dumps({"id": 2, "result": {"result": {"value": ""}}}),    # clear
            json.dumps({"id": 3, "result": {}}),                           # insertText
        ]
        cdp.type_text("#input", "hello")

        methods = [c["method"] for c in calls]
        assert "Runtime.evaluate" in methods  # focus + clear
        assert "Input.insertText" in methods

    def test_press_key_enter(self):
        """CDPCommands.press_key('enter') envoie keyDown+keyUp (EF-003)"""
        cdp = self._make_cdp()
        calls = []
        cdp.ws.send = lambda d: calls.append(json.loads(d))
        cdp.ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {}}),  # keyDown
            json.dumps({"id": 2, "result": {}}),  # keyUp
        ]
        cdp.press_key("enter")

        assert len(calls) == 2
        assert calls[0]["params"]["key"] == "Enter"
        assert calls[0]["params"]["type"] == "keyDown"
        assert calls[1]["params"]["type"] == "keyUp"

    def test_scroll_directions(self):
        """CDPCommands.scroll() supporte 4 directions (EF-003)"""
        for direction in ["down", "up", "bottom", "top"]:
            cdp = self._make_cdp()
            cdp.ws.recv.return_value = json.dumps({
                "id": 1, "result": {"result": {"value": None}}
            })
            cdp.scroll(direction)  # Should not raise

    def test_wait_element_found(self):
        """CDPCommands.wait_element() retourne True si trouvé (EF-003)"""
        cdp = self._make_cdp()
        cdp.ws.recv.return_value = json.dumps({
            "id": 1, "result": {"result": {"type": "boolean", "value": True}}
        })
        assert cdp.wait_element("#exists", timeout=1) is True

    def test_wait_element_timeout(self):
        """CDPCommands.wait_element() lève Exception après timeout (EF-003)"""
        cdp = self._make_cdp()
        cdp.ws.recv.return_value = json.dumps({
            "id": 1, "result": {"result": {"type": "boolean", "value": False}}
        })
        with pytest.raises(Exception, match="Timeout waiting for"):
            cdp.wait_element("#missing", timeout=0.5)

    def test_get_images_empty(self):
        """CDPCommands.get_images() retourne liste vide si pas d'images (EF-003)"""
        cdp = self._make_cdp()
        cdp.ws.recv.return_value = json.dumps({
            "id": 1, "result": {"result": {"type": "object", "value": []}}
        })
        result = cdp.get_images()
        assert result == []

    def test_hover(self):
        """CDPCommands.hover() envoie mouseMoved sans click (EF-003)"""
        cdp = self._make_cdp()
        calls = []
        cdp.ws.send = lambda d: calls.append(json.loads(d))
        cdp.ws.recv.side_effect = [
            json.dumps({
                "id": 1,
                "result": {"result": {"type": "object", "value": {"x": 50, "y": 100}}}
            }),
            json.dumps({"id": 2, "result": {}}),  # mouseMoved
        ]
        cdp.hover("#element")

        mouse_calls = [c for c in calls if c.get("method") == "Input.dispatchMouseEvent"]
        assert len(mouse_calls) == 1
        assert mouse_calls[0]["params"]["type"] == "mouseMoved"

    def test_safe_sel_injection(self):
        """Vérifie que _safe_sel bloque l'injection CSS/JS (R-P1CLOSE, R-SANIT)."""
        from cdp_commands import CDPCommands
        cdp = CDPCommands("MOCK_TAB")

        # Single quote injection attempt
        malicious = "'; alert('xss'); '"
        result = cdp._safe_sel(malicious)
        assert "\\'" in result
        assert result == "\\'; alert(\\'xss\\'); \\'"

        # Backslash injection
        assert cdp._safe_sel("a\\b") == "a\\\\b"

        # Newline injection
        assert cdp._safe_sel("a\nb") == "a\\nb"

        # Carriage return injection
        assert cdp._safe_sel("a\rb") == "a\\rb"

        # Combined attack vector
        combined = "div'); document.cookie='stolen\n"
        result = cdp._safe_sel(combined)
        assert "\n" not in result
        assert "\\'" in result
        assert result == "div\\'); document.cookie=\\'stolen\\n"

    def test_safe_sel_used_in_click(self):
        """Vérifie que click() utilise _safe_sel pour le sélecteur (R-P1CLOSE)."""
        cdp = self._make_cdp()
        calls = []
        cdp.ws.send = lambda d: calls.append(json.loads(d))
        # Return null coords to trigger not-found (simpler than full flow)
        cdp.ws.recv.return_value = json.dumps({
            "id": 1, "result": {"result": {"type": "object", "value": None}}
        })
        # Malicious selector with quote
        try:
            cdp.click("div'; alert(1); '")
        except Exception:
            pass
        # Verify the JS sent contains escaped selector
        if calls:
            js_code = calls[0].get("params", {}).get("expression", "")
            assert "\\'" in js_code or "alert(1)" not in js_code
