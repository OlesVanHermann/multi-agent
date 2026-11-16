"""
A1 — Découplage détection fin de réponse / rendu CLI

Les chaînes d'UI Claude sont externalisées dans markers.yaml ;
agent.py ne doit plus en contenir aucune en dur (hors commentaires).
"""
import io
import os
import sys
import tokenize

import pytest

_HERE = os.path.dirname(os.path.realpath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
_AGENT_PY = os.path.join(_REPO_ROOT, 'scripts', 'agent-bridge', 'agent.py')
_MARKERS_YAML = os.path.join(_REPO_ROOT, 'scripts', 'agent-bridge', 'markers.yaml')
sys.path.insert(0, os.path.join(_REPO_ROOT, 'scripts', 'agent-bridge'))

UI_STRINGS = [
    "bypass permissions",
    "plan mode on",
    "Conversation compacted",
    "compacting conversation",
    "esc to interrupt",
    "Would you like to proceed",
    "How is Claude doing",
    "Press up to edit queued messages",
    "Enter to select",
    "Context limit reached",
    "until auto-compact",
    "API Error: 401",
]


def _code_strings(path):
    """Toutes les chaînes littérales du code (commentaires exclus)."""
    out = []
    with open(path, 'rb') as f:
        for tok in tokenize.tokenize(f.readline):
            if tok.type == tokenize.STRING:
                out.append(tok.string)
    return '\n'.join(out)


class TestNoHardcodedUIStrings:
    def test_agent_py_has_no_ui_literal(self):
        strings = _code_strings(_AGENT_PY)
        for ui in UI_STRINGS:
            assert ui not in strings, f"chaîne d'UI en dur dans agent.py : {ui!r}"

    def test_markers_yaml_exists_and_loads(self):
        yaml = pytest.importorskip("yaml")
        with open(_MARKERS_YAML, encoding='utf-8') as f:
            markers = yaml.safe_load(f)
        for key in ('prompt_markers', 'status_line', 'busy_markers', 'plan_mode',
                    'compaction', 'approval', 'survey', 'queued',
                    'api_error_patterns', 'context_pct_patterns'):
            assert key in markers, f"clé manquante dans markers.yaml : {key}"
        assert markers['compaction']['in_progress']
        assert markers['compaction']['done']


class TestMarkersLoaded:
    def test_module_constants_match_yaml(self):
        yaml = pytest.importorskip("yaml")
        import agent
        with open(_MARKERS_YAML, encoding='utf-8') as f:
            markers = yaml.safe_load(f)
        assert agent.PROMPT_MARKERS == markers['prompt_markers']
        assert agent.STATUS_LINE == markers['status_line']
        assert agent.COMPACTION_DONE == markers['compaction']['done']
        assert agent.API_ERROR_PATTERNS == markers['api_error_patterns']

    def test_prompt_markers_content(self):
        # Compat avec les tests existants : marqueurs historiques toujours là
        from agent import PROMPT_MARKERS
        assert '❯' in PROMPT_MARKERS
        assert '>' in PROMPT_MARKERS

    def test_parse_pane_state_uses_markers(self):
        """Le comportement B6 reste identique avec les marqueurs externalisés."""
        from agent import _parse_pane_state
        out = "...\nbypass permissions · esc to interrupt\n"
        assert _parse_pane_state(out, "claude", "300")['busy'] is True
        out = "bypass permissions on\n❯ \n"
        st = _parse_pane_state(out, "claude", "300")
        assert st['busy'] is False
