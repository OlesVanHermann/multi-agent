"""Codex : pas de fin de tour tant que l'indicateur d'activité est visible.

Constat 304-204 (mx30, 2026-10-11, codex-cli 0.162.1) : le bridge a publié
« Response sent » 11 et 29 secondes après l'envoi alors que Codex affichait
« Working » depuis plusieurs minutes. La ligne de statut de Codex est affichée
au repos comme pendant le travail, et le titre du fil a remplacé l'indicateur
animé du footer : les trois dernières lignes restaient stables en plein travail.
"""
import os
import sys
import threading
import time
from unittest.mock import MagicMock

_HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', 'scripts', 'agent-bridge'))

import engines  # noqa: E402
import agent as agent_mod  # noqa: E402

CODEX = engines.load_markers('codex')

DRAFT = "\n".join(
    ["› brouillon colle depuis le dashboard"]
    + [f"  suite {n} du brouillon" for n in range(38)]
)
FOOTER = (
    "  GPT-6.1-Sol max · ~/multi-agent · Devenir agent 304-204\n"
    "  tab to queue message"
)


def _frame(body, working_secs=None):
    working = (f"◦ Working ({working_secs}s • esc to interrupt)\n\n"
               if working_secs is not None else "")
    return f"› deviens agent 304-204\n{body}\n{working}{DRAFT}\n\n{FOOTER}\n"


def _codex_bridge(monkeypatch):
    for name, value in {
        'MARKERS': CODEX,
        'BUSY_SCOPE': CODEX['busy_scope'],
        'BUSY_MARKERS': CODEX['busy_markers'],
        'STATUS_LINE': CODEX['status_line'],
        'PROMPT_MARKERS': CODEX['prompt_markers'],
        'QUEUED_MSG': CODEX['queued'],
        'COMPACTION_DONE': CODEX['compaction']['done'],
        'APPROVAL_PROMPT': CODEX['approval'],
        'SURVEY_PROMPT': CODEX['survey'],
        'WAITING_SELECT': CODEX['waiting_select'],
        'STABLE_READY_SECS': 0.3,
        'STABLE_FALLBACK_SECS': 0.3,
        'POLL_MAX': 0.1,
    }.items():
        monkeypatch.setattr(agent_mod, name, value)
    bridge = object.__new__(agent_mod.TmuxAgent)
    bridge.agent_id = "304-204"
    bridge.session_name = "agent-304-204"
    bridge._log = MagicMock()
    bridge._last_tail3_key = ''
    bridge._get_auto_responder = MagicMock()
    bridge.running = True
    return bridge


def test_no_turn_end_while_codex_shows_working(monkeypatch):
    bridge = _codex_bridge(monkeypatch)
    started = time.time()
    busy_for = 1.5

    def capture(_lines):
        elapsed = time.time() - started
        if elapsed < busy_for:
            # Le compteur avance ; le bas du pane (brouillon + footer) est figé.
            return _frame("• Ran ./push.sh e01", working_secs=int(elapsed * 10))
        return _frame("• Ran ./push.sh e01\n• Tests terminés : réponse finale")

    monkeypatch.setattr(bridge, "_capture_pane", capture, raising=False)
    baseline = _frame("")
    result = []
    worker = threading.Thread(
        target=lambda: result.append(bridge._wait_for_response(baseline=baseline)),
        daemon=True)
    worker.start()
    worker.join(timeout=10)
    bridge.running = False

    assert result, "le tour ne s'est jamais terminé après la fin du travail"
    assert time.time() - started >= busy_for
    assert "réponse finale" in result[0]


def test_turn_never_ends_while_working_stays_visible(monkeypatch):
    bridge = _codex_bridge(monkeypatch)
    counter = {"n": 0}

    def capture(_lines):
        counter["n"] += 1
        return _frame("• Ran ./push.sh e01", working_secs=counter["n"])

    monkeypatch.setattr(bridge, "_capture_pane", capture, raising=False)
    result = []
    worker = threading.Thread(
        target=lambda: result.append(
            bridge._wait_for_response(baseline=_frame(""))),
        daemon=True)
    worker.start()
    time.sleep(1.5)
    assert worker.is_alive() and result == []
    bridge.running = False
    worker.join(timeout=2)
    assert result == ["__BRIDGE_STOPPED__"]
