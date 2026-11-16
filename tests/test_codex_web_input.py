"""Saisie web vers Codex : composer lu, Enter pris en compte, « ; » conservé.

Constats 304-204 (mx30, 2026-10-11, codex-cli 0.162.1) :
- le dashboard ne lisait que le composer de Claude Code (« ❯ ») et croyait
  celui de Codex (« › ») toujours vide ;
- l'Enter envoyé juste après la dernière synchronisation incrémentale était
  pris par Codex pour la fin d'un collage : message laissé dans le composer
  (perdu à 0-50 ms, pris à partir de 100 ms) ;
- un « ; » final de morceau était avalé par tmux (« eXX; » → « eXX »).
Les séquences ANSI ci-dessous sont celles de `tmux capture-pane -e` relevées
sur cette session.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web', 'backend'))
pytest.importorskip("fastapi")

from multi_agent import tmuxio  # noqa: E402
from multi_agent.models import UpdateInput  # noqa: E402
from multi_agent.routers import agents  # noqa: E402

FOOTER = (
    "\n  \x1b[38;5;223mGPT-6.1-Sol max\x1b[39m · \x1b[38;5;151m~/multi-agent\x1b[39m"
    " · \x1b[38;5;216mDevenir agent 304-204\x1b[39m\n"
    "  \x1b[1mtab\x1b[0m to queue message\n"
)
HISTORY = "\x1b[1;2m›\x1b[0m lance les tests de chaque version eXX\n\n"


def _pane(composer):
    return HISTORY + "• Working (2m 18s • esc to interrupt)\n\n" + composer + "\n" + FOOTER


class TestCodexComposerExtraction:
    def test_placeholder_is_empty(self):
        pane = _pane("\x1b[1m›\x1b[0m \x1b[2mAsk Codex to do anything\x1b[0m")
        assert tmuxio._extract_current_input(pane) == ""

    def test_typed_single_line(self):
        pane = _pane("\x1b[1m\x1b[38;5;215m›\x1b[0m lance les tests de chaque version eXX")
        assert tmuxio._extract_current_input(pane) == "lance les tests de chaque version eXX"

    def test_wrapped_draft_is_joined(self):
        pane = _pane(
            "\x1b[1m\x1b[38;5;215m›\x1b[0m regarde dans l'historique de quoi on\n"
            "  parlait depuis 2-3h et relance\n"
            "  les tests"
        )
        assert tmuxio._extract_current_input(pane) == (
            "regarde dans l'historique de quoi on parlait depuis 2-3h et relance les tests")

    def test_typed_text_with_shell_prompt_is_not_misread(self):
        """L'ancien repli « $ » lisait n'importe quelle ligne d'historique."""
        pane = _pane("\x1b[1m›\x1b[0m ubuntu@mx30:~/test-errors$ ls -al")
        assert tmuxio._extract_current_input(pane) == "ubuntu@mx30:~/test-errors$ ls -al"

    def test_colour_2_is_not_dim(self):
        pane = _pane("\x1b[1m\x1b[38;5;2m›\x1b[0m texte saisi")
        assert tmuxio._extract_current_input(pane) == "texte saisi"

    def test_history_message_at_bottom_is_not_a_composer(self):
        pane = "\x1b[1;2m›\x1b[0m ancien message envoyé\n" + FOOTER
        assert tmuxio._extract_current_input(pane) == ""

    def test_numbered_dialog_option_is_not_a_composer(self):
        pane = (
            "  Would you like to run the following command?\n"
            "› 1. Yes, proceed (y)\n"
            "  2. No, and tell Codex what to do differently (esc)\n"
            "  Press enter to confirm or esc to cancel\n"
        )
        assert tmuxio._extract_current_input(pane) == ""

    def test_claude_composer_unchanged(self):
        pane = (
            "réponse précédente\n"
            "────────────────────\n"
            "❯\xa0analyse le README\n"
            "────────────────────\n"
            "  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
        )
        assert tmuxio._extract_current_input(pane) == "analyse le README"

    def test_codex_prefix_comes_from_markers(self):
        assert "›" in tmuxio._COMPOSER_PREFIXES


def _record(monkeypatch):
    calls = []

    async def fake_run(cmd, **kwargs):
        calls.append(("run", list(cmd)))

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""
        return Result()

    async def fake_sleep(delay):
        calls.append(("sleep", delay))

    monkeypatch.setattr(agents, "_run_subprocess", fake_run)
    monkeypatch.setattr(agents.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(agents, "_log_prompt_history", lambda *a, **k: None)
    return calls


class TestSemicolonKept:
    @pytest.mark.parametrize("text,expected", [
        ("il faut créer les eXX;", [["-l", "il faut créer les eXX"], ["-H", "3b"]]),
        ("a\\;", [["-l", "a\\"], ["-H", "3b"]]),
        (";;", [["-H", "3b", "3b"]]),
        ("a;b", [["-l", "a;b"]]),
    ])
    def test_trailing_semicolons_sent_as_hex(self, monkeypatch, text, expected):
        calls = _record(monkeypatch)
        asyncio.run(agents._send_literal("agent-304-204:0.0", text))
        sent = [c[1][4:] for c in calls if c[0] == "run"]
        assert sent == expected

    def test_incremental_sync_keeps_semicolon(self, monkeypatch):
        calls = _record(monkeypatch)
        asyncio.run(agents.update_agent_input(
            "304-204", UpdateInput(text="les eXX;", previous="", submit=False)))
        sent = [c[1] for c in calls if c[0] == "run" and "has-session" not in c[1]]
        assert sent == [
            ["tmux", "send-keys", "-t", "agent-304-204:0.0", "-l", "les eXX"],
            ["tmux", "send-keys", "-t", "agent-304-204:0.0", "-H", "3b"],
        ]


class TestEnterAfterSettle:
    def test_synced_submit_waits_before_enter(self, monkeypatch):
        calls = _record(monkeypatch)
        asyncio.run(agents.update_agent_input(
            "304-204",
            UpdateInput(text="lance les tests", previous="lance les tests",
                        submit=True, already_synced=True)))
        enter = calls.index(("run", ["tmux", "send-keys", "-t", "agent-304-204:0.0", "Enter"]))
        assert ("sleep", agents._SUBMIT_SETTLE_S) in calls[:enter]
        assert agents._SUBMIT_SETTLE_S >= 0.1

    def test_send_route_waits_before_enter(self, monkeypatch):
        from multi_agent.models import SendMessage
        calls = _record(monkeypatch)
        asyncio.run(agents.send_to_agent(SendMessage(message="go"), agent_id="304-204"))
        enter = calls.index(("run", ["tmux", "send-keys", "-t", "agent-304-204:0.0", "Enter"]))
        assert ("sleep", agents._SUBMIT_SETTLE_S) in calls[:enter]
