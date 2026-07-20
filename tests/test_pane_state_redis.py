"""
B6 — État agents lu depuis Redis (publié par le bridge)

Le bridge dérive l'état du pane lui-même (_parse_pane_state) et le publie
dans le hash agent ; le dashboard lit Redis d'abord et ne retombe sur le
scan tmux que pour les états absents/périmés (_pane_states_from_redis).
"""
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.realpath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
sys.path.insert(0, os.path.join(_REPO_ROOT, 'scripts', 'agent-bridge'))
sys.path.insert(0, os.path.join(_REPO_ROOT, 'web', 'backend'))


class TestParsePaneState:
    def _parse(self, out, pane_cmd="claude", agent_id="300"):
        from agent import _parse_pane_state
        return _parse_pane_state(out, pane_cmd, agent_id)

    def test_busy_when_esc_to_interrupt(self):
        out = "...\nbypass permissions · esc to interrupt\n"
        assert self._parse(out)['busy'] is True

    def test_idle_when_prompt_visible(self):
        out = "bypass permissions on\n❯ \n"
        st = self._parse(out)
        assert st['busy'] is False
        assert st['claude_alive'] is True

    def test_not_busy_when_claude_dead(self):
        st = self._parse("whatever", pane_cmd="bash")
        assert st['busy'] is False
        assert st['claude_alive'] is False

    def test_context_pct_extraction(self):
        out = "bypass permissions\n❯\n4% until auto-compact\n"
        assert self._parse(out)['context_pct'] == 4

    def test_context_pct_alt_format(self):
        out = "bypass permissions\n❯\nauto-compact: 12%\n"
        assert self._parse(out)['context_pct'] == 12

    def test_context_pct_absent(self):
        assert self._parse("bypass permissions\n❯\n")['context_pct'] == -1

    def test_api_error_three_occurrences(self):
        out = "bypass permissions\n❯\n" + "API Error: x\n" * 3
        assert self._parse(out)['api_error'] is True

    def test_api_error_when_alive_without_status_line(self):
        # claude tourne mais aucune ligne "bypass permissions" → UI cassée
        assert self._parse("garbage\n❯\n")['api_error'] is True

    def test_no_api_error_nominal(self):
        out = "bypass permissions\n❯\nAPI Error: once\n"
        assert self._parse(out)['api_error'] is False

    def test_compacting_flags(self):
        st = self._parse("bypass permissions\nCompacting conversation...\n❯\n")
        assert st['compacted'] is True
        assert st['done_compacting'] is False
        st = self._parse("bypass permissions\nConversation compacted\n❯\n")
        assert st['done_compacting'] is True

    def test_prompt_loaded_compound_id(self):
        out = ("bypass permissions\nConversation compacted\n"
               "Read prompts/345-team/345-500.md\n❯\n")
        assert self._parse(out, agent_id="345-500")['prompt_loaded'] is True

    def test_misc_flags(self):
        out = ("bypass permissions · 2 bashes ↓ 12 lines\n"
               "Enter to select\nContext limit reached\n/model opus\n"
               "plan mode on\n❯\n")
        st = self._parse(out)
        assert st['has_bashes'] is True
        assert st['has_down'] is True
        assert st['plan_mode'] is True
        assert st['waiting_approval'] is True
        assert st['context_limit'] is True
        assert st['model_change'] is True

    def test_codex_runtime_model_is_read_from_footer(self):
        from agent import _runtime_effort_from_pane, _runtime_model_from_pane
        from engines import load_markers
        out = "› Implement feature\n  gpt-5.6-luna low · ~/multi-agent\n"
        assert _runtime_model_from_pane(out, load_markers("codex")) == "gpt-5.6-luna"
        assert _runtime_effort_from_pane(out, load_markers("codex")) == "low"

    def test_claude_runtime_model_remains_unknown_without_tui_interaction(self):
        from agent import _runtime_model_from_pane
        from engines import load_markers
        assert _runtime_model_from_pane("bypass permissions", load_markers("claude")) == ""

    def test_claude_model_effort_observation_is_passive(self):
        from agent import TmuxAgent
        instance = object.__new__(TmuxAgent)
        instance._observed_model = ""
        instance._observed_effort = ""
        instance._observe_claude_model_effort(
            "Set model to Fable 5 and saved as your default for new sessions\n"
            "Set effort level to xhigh (saved as your default)\n"
        )
        assert instance._observed_model == "claude-fable-5"
        assert instance._observed_effort == "xhigh"

    def test_bridge_never_uses_bare_model_or_effort_as_probe(self):
        source = open(os.path.join(_REPO_ROOT, "scripts", "agent-bridge", "agent.py")).read()
        assert "_check_claude_model_effort" not in source
        assert "MODEL_CHECK_INTERVAL" not in source
        from engines import load_markers
        markers = load_markers("claude")
        assert "NEVER" in markers["model_check_command"]
        assert "NEVER" in markers["effort_check_command"]


class TestPaneStatesFromRedis:
    @pytest.fixture(scope="class")
    def srv(self):
        pytest.importorskip("fastapi")
        import server
        return server

    def test_fresh_state_used_no_fallback(self, srv):
        now = 1000
        state = {'busy': True, 'context_pct': 3}
        data = {"300": {"pane_state": json.dumps(state), "pane_state_ts": str(now - 5)}}
        states, stale = srv._pane_states_from_redis(["300"], data, now)
        assert states == {"300": state}
        assert stale == []

    def test_stale_ts_goes_to_fallback(self, srv):
        now = 1000
        data = {"300": {"pane_state": "{}", "pane_state_ts": str(now - srv.PANE_STATE_TTL - 1)}}
        states, stale = srv._pane_states_from_redis(["300"], data, now)
        assert states == {}
        assert stale == ["300"]

    def test_missing_state_goes_to_fallback(self, srv):
        states, stale = srv._pane_states_from_redis(["300", "301"], {"300": {}}, 1000)
        assert states == {}
        assert stale == ["300", "301"]

    def test_bad_json_goes_to_fallback(self, srv):
        data = {"300": {"pane_state": "{not json", "pane_state_ts": "999"}}
        states, stale = srv._pane_states_from_redis(["300"], data, 1000)
        assert states == {}
        assert stale == ["300"]

    def test_bad_ts_goes_to_fallback(self, srv):
        data = {"300": {"pane_state": "{}", "pane_state_ts": "abc"}}
        states, stale = srv._pane_states_from_redis(["300"], data, 1000)
        assert states == {}
        assert stale == ["300"]

    def test_mixed_fresh_and_stale(self, srv):
        now = 1000
        fresh = {'busy': False}
        data = {
            "300": {"pane_state": json.dumps(fresh), "pane_state_ts": str(now)},
            "301": {},
        }
        states, stale = srv._pane_states_from_redis(["300", "301"], data, now)
        assert states == {"300": fresh}
        assert stale == ["301"]
