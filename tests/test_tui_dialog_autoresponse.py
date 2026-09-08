"""A10 — SPEC-OPERATEUR-tui-dialogs-autoresponse.

Deux familles : (1) classification des dialogues déclarés (relevés opérateur
du 06/09/2026, fixtures reprises telles quelles), (2) frappe sûre côté bridge
— composer occupé, séquence retombée dans le composer (le « 0 » fantôme),
confirmation en deux temps avec preuve de sélection, budget persistant.
Invariant transverse : aucune auto-réponse ne change jamais le modèle.
"""

import os
import sys
import threading
from unittest.mock import MagicMock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "agent-bridge"))

from autoresponder import (  # noqa: E402
    AutoResponder,
    classify_active_dialog,
    selected_line_contains,
)
import agent as agent_mod  # noqa: E402
import engines  # noqa: E402

CLAUDE = engines.load_markers("claude")
CODEX = engines.load_markers("codex")


# ── Fixtures = relevés opérateur (mx6, 2026-09-06) ──────────────────────

def _codex_rate_limit():
    return "\n".join([
        "  Approaching rate limits",
        "  Switch to gpt-5.6-luna for lower credit usage?",
        "› 1. Switch to gpt-5.6-luna                 Fast and affordable agentic coding model.",
        "  2. Keep current model",
        "  3. Keep current model (never show again)  Hide future rate limit reminders about switching models.",
        "  Press enter to confirm or esc to go back",
    ])


def _codex_slow_response():
    return "\n".join([
        "  Our systems are thinking a bit more about this request before responding.",
        "  Hang tight or retry with a faster model for a quicker response.",
        "› 1. Retry with a faster model",
        "  2. Dismiss and keep waiting",
        "  3. Learn more",
        "  Press enter to confirm or esc to go back",
        "  No action is required. Codex will keep waiting.",
    ])


def _codex_proceed(question="Do you want to proceed?"):
    return "\n".join([
        f" {question}",
        " ❯ 1. Yes",
        "   2. No",
        " Esc to cancel · Tab to amend",
    ])


def _claude_usage_limit(continue_first=True):
    options = [
        "  1. Continue with Fable 5",
        "› 2. Switch to Opus 5 (1M context) and continue",
    ] if continue_first else [
        "› 1. Switch to Opus 5 (1M context) and continue",
        "  2. Continue with Fable 5",
    ]
    return "\n".join([
        "  You've reached your Fable 5 limit",
        "  Continuing on Fable 5 uses usage credits — you have credits.",
        *options,
        "  Enter to confirm · Esc to cancel",
    ])


# ── 1. Classification des dialogues déclarés ────────────────────────────

class TestDeclaredDialogClassification:
    def test_rate_limit_selects_never_show_again(self):
        d = classify_active_dialog(_codex_rate_limit(), "codex", CODEX)
        assert d is not None and d.kind == "rate_limit"
        assert d.keys == ("3",)  # numéro résolu dynamiquement par libellé
        assert d.confirm_key == "Enter"
        assert "never show again" in d.confirm_selected

    def test_slow_response_selects_dismiss_and_keep_waiting(self):
        d = classify_active_dialog(_codex_slow_response(), "codex", CODEX)
        assert d is not None and d.kind == "slow_response"
        assert d.keys == ("2",)

    def test_proceed_approval_selects_yes(self):
        d = classify_active_dialog(_codex_proceed(), "codex", CODEX)
        assert d is not None and d.kind == "proceed_approval"
        assert d.keys == ("1",)

    def test_usage_limit_targets_continue_with_regardless_of_rank(self):
        first = classify_active_dialog(
            _claude_usage_limit(continue_first=True), "claude", CLAUDE)
        assert first is not None and first.kind == "usage_limit"
        assert first.keys == ("1",)
        swapped = classify_active_dialog(
            _claude_usage_limit(continue_first=False), "claude", CLAUDE)
        assert swapped is not None and swapped.kind == "usage_limit"
        assert swapped.keys == ("2",)  # jamais un rang codé en dur

    def test_usage_limit_without_continue_option_escapes(self):
        pane = "\n".join([
            "  You've reached your Fable 5 limit",
            "  Continuing uses usage credits — Continue with support page.",
            "› 1. Switch to Opus 5 and continue",
            "  Enter to confirm · Esc to cancel",
        ])
        d = classify_active_dialog(pane, "claude", CLAUDE)
        assert d is not None and d.kind == "usage_limit_escape"
        assert d.keys == ("Escape",)

    def test_bare_yes_outside_proceed_screen_never_matches(self):
        # Contre-fixture du CDC : « 1. Yes » hors « Do you want to proceed? »
        pane = "\n".join([
            " historique : 1. Yes c'était validé hier",
            " ❯ ",
        ])
        assert classify_active_dialog(pane, "codex", CODEX) is None

    def test_irreversible_marker_still_blocks_declared_dialogs(self):
        pane = _codex_proceed(
            question="Do you want to proceed? (will run rm -rf build/)")
        assert classify_active_dialog(pane, "codex", CODEX) is None

    def test_wrong_process_never_matches(self):
        assert classify_active_dialog(
            _codex_rate_limit(), "bash", CODEX) is None

    def test_selected_line_contains_reads_cursor_line(self):
        cfg = CODEX["auto_response"]
        assert selected_line_contains(
            _codex_rate_limit(), cfg, "Switch to gpt-5.6-luna")
        assert not selected_line_contains(
            _codex_rate_limit(), cfg, "never show again")


# ── 2. Frappe sûre côté bridge ──────────────────────────────────────────

def _bridge():
    bridge = object.__new__(agent_mod.TmuxAgent)
    bridge.agent_id = "399"
    bridge.session_name = "agent-399"
    bridge.state = agent_mod.State.IDLE
    bridge.state_lock = threading.Lock()
    bridge._tui_lock = threading.Lock()
    config = agent_mod.MARKERS["auto_response"]
    bridge._auto_responder = AutoResponder(
        cooldown_seconds=0, max_attempts=config["max_attempts"])
    bridge.redis = MagicMock()
    bridge._log = MagicMock()
    bridge._log_event = MagicMock()
    bridge._set_redis_status = MagicMock()
    return bridge


def _survey_pane(composer_text=""):
    return "\n".join([
        "How is Claude doing this session? (optional)",
        "  1: Bad  2: Fine  3: Good  4: Unsure",
        "  0: Dismiss",
        f"❯ {composer_text}",
    ])


class TestSafeTyping:
    def test_busy_composer_aborts_before_any_key(self):
        bridge = _bridge()
        pane = _survey_pane("redémarre voice-agent")
        bridge._capture_dialog_context = MagicMock(
            return_value=(pane, "claude"))
        bridge._send_dialog_keys = MagicMock(return_value=True)
        assert bridge._maybe_auto_respond(pane, "claude", "test") is True
        bridge._send_dialog_keys.assert_not_called()

    def test_leaked_keys_are_reverted_with_ctrl_u(self, monkeypatch):
        """Le « 0 » fantôme : dialogue disparu à l'instant de la frappe, le
        chiffre atterrit dans le composer → C-u, jamais de message envoyé."""
        bridge = _bridge()
        clean = _survey_pane()
        leaked = "❯ 0"  # dialogue fermé, le 0 est dans le composer
        captures = iter([(clean, "claude"), (leaked, "claude")])
        bridge._capture_dialog_context = MagicMock(
            side_effect=lambda: next(captures))
        bridge._send_dialog_keys = MagicMock(return_value=True)
        run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr(agent_mod.subprocess, "run", run)
        assert bridge._maybe_auto_respond(
            _survey_pane(), "claude", "test") is True
        sent_keys = [c.args[0] for c in run.call_args_list]
        assert any("C-u" in call for call in sent_keys)
        bridge._log_event.assert_any_call("auto_response_reverted", "survey")

    def test_two_step_confirm_requires_selection_proof(self):
        """Sélection restée sur la bascule → Escape + alerte, jamais Enter."""
        bridge = _bridge()
        pane = _claude_usage_limit(continue_first=False)
        # Après la frappe du digit, la sélection n'a PAS bougé (toujours sur
        # « Switch to Opus 5 ») — la capture renvoie le même écran.
        bridge._capture_dialog_context = MagicMock(
            return_value=(pane, "claude"))
        bridge._publish_dialog_alert = MagicMock()
        sent = []
        bridge._send_dialog_keys = MagicMock(
            side_effect=lambda keys: sent.append(tuple(keys)) or True)
        assert bridge._maybe_auto_respond(pane, "claude", "test") is True
        assert ("Escape",) in sent
        assert ("Enter",) not in sent
        bridge._publish_dialog_alert.assert_called_once()

    def test_dialog_gone_after_digit_is_success_without_enter(self):
        # Moteur du bridge chargé = claude : fixture usage_limit.
        bridge = _bridge()
        pane = _claude_usage_limit(continue_first=True)
        idle = "travail terminé\n❯ \nbypass permissions on"
        captures = iter([
            (pane, "claude"),   # revalidation TOCTOU
            (idle, "claude"),   # post-frappe : composer vide, pas de fuite
            (idle, "claude"),   # confirmation : dialogue disparu → succès
        ])
        bridge._capture_dialog_context = MagicMock(
            side_effect=lambda: next(captures))
        sent = []
        bridge._send_dialog_keys = MagicMock(
            side_effect=lambda keys: sent.append(tuple(keys)) or True)
        assert bridge._maybe_auto_respond(pane, "claude", "test") is True
        assert sent == [("1",)]  # ni Enter ni Escape après fermeture

    def test_persistent_attempt_budget_survives_restart(self):
        bridge = _bridge()
        pane = _survey_pane()
        bridge._capture_dialog_context = MagicMock(
            return_value=(pane, "claude"))
        bridge._send_dialog_keys = MagicMock(return_value=True)
        bridge.redis.incr = MagicMock(return_value=99)  # budget déjà épuisé
        assert bridge._maybe_auto_respond(pane, "claude", "test") is True
        bridge._send_dialog_keys.assert_not_called()

    def test_send_dialog_keys_accepts_declared_digits_only(self, monkeypatch):
        bridge = _bridge()
        run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr(agent_mod.subprocess, "run", run)
        assert bridge._send_dialog_keys(("3", "Enter")) is True
        assert bridge._send_dialog_keys(("Escape",)) is True
        with pytest.raises(ValueError):
            bridge._send_dialog_keys(("q",))
        with pytest.raises(ValueError):
            bridge._send_dialog_keys(("C-c",))
