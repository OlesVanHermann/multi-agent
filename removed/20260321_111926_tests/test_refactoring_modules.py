"""
Tests unitaires pour les 4 modules du refactoring EF-005
Valide : cdp_connection, tab_manager, cdp_commands, redis_integration, __init__

Réf spec 342 : CA-006 (≤700 LOC/module), CT-003 (port 9222), CT-004 (pas de dep)
"""
import pytest
import os
import sys
import json
from unittest.mock import MagicMock, patch, PropertyMock

# Add refactoring to path for standalone imports
_REFACTORING = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'refactoring'))
sys.path.insert(0, _REFACTORING)


# === CA-006 : Taille des modules ===

class TestModuleSizeCA006:
    """CA-006 — Aucun module ne dépasse 700 LOC"""

    MODULE_FILES = [
        'cdp_connection.py',
        'tab_manager.py',
        'cdp_commands.py',
        'redis_integration.py',
    ]

    def test_all_modules_under_700_loc(self):
        """Chaque module EF-005 doit être ≤700 LOC (CA-006)"""
        for name in self.MODULE_FILES:
            path = os.path.join(_REFACTORING, name)
            assert os.path.isfile(path), f"{name} not found"
            with open(path) as f:
                loc = sum(1 for _ in f)
            assert loc <= 700, f"{name} has {loc} LOC, limit is 700"

    def test_init_exports_all_symbols(self):
        """__init__.py réexporte tous les symboles des 4 modules (EF-005)"""
        init_path = os.path.join(_REFACTORING, '__init__.py')
        with open(init_path) as f:
            content = f.read()
        expected = [
            'get_agent_tab', 'set_agent_tab', 'del_agent_tab',
            'list_all_mappings', 'cleanup_stale_target', 'REDIS_PREFIX',
            'get_my_agent_id', 'get_tabs', 'count_page_tabs',
            'create_tab', 'close_tab_by_id',
            'CDP', 'get_cdp', 'check_chrome_running', 'validate_target',
            'CHROME_PORT', 'CDPCommands',
        ]
        for sym in expected:
            assert sym in content, f"__init__.py missing re-export: {sym}"


# === redis_integration.py ===

class TestRedisIntegrationModule:
    """EF-005 Module 4 — redis_integration.py"""

    def test_redis_prefix_format(self):
        """REDIS_PREFIX suit le format ma:chrome:tab: (EF-005)"""
        from redis_integration import REDIS_PREFIX
        assert REDIS_PREFIX == "ma:chrome:tab:"

    @patch('redis_integration.r', None)
    def test_get_agent_tab_no_redis(self):
        """get_agent_tab retourne None si Redis indisponible (EF-005)"""
        from redis_integration import get_agent_tab
        assert get_agent_tab("300") is None

    @patch('redis_integration.r', None)
    def test_set_agent_tab_no_redis(self):
        """set_agent_tab retourne False si Redis indisponible (EF-005)"""
        from redis_integration import set_agent_tab
        assert set_agent_tab("300", "target123") is False

    @patch('redis_integration.r', None)
    def test_del_agent_tab_no_redis(self):
        """del_agent_tab ne crashe pas sans Redis (EF-005)"""
        from redis_integration import del_agent_tab
        del_agent_tab("300")  # Should not raise

    @patch('redis_integration.r', None)
    def test_list_all_mappings_no_redis(self):
        """list_all_mappings retourne {} sans Redis (EF-005)"""
        from redis_integration import list_all_mappings
        assert list_all_mappings() == {}

    @patch('redis_integration.r', None)
    def test_cleanup_stale_no_redis(self):
        """cleanup_stale_target ne crashe pas sans Redis (EF-005)"""
        from redis_integration import cleanup_stale_target
        cleanup_stale_target("300")  # Should not raise

    @patch('redis_integration.r')
    def test_get_agent_tab_hit(self, mock_r):
        """get_agent_tab retourne le target_id si présent (EF-005)"""
        mock_r.get.return_value = "ABC123"
        from redis_integration import get_agent_tab
        assert get_agent_tab("300") == "ABC123"
        mock_r.get.assert_called_with("ma:chrome:tab:300")

    @patch('redis_integration.r')
    def test_set_agent_tab_stores(self, mock_r):
        """set_agent_tab stocke la clé dans Redis (EF-005)"""
        from redis_integration import set_agent_tab
        result = set_agent_tab("300", "XYZ789")
        assert result is True
        mock_r.set.assert_called_with("ma:chrome:tab:300", "XYZ789")

    @patch('redis_integration.r')
    def test_del_agent_tab_deletes(self, mock_r):
        """del_agent_tab supprime la clé Redis (EF-005)"""
        from redis_integration import del_agent_tab
        del_agent_tab("300")
        mock_r.delete.assert_called_with("ma:chrome:tab:300")

    @patch('redis_integration.r')
    def test_list_all_mappings_returns_sorted(self, mock_r):
        """list_all_mappings retourne les mappings triés (EF-005)"""
        mock_r.keys.return_value = [
            "ma:chrome:tab:302", "ma:chrome:tab:300", "ma:chrome:tab:301"
        ]
        mock_r.get.side_effect = lambda k: {"ma:chrome:tab:300": "A", "ma:chrome:tab:301": "B", "ma:chrome:tab:302": "C"}[k]
        from redis_integration import list_all_mappings
        result = list_all_mappings()
        assert list(result.keys()) == ["300", "301", "302"]

    @patch('redis_integration.r')
    def test_cleanup_stale_target_deletes_old(self, mock_r):
        """cleanup_stale_target supprime un mapping obsolète (EF-005)"""
        mock_r.get.return_value = "OLD_TARGET"
        from redis_integration import cleanup_stale_target
        cleanup_stale_target("300")
        mock_r.delete.assert_called_with("ma:chrome:tab:300")


# === tab_manager.py ===

class TestTabManagerModule:
    """EF-005 Module 2 — tab_manager.py"""

    def test_chrome_port_constant(self):
        """CHROME_PORT vaut 9222 (CT-003)"""
        from tab_manager import CHROME_PORT
        assert CHROME_PORT == 9222

    @patch.dict(os.environ, {"AGENT_ID": "400"})
    def test_get_my_agent_id_env(self):
        """get_my_agent_id lit AGENT_ID de l'env en priorité (EF-005)"""
        from tab_manager import get_my_agent_id
        assert get_my_agent_id() == "400"

    @patch.dict(os.environ, {}, clear=True)
    @patch('tab_manager.subprocess.run')
    def test_get_my_agent_id_tmux_ma_prefix(self, mock_run):
        """get_my_agent_id parse le format ma-agent-XXX (EF-005)"""
        os.environ.pop("AGENT_ID", None)
        mock_run.return_value = MagicMock(stdout="ma-agent-305\n")
        from tab_manager import get_my_agent_id
        assert get_my_agent_id() == "305"

    @patch.dict(os.environ, {}, clear=True)
    @patch('tab_manager.subprocess.run')
    def test_get_my_agent_id_tmux_exception(self, mock_run):
        """get_my_agent_id retourne None si tmux échoue (EF-005)"""
        os.environ.pop("AGENT_ID", None)
        mock_run.side_effect = Exception("tmux not found")
        from tab_manager import get_my_agent_id
        assert get_my_agent_id() is None

    @patch('tab_manager.urllib.request.urlopen')
    def test_get_tabs_success(self, mock_urlopen):
        """get_tabs retourne la liste des onglets Chrome (EF-005)"""
        tabs_data = [
            {"id": "A", "type": "page", "url": "https://example.com"},
            {"id": "B", "type": "service_worker", "url": "chrome-extension://x"},
        ]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(tabs_data).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        from tab_manager import get_tabs
        result = get_tabs()
        assert len(result) == 2
        assert result[0]["id"] == "A"

    @patch('tab_manager.urllib.request.urlopen')
    def test_get_tabs_chrome_down(self, mock_urlopen):
        """get_tabs retourne [] si Chrome ne répond pas (EF-005)"""
        mock_urlopen.side_effect = Exception("Connection refused")
        from tab_manager import get_tabs
        assert get_tabs() == []

    @patch('tab_manager.get_tabs')
    def test_count_page_tabs_filters(self, mock_get_tabs):
        """count_page_tabs ne compte que les tabs de type page (EF-005)"""
        mock_get_tabs.return_value = [
            {"type": "page"}, {"type": "page"},
            {"type": "service_worker"}, {"type": "other"}
        ]
        from tab_manager import count_page_tabs
        assert count_page_tabs() == 2

    @patch('tab_manager.urllib.request.urlopen')
    def test_create_tab_encodes_url(self, mock_urlopen):
        """create_tab encode l'URL correctement (EF-005)"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"id": "NEW_TAB"}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        from tab_manager import create_tab
        result = create_tab("https://example.com/path?q=test")
        assert result == "NEW_TAB"

    @patch('tab_manager.urllib.request.urlopen')
    def test_close_tab_by_id_success(self, mock_urlopen):
        """close_tab_by_id retourne True en cas de succès (EF-005)"""
        mock_urlopen.return_value = MagicMock()
        from tab_manager import close_tab_by_id
        assert close_tab_by_id("TAB123") is True

    @patch('tab_manager.urllib.request.urlopen')
    def test_close_tab_by_id_failure(self, mock_urlopen):
        """close_tab_by_id retourne False en cas d'erreur (EF-005)"""
        mock_urlopen.side_effect = Exception("Not found")
        from tab_manager import close_tab_by_id
        assert close_tab_by_id("BAD_ID") is False


# === cdp_connection.py ===

class TestCDPConnectionModule:
    """EF-005 Module 1 — cdp_connection.py"""

    def test_exit_codes_defined(self):
        """Les codes de sortie sont définis correctement (EF-005)"""
        from cdp_connection import EXIT_OK, EXIT_ERROR, EXIT_CHROME_NOT_RUNNING
        from cdp_connection import EXIT_TARGET_STALE, EXIT_WEBSOCKET_FAILED
        assert EXIT_OK == 0
        assert EXIT_ERROR == 1
        assert EXIT_CHROME_NOT_RUNNING == 100
        assert EXIT_TARGET_STALE == 101
        assert EXIT_WEBSOCKET_FAILED == 102

    def test_cdp_init_state(self):
        """CDP.__init__ initialise ws=None, msg_id=0 (EF-005)"""
        from cdp_connection import CDP
        cdp = CDP("test_tab")
        assert cdp.tab_id == "test_tab"
        assert cdp.ws is None
        assert cdp.msg_id == 0

    @patch('cdp_connection.urllib.request.urlopen')
    def test_check_chrome_running_true(self, mock_urlopen):
        """check_chrome_running retourne True si Chrome répond (EF-005)"""
        mock_urlopen.return_value.__enter__ = MagicMock()
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        from cdp_connection import check_chrome_running
        assert check_chrome_running() is True

    @patch('cdp_connection.urllib.request.urlopen')
    def test_check_chrome_custom_port(self, mock_urlopen):
        """check_chrome_running accepte un port custom (EF-005)"""
        mock_urlopen.return_value.__enter__ = MagicMock()
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        from cdp_connection import check_chrome_running
        assert check_chrome_running(port=9333) is True
        call_url = mock_urlopen.call_args[0][0]
        assert "9333" in call_url

    @patch('cdp_connection.check_chrome_running', return_value=False)
    def test_require_chrome_running_exits(self, mock_check):
        """require_chrome_running quitte si Chrome down (EF-005)"""
        from cdp_connection import require_chrome_running, EXIT_CHROME_NOT_RUNNING
        with pytest.raises(SystemExit) as exc_info:
            require_chrome_running()
        assert exc_info.value.code == EXIT_CHROME_NOT_RUNNING

    @patch('cdp_connection.get_tabs')
    def test_validate_target_exists(self, mock_tabs):
        """validate_target retourne True si le target existe (EF-005)"""
        mock_tabs.return_value = [{"id": "ABC"}, {"id": "DEF"}]
        from cdp_connection import validate_target
        assert validate_target("ABC") is True

    @patch('cdp_connection.get_tabs')
    def test_validate_target_stale(self, mock_tabs):
        """validate_target retourne False si target disparu (EF-005)"""
        mock_tabs.return_value = [{"id": "ABC"}]
        from cdp_connection import validate_target
        assert validate_target("GONE") is False

    def test_cdp_close_no_ws(self):
        """CDP.close() ne crashe pas si ws est None (EF-005)"""
        from cdp_connection import CDP
        cdp = CDP("tab")
        cdp.close()  # Should not raise


# === cdp_commands.py ===

class TestCDPCommandsModule:
    """EF-005 Module 3 — cdp_commands.py"""

    def test_inherits_from_cdp(self):
        """CDPCommands hérite de CDP (EF-005)"""
        from cdp_commands import CDPCommands
        from cdp_connection import CDP
        assert issubclass(CDPCommands, CDP)

    def test_max_image_dim_constant(self):
        """MAX_IMAGE_DIM est défini (EF-005)"""
        from cdp_commands import MAX_IMAGE_DIM
        assert MAX_IMAGE_DIM == 1800

    def test_key_map_contains_standard_keys(self):
        """press_key supporte enter, tab, escape, backspace, arrows (EF-005)"""
        from cdp_commands import CDPCommands
        cdp = object.__new__(CDPCommands)
        cdp.ws = MagicMock()
        cdp.msg_id = 0
        # Access key_map inside press_key — verified by testing the method doesn't crash
        # when given known keys
        expected_keys = ["enter", "tab", "escape", "backspace", "delete",
                         "arrowup", "arrowdown", "arrowleft", "arrowright"]
        for key in expected_keys:
            # Just verify no KeyError; actual CDP calls are mocked
            cdp.send = MagicMock()
            cdp.press_key(key)
            assert cdp.send.call_count == 2  # keyDown + keyUp

    def test_scroll_directions(self):
        """scroll accepte down, up, bottom, top (EF-005)"""
        from cdp_commands import CDPCommands
        cdp = object.__new__(CDPCommands)
        cdp.evaluate = MagicMock()
        for direction in ["down", "up", "bottom", "top"]:
            cdp.scroll(direction)
        assert cdp.evaluate.call_count == 4

    def test_click_raises_on_missing_element(self):
        """click lève Exception si l'élément n'existe pas (EF-005)"""
        from cdp_commands import CDPCommands
        cdp = object.__new__(CDPCommands)
        cdp.evaluate = MagicMock(return_value=None)
        with pytest.raises(Exception, match="Element not found"):
            cdp.click("#nonexistent")

    def test_hover_raises_on_missing_element(self):
        """hover lève Exception si l'élément n'existe pas (EF-005)"""
        from cdp_commands import CDPCommands
        cdp = object.__new__(CDPCommands)
        cdp.evaluate = MagicMock(return_value=None)
        with pytest.raises(Exception, match="Element not found"):
            cdp.hover("#nonexistent")

    def test_click_text_raises_on_missing(self):
        """click_text lève Exception si le texte n'existe pas (EF-005)"""
        from cdp_commands import CDPCommands
        cdp = object.__new__(CDPCommands)
        cdp.evaluate = MagicMock(return_value=None)
        with pytest.raises(Exception, match="not found"):
            cdp.click_text("Missing Button")

    def test_dblclick_raises_on_missing(self):
        """dblclick lève Exception si l'élément n'existe pas (EF-005)"""
        from cdp_commands import CDPCommands
        cdp = object.__new__(CDPCommands)
        cdp.evaluate = MagicMock(return_value=None)
        with pytest.raises(Exception, match="Element not found"):
            cdp.dblclick("#gone")

    def test_wait_element_timeout(self):
        """wait_element lève Exception après timeout (EF-005)"""
        from cdp_commands import CDPCommands
        cdp = object.__new__(CDPCommands)
        cdp.evaluate = MagicMock(return_value=False)
        with pytest.raises(Exception, match="Timeout"):
            cdp.wait_element("#slow", timeout=0.1)

    def test_wait_hidden_timeout(self):
        """wait_hidden lève Exception après timeout (EF-005)"""
        from cdp_commands import CDPCommands
        cdp = object.__new__(CDPCommands)
        cdp.evaluate = MagicMock(return_value=True)
        with pytest.raises(Exception, match="Timeout"):
            cdp.wait_hidden("#sticky", timeout=0.1)

    def test_wait_text_timeout(self):
        """wait_text lève Exception après timeout (EF-005)"""
        from cdp_commands import CDPCommands
        cdp = object.__new__(CDPCommands)
        cdp.evaluate = MagicMock(return_value=False)
        with pytest.raises(Exception, match="Timeout"):
            cdp.wait_text("Never appears", timeout=0.1)

    def test_get_element_as_image_not_found(self):
        """get_element_as_image retourne None si élément absent (EF-005)"""
        from cdp_commands import CDPCommands
        cdp = object.__new__(CDPCommands)
        cdp.evaluate = MagicMock(return_value=None)
        result = cdp.get_element_as_image("#missing")
        assert result is None

    def test_navigate_calls_page_enable(self):
        """navigate appelle Page.enable puis Page.navigate (EF-005)"""
        from cdp_commands import CDPCommands
        cdp = object.__new__(CDPCommands)
        cdp.send = MagicMock()
        cdp.navigate("https://example.com")
        calls = [c[0][0] for c in cdp.send.call_args_list]
        assert "Page.enable" in calls
        assert "Page.navigate" in calls

    def test_type_text_clears_by_default(self):
        """type_text efface le champ avant de taper (EF-005)"""
        from cdp_commands import CDPCommands
        cdp = object.__new__(CDPCommands)
        cdp.evaluate = MagicMock()
        cdp.send = MagicMock()
        cdp.type_text("#input", "hello")
        # Should have 2 evaluate calls: focus + clear
        assert cdp.evaluate.call_count == 2

    def test_type_text_no_clear(self):
        """type_text sans clear n'efface pas le champ (EF-005)"""
        from cdp_commands import CDPCommands
        cdp = object.__new__(CDPCommands)
        cdp.evaluate = MagicMock()
        cdp.send = MagicMock()
        cdp.type_text("#input", "hello", clear=False)
        # Should have 1 evaluate call: focus only
        assert cdp.evaluate.call_count == 1

    def test_safe_sel_escapes_single_quotes(self):
        """_safe_sel échappe les quotes simples (R-SANIT, R-P1CLOSE)"""
        from cdp_commands import CDPCommands
        assert CDPCommands._safe_sel("div.class") == "div.class"
        assert CDPCommands._safe_sel("a[href='x']") == "a[href=\\'x\\']"
        malicious = "'; alert('xss'); '"
        result = CDPCommands._safe_sel(malicious)
        assert "'" not in result.replace("\\'", "")

    def test_safe_sel_escapes_backslash(self):
        """_safe_sel échappe les backslashes (R-P1CLOSE)"""
        from cdp_commands import CDPCommands
        assert CDPCommands._safe_sel("a\\b") == "a\\\\b"
        assert CDPCommands._safe_sel("no\\backslash\\'quote") == "no\\\\backslash\\\\\\'quote"

    def test_safe_sel_escapes_newlines(self):
        """_safe_sel échappe les newlines et carriage returns (R-P1CLOSE)"""
        from cdp_commands import CDPCommands
        assert CDPCommands._safe_sel("a\nb") == "a\\nb"
        assert CDPCommands._safe_sel("a\rb") == "a\\rb"
        assert CDPCommands._safe_sel("a\n\rb") == "a\\n\\rb"

    def test_safe_sel_combined_injection(self):
        """_safe_sel bloque les tentatives d'injection combinées (R-P1CLOSE)"""
        from cdp_commands import CDPCommands
        # Attempt to break out of querySelector and inject JS
        payload = "'); document.cookie='stolen'; ('"
        result = CDPCommands._safe_sel(payload)
        # The result should not contain unescaped quotes
        assert result == "\\'); document.cookie=\\'stolen\\'; (\\'"

    def test_timing_constants_defined(self):
        """CDPCommands définit des constantes WAIT_* configurables (R-TIMING, R-P2PROVE)"""
        from cdp_commands import CDPCommands
        expected = ['WAIT_NAVIGATION', 'WAIT_HISTORY', 'WAIT_SUBMIT',
                    'WAIT_CLICK', 'WAIT_SCROLL', 'WAIT_KEY', 'WAIT_SHORT', 'WAIT_POLL']
        for const in expected:
            assert hasattr(CDPCommands, const), f"Missing constant: {const}"
            val = getattr(CDPCommands, const)
            assert isinstance(val, (int, float)), f"{const} must be numeric"
            assert val > 0, f"{const} must be positive"

    def test_no_hardcoded_sleep_values(self):
        """Aucun time.sleep avec valeur numérique en dur dans cdp_commands.py (R-P2PROVE)"""
        import re
        src_path = os.path.join(_REFACTORING, 'cdp_commands.py')
        with open(src_path) as f:
            content = f.read()
        # Find time.sleep calls with numeric literals (e.g. time.sleep(0.5), time.sleep(2))
        hardcoded = re.findall(r'time\.sleep\(\s*[0-9]', content)
        assert hardcoded == [], f"Hardcoded time.sleep found: {hardcoded}"
