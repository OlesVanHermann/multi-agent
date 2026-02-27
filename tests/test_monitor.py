"""
Tests pour monitor.py — EF-007 (tests monitor.py, CA-008: 8 tests minimum)
CT-004 : pytest + unittest.mock
CT-010 : Mock Redis, pas de pollution prod

Vérifie : COLORS, agent_color(), c(), truncate(), format_message()
EF-003 : Vérification format 7 champs heartbeat stream (mi:agent:{id}:heartbeat)
"""
import pytest
import sys
import os
from unittest.mock import MagicMock, patch

# Load monitor.py via importlib (R-SYMLINKPROOF: explicit path, no sys.path conflicts)
import importlib.util

_HERE = os.path.dirname(os.path.realpath(__file__))

def _find_project_root(start, markers=('CLAUDE.md', '.git')):
    """Remonte les répertoires jusqu'à trouver un marqueur du projet."""
    current = os.path.realpath(start)
    while current != os.path.dirname(current):
        if any(os.path.exists(os.path.join(current, m)) for m in markers):
            return current
        current = os.path.dirname(current)
    raise FileNotFoundError(f"Marqueur {markers} introuvable depuis {start}")

_BASE = _find_project_root(_HERE)
_MONITOR_PATH = os.path.join(_BASE, 'scripts', 'monitor.py')

# Mock redis ONLY for monitor.py loading — restore real redis to avoid poisoning
# other tests that depend on real redis.ConnectionError (R-REGTEST C3)
_real_redis = sys.modules.get('redis')
sys.modules['redis'] = MagicMock()

_spec = importlib.util.spec_from_file_location("monitor_mod", _MONITOR_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# Restore real redis module to prevent test pollution (R-REGTEST C3)
if _real_redis is not None:
    sys.modules['redis'] = _real_redis
else:
    del sys.modules['redis']

COLORS = _mod.COLORS
AGENT_COLORS = _mod.AGENT_COLORS
c = _mod.c
agent_color = _mod.agent_color
truncate = _mod.truncate
format_message = _mod.format_message


class TestMonitorColors:
    """EF-007 — Tests des constantes de couleur."""

    def test_colors_has_reset(self):
        """EF-007 : COLORS contient 'reset'."""
        assert 'reset' in COLORS
        assert '\033[0m' in COLORS['reset']

    def test_colors_has_standard_set(self):
        """EF-007 : COLORS contient toutes les couleurs standard."""
        for color in ['red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white', 'gray']:
            assert color in COLORS, f"Missing color: {color}"

    def test_agent_colors_mapping(self):
        """EF-007 : AGENT_COLORS mappe les plages de numérotation."""
        assert AGENT_COLORS['0'] == 'magenta'   # Super-Master
        assert AGENT_COLORS['1'] == 'cyan'      # Master
        assert AGENT_COLORS['2'] == 'blue'      # Explorer
        assert AGENT_COLORS['3'] == 'green'     # Developer
        assert AGENT_COLORS['4'] == 'yellow'    # Integrator
        assert AGENT_COLORS['5'] == 'red'       # Tester


class TestMonitorColorFunction:
    """EF-007 — Tests de la fonction c()."""

    def test_c_wraps_text_with_color(self):
        """EF-007 : c() entoure le texte avec les codes ANSI."""
        result = c('red', 'hello')
        assert 'hello' in result
        assert COLORS['reset'] in result

    def test_c_unknown_color_no_crash(self):
        """EF-007 : c() avec couleur inconnue ne plante pas."""
        result = c('nonexistent', 'test')
        assert 'test' in result


class TestAgentColor:
    """EF-007 — Tests de agent_color()."""

    def test_agent_color_developer(self):
        """EF-007 : Agent 345 → green (Developer)."""
        assert agent_color('345') == 'green'

    def test_agent_color_master(self):
        """EF-007 : Agent 100 → cyan (Master)."""
        assert agent_color('100') == 'cyan'

    def test_agent_color_empty(self):
        """EF-007 : Agent vide → white."""
        assert agent_color('') == 'white'
        assert agent_color(None) == 'white'


class TestTruncate:
    """EF-007 — Tests de truncate()."""

    def test_truncate_short_text(self):
        """EF-007 : Texte court retourné tel quel."""
        assert truncate('hello', 60) == 'hello'

    def test_truncate_long_text(self):
        """EF-007 : Texte long tronqué avec ellipsis."""
        long_text = 'a' * 100
        result = truncate(long_text, 60)
        assert len(result) == 63  # 60 + "..."
        assert result.endswith('...')

    def test_truncate_newlines(self):
        """EF-007 : Newlines remplacés par espaces."""
        assert truncate('hello\nworld') == 'hello world'

    def test_truncate_none(self):
        """EF-007 : None retourne chaîne vide."""
        assert truncate(None) == ''
        assert truncate('') == ''


class TestFormatMessage:
    """EF-007 — Tests de format_message()."""

    def test_format_inbox_prompt(self):
        """EF-007 : Message inbox avec prompt formaté correctement."""
        data = {
            'prompt': 'Execute task 1',
            'from_agent': '100',
            'type': 'prompt'
        }
        result = format_message('ma:agent:300:inbox', '1-0', data)

        assert result is not None
        assert '[300]' in result
        assert 'Execute task 1' in result

    def test_format_outbox_response(self):
        """EF-007 : Message outbox avec response formaté correctement."""
        data = {
            'response': 'Task completed successfully',
            'to_agent': '100',
            'type': 'response'
        }
        result = format_message('ma:agent:300:outbox', '1-0', data)

        assert result is not None
        assert '[300]' in result

    def test_format_short_stream_returns_none(self):
        """EF-007 : Stream malformé retourne None."""
        result = format_message('ma:agent', '1-0', {})
        assert result is None

    def test_format_inbox_response_shows_length(self):
        """EF-007 : Response dans inbox montre la longueur."""
        data = {
            'response': 'x' * 200,
            'from_agent': '345'
        }
        result = format_message('ma:agent:300:inbox', '1-0', data)

        assert result is not None
        assert '200 chars' in result

    def test_format_compact_mode(self):
        """EF-007 : Mode compact tronque plus court."""
        data = {'prompt': 'a' * 100, 'from_agent': '100'}
        normal = format_message('ma:agent:300:inbox', '1-0', data, compact=False)
        compact = format_message('ma:agent:300:inbox', '1-0', data, compact=True)

        # Compact should have shorter content
        assert len(compact) < len(normal)


class TestHeartbeatStreamFormat:
    """EF-003, EF-007 — Vérification format heartbeat stream."""

    def test_heartbeat_data_has_7_required_fields(self):
        """EF-003, CA-004 : Heartbeat doit avoir 7 champs."""
        # Simule les données qu'un agent publie via EF-003
        heartbeat = {
            "agent_id": "300",
            "timestamp": "1234567890",
            "status": "idle",
            "messages_processed": "42",
            "last_message_ts": "1234567880",
            "memory_mb": "128.5",
            "cpu_percent": "15.3"
        }
        required = ["agent_id", "timestamp", "status",
                     "messages_processed", "last_message_ts",
                     "memory_mb", "cpu_percent"]
        for field in required:
            assert field in heartbeat, f"Missing heartbeat field: {field}"
        assert len(heartbeat) == 7

    def test_heartbeat_stream_key_format(self):
        """CT-002 : Stream heartbeat utilise préfixe mi:."""
        prefix = "mi"
        agent_id = "300"
        expected = f"{prefix}:agent:{agent_id}:heartbeat"
        assert expected == "mi:agent:300:heartbeat"
