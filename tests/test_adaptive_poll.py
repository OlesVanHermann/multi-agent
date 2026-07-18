"""
A2 — Scrutation adaptative (fin des sleep fixes)

Le poll redescend à POLL_MIN dès que le pane change et s'allonge (×1.5,
plafonné à POLL_MAX) dès stabilité. _send_keys sort dès que la ligne
d'input est vide au lieu d'attendre des paliers fixes 1/2/4/8 s.
"""
import os
import sys
import time
from unittest.mock import MagicMock

import pytest

_HERE = os.path.dirname(os.path.realpath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
sys.path.insert(0, os.path.join(_REPO_ROOT, 'scripts', 'agent-bridge'))


class TestNextPollInterval:
    def test_reset_to_min_on_change(self):
        from agent import _next_poll_interval, POLL_MIN
        assert _next_poll_interval(2.0, changed=True) == POLL_MIN

    def test_grows_when_stable(self):
        from agent import _next_poll_interval, POLL_MIN
        assert _next_poll_interval(POLL_MIN, changed=False) == pytest.approx(POLL_MIN * 1.5)

    def test_capped_at_max(self):
        from agent import _next_poll_interval, POLL_MAX
        assert _next_poll_interval(POLL_MAX, changed=False) == POLL_MAX
        assert _next_poll_interval(POLL_MAX * 10, changed=False) == POLL_MAX

    def test_bounds_sane(self):
        from agent import POLL_MIN, POLL_MAX, POLL_INTERVAL
        assert 0 < POLL_MIN < POLL_MAX
        assert POLL_INTERVAL == 1.0  # conservé pour la boucle de compaction

    def test_stability_thresholds_preserved(self):
        # Équivalents des anciens compteurs (5/10/15 itérations à 1s)
        from agent import STABLE_READY_SECS, STABLE_FALLBACK_SECS, STABLE_PLAN_SECS
        assert STABLE_READY_SECS == 5.0
        assert STABLE_FALLBACK_SECS == 10.0
        assert STABLE_PLAN_SECS == 15.0


class TestComposerContainsText:
    def test_wrapped_prompt_with_empty_cursor_row_is_still_pending(self):
        from agent import _composer_contains_text
        viewport = "\n".join([
            "› [ENVELOPPE BRIDGE]",
            "  FROM=348-348",
            "  unique-message-tail",
            "",
            "  gpt-5.6-sol xhigh",
        ])
        assert _composer_contains_text(viewport, 3, "unique-message-tail")

    def test_empty_active_composer_means_previous_prompt_was_submitted(self):
        from agent import _composer_contains_text
        viewport = "\n".join([
            "› previous unique-message-tail",
            "  previous continuation",
            "› ",
            "  gpt-5.6-sol xhigh",
        ])
        assert not _composer_contains_text(viewport, 2, "unique-message-tail")

    def test_unknown_composer_is_conservatively_pending(self):
        from agent import _composer_contains_text
        assert _composer_contains_text("plain terminal output", 0, "message-tail")


def _make_agent():
    from agent import TmuxAgent
    agent = object.__new__(TmuxAgent)
    agent.agent_id = "300"
    agent.session_name = "A-agent-300"
    agent._log = MagicMock()
    return agent


class TestSendKeysAdaptive:
    def test_exits_quickly_when_submitted(self, monkeypatch):
        """L'input est soumis immédiatement → pas de palier fixe d'1s+."""
        import agent as agent_mod
        a = _make_agent()
        # Composeur actif vide : le texte a bien été soumis.
        def fake_run(cmd, **kw):
            if "capture-pane" in cmd:
                return MagicMock(stdout="› \n", returncode=0)
            return MagicMock(stdout="0\n", returncode=0)
        run_mock = MagicMock(side_effect=fake_run)
        monkeypatch.setattr(agent_mod.subprocess, "run", run_mock)
        monkeypatch.setattr(a, "_capture_pane", lambda n: "❯ \nbypass permissions\n", raising=False)

        start = time.time()
        a._send_keys("hello world")
        elapsed = time.time() - start
        # Fixe incompressible : 0.3 (C-u) + 1.0 (texte) + 1er poll POLL_MIN.
        # L'ancienne échelle attendait au moins 1s de plus avant la 1re vérif.
        assert elapsed < 2.5

    def test_resends_enter_while_text_still_on_input_line(self, monkeypatch):
        """Texte toujours sur la ligne d'input → Enter renvoyé, budget borné."""
        import agent as agent_mod
        a = _make_agent()
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if "capture-pane" in cmd:
                return MagicMock(stdout="› hello world\n", returncode=0)
            return MagicMock(stdout="0\n", returncode=0)

        monkeypatch.setattr(agent_mod.subprocess, "run", fake_run)
        # La ligne du curseur contient toujours le texte → jamais soumis
        monkeypatch.setattr(a, "_capture_pane", lambda n: "hello world\n", raising=False)
        # Budget raccourci pour le test (échelle de renvoi à ~1s et ~3s)
        monkeypatch.setattr(agent_mod, "SEND_KEYS_BUDGET", 4.0)
        monkeypatch.setattr(agent_mod, "POLL_MAX", 0.3)

        start = time.time()
        a._send_keys("hello world")
        elapsed = time.time() - start
        assert elapsed < 8  # le budget coupe la boucle

        enters = [c for c in calls if c[:3] == ["tmux", "send-keys", "-t"] and c[-1] == "Enter"]
        # 1 Enter initial + renvois à ~1s puis ~3s
        assert len(enters) >= 3

    def test_checks_viewport_and_tail_for_wrapped_message(self, monkeypatch):
        """Le curseur tmux est relatif au viewport et pointe près de la fin
        d'un long message replié, pas sur ses 40 premiers caractères."""
        import agent as agent_mod
        a = _make_agent()
        calls = []
        text = "prefix " + ("x" * 80) + " unique-message-tail"

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if "display-message" in cmd:
                return MagicMock(stdout="2\n", returncode=0)
            if "capture-pane" in cmd:
                return MagicMock(stdout="old scrollback\n› wrapped prefix\nunique-message-tail\n", returncode=0)
            return MagicMock(stdout="", returncode=0)

        monkeypatch.setattr(agent_mod.subprocess, "run", fake_run)
        monkeypatch.setattr(agent_mod, "SEND_KEYS_BUDGET", 1.5)
        monkeypatch.setattr(agent_mod, "POLL_MAX", 0.2)
        a._send_keys(text)

        captures = [c for c in calls if "capture-pane" in c]
        assert captures
        assert all("-S" not in c for c in captures)
        enters = [c for c in calls if c[:3] == ["tmux", "send-keys", "-t"] and c[-1] == "Enter"]
        assert len(enters) >= 2


class TestWaitForResponseAdaptive:
    def test_short_response_detected(self, monkeypatch):
        """Réponse courte : détectée après STABLE_READY_SECS, pas de faux départ."""
        import agent as agent_mod
        a = _make_agent()
        monkeypatch.setattr(agent_mod, "STABLE_READY_SECS", 0.5)
        monkeypatch.setattr(agent_mod, "POLL_MAX", 0.2)

        baseline = "old content\nbypass permissions\n❯"
        final = "old content\nmy answer\nbypass permissions\n❯"
        captures = iter([baseline])

        def capture(n):
            return next(captures, final)

        monkeypatch.setattr(a, "_capture_pane", capture, raising=False)
        a._last_tail3_key = ''

        start = time.time()
        resp = a._wait_for_response(timeout=10)
        elapsed = time.time() - start
        assert "my answer" in resp
        assert elapsed < 5  # bien plus court que les ~6s de l'ancien poll fixe

    def test_no_false_positive_before_stability(self, monkeypatch):
        """Le pane change en continu : le seuil ne fabrique pas de fin."""
        import agent as agent_mod
        a = _make_agent()
        monkeypatch.setattr(agent_mod, "STABLE_READY_SECS", 5.0)

        counter = {"n": 0}

        def capture(n):
            counter["n"] += 1
            # tail3 change à chaque capture → jamais stable
            return f"streaming {counter['n']}\nbypass permissions ligne {counter['n']}\n❯"

        monkeypatch.setattr(a, "_capture_pane", capture, raising=False)
        a._last_tail3_key = ''

        import threading
        a.running = True
        result = []
        t = threading.Thread(
            target=lambda: result.append(a._wait_for_response(timeout=0.5)),
            daemon=True)
        t.start()
        time.sleep(1.0)
        assert t.is_alive()
        assert result == []
        a.running = False
        t.join(timeout=2)
        assert result == ["__BRIDGE_STOPPED__"]
