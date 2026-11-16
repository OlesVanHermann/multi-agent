"""« new session » : /exit, session sauvegardée écrasée, nouvelle conversation.

Bouton du terminal à côté de « update harness » (l'ancien « update », qui
reprend la même session). `agent.sh new-session <id>` : mêmes gardes que
update (rien n'est touché si l'agent n'est pas au repos), /exit du CLI qui
TOURNE, arrêt sans sauvegarde, démarrage fresh — l'ancien <id>.session part
dans removed/, le nouvel identifiant est relevé au démarrage, le bridge
relancé envoie « deviens agent ». 000 est refusé (démarré par infra.sh).
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_agent_update_resume import (  # noqa: E402,F401  harnais partagé
    BASE_DIR, CLAUDE_ID, install, _tmux, _pane, _wait_for, _start_fake)
from test_agent_session_resume import (  # noqa: E402,F401
    ns, _agent_sh, _file, _archived, _bridge_line, _last_sid)

# redis-cli factice : PING, et un bridge qui annonce cli_hold.
FAKE_REDIS_CAPS = r'''#!/bin/bash
for a in "$@"; do
    case "$a" in
        ping|PING) echo PONG; exit 0 ;;
        bridge_caps) echo cli_hold; exit 0 ;;
    esac
done
exit 0
'''


@pytest.fixture
def caps(ns):
    """Harnais start/stop dont le bridge annonce cli_hold (bridge à jour)."""
    (ns.root / 'bin' / 'redis-cli').write_text(FAKE_REDIS_CAPS)
    return ns


def _sid(ns, agent_id):
    return _file(ns, agent_id).read_text().split()[-1]


class TestAgentShNewSession:
    @pytest.mark.parametrize('agent_id,cli', [('300-300', 'claude'), ('300-301', 'codex')])
    def test_new_session_replaces_the_saved_one(self, caps, agent_id, cli):
        r = _agent_sh(caps, 'start', agent_id)
        assert r.returncode == 0, r.stdout + r.stderr
        old = _sid(caps, agent_id)                     # relevé au démarrage
        r = _agent_sh(caps, 'new-session', agent_id)
        assert r.returncode == 0, r.stdout + r.stderr
        session = f'agent-{agent_id}'
        pane = _pane(caps, session)
        new = _last_sid(pane)
        assert new != old and 'RESUMED' not in pane
        assert f'UPDATE_RESULT agent={agent_id} mode=new session={new}' in r.stdout
        # Session écrasée : l'ancienne archivée, la nouvelle enregistrée.
        assert _file(caps, agent_id).read_text() == f'{cli}1a\n{cli}\n{new}\n'
        assert [p.read_text() for p in _archived(caps, agent_id)] == [
            f'{cli}1a\n{cli}\n{old}\n']
        # Nouvelle conversation : bridge relancé SANS reprise (« deviens agent »).
        assert _wait_for(lambda: 'AGENT_CLI=' in _bridge_line(caps, session), 10)
        assert 'AGENT_RESUMED' not in _bridge_line(caps, session)

    def test_new_session_follows_the_configured_engine(self, caps):
        """Claude tourne, la configuration demande codex : /exit de claude,
        nouvelle session codex."""
        session, _ = _start_fake(caps, '300-301', 'claude')
        r = _agent_sh(caps, 'new-session', '300-301')
        assert r.returncode == 0, r.stdout + r.stderr
        cmd = _tmux(caps, 'display', '-p', '-t', f'{session}:0', '#{pane_current_command}')
        assert cmd.stdout.strip() == 'codex'

    @pytest.mark.parametrize('agent_id,cli,show', [
        ('300-301', 'codex', '• Working (3s • esc to interrupt)'),
        ('300-300', 'claude', 'Enter to select · ↑/↓ to navigate · Esc to cancel'),
    ])
    def test_agent_not_at_rest_is_left_untouched(self, caps, agent_id, cli, show):
        session, sid = _start_fake(caps, agent_id, cli, env=f"FAKE_SHOW='{show}'")
        r = _agent_sh(caps, 'new-session', agent_id)
        assert r.returncode == 3, r.stdout + r.stderr
        assert 'pas au repos' in r.stdout
        pane = _pane(caps, session)
        assert pane.count('SESSION ') == 1 and f'SESSION {sid}' in pane

    def test_bridge_without_capability_is_refused(self, ns):
        r = _agent_sh(ns, 'start', '300-300')        # bridge sans cli_hold
        assert r.returncode == 0, r.stdout + r.stderr
        sid = _sid(ns, '300-300')
        r = _agent_sh(ns, 'new-session', '300-300')
        assert r.returncode == 4 and 'reload-bridge 300-300' in r.stdout
        assert _sid(ns, '300-300') == sid and not _archived(ns, '300-300')

    def test_bridge_is_stopped_before_the_hold_is_released(self):
        """Après /exit le pane est un shell : lever cli_hold avant d'arrêter
        le bridge laisserait coller un message arrivé pendant la sortie."""
        src = (BASE_DIR / 'scripts' / 'agent.sh').read_text()
        body = src[src.index('new_session_single() {'):]
        body = body[:body.index('\n}\n')]
        after_exit = body[body.index('engine_exit_session_id'):]
        after_exit = after_exit[after_exit.index('    fi\n'):]
        assert after_exit.index('stop_single "$agent_id" nosave') < after_exit.index('release_cli_hold')

    def test_architect_is_refused(self, ns):
        r = _agent_sh(ns, 'new-session', '000')
        assert r.returncode == 6 and 'protégé' in r.stdout

    def test_missing_session_is_an_error(self, ns):
        r = _agent_sh(ns, 'new-session', '300-300')
        assert r.returncode == 1 and 'not running' in r.stdout + r.stderr


class TestBackendNewSession:
    def _call(self, monkeypatch, rc, stdout='', agent_id='300-300'):
        from web.backend.multi_agent.routers import agents as agents_router
        calls = []

        async def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return SimpleNamespace(returncode=rc, stdout=stdout, stderr='')

        async def alive():
            return True

        monkeypatch.setattr(agents_router, '_run_subprocess', fake_run)
        monkeypatch.setattr(agents_router, '_tmux_server_alive', alive)
        return asyncio.run(agents_router.new_session_agent(agent_id=agent_id)), calls

    def test_new_session_result_is_parsed(self, monkeypatch):
        out = f'[OK] Agent 300-300: nouvelle session\nUPDATE_RESULT agent=300-300 mode=new session={CLAUDE_ID}\n'
        result, calls = self._call(monkeypatch, 0, out)
        assert result['status'] == 'renewed'
        assert result['results'] == [
            {'agent_id': '300-300', 'mode': 'new', 'session_id': CLAUDE_ID}]
        assert len(calls) == 1 and calls[0][0] == 'bash'
        assert calls[0][1].endswith('scripts/agent.sh')
        assert calls[0][-2:] == ['new-session', '300-300']

    @pytest.mark.parametrize('rc,reason', [(3, 'not_idle'), (4, 'bridge_reload'), (6, 'protected')])
    def test_refusals_are_conflicts_with_a_reason(self, monkeypatch, rc, reason):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            self._call(monkeypatch, rc, '[WARN] 300-300 refusé')
        assert exc.value.status_code == 409
        assert exc.value.detail == {'reason': reason, 'message': '[WARN] 300-300 refusé'}

    def test_architect_is_refused_without_running_anything(self, monkeypatch):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            self._call(monkeypatch, 0, '', agent_id='000')
        assert exc.value.status_code == 409 and exc.value.detail['reason'] == 'protected'

    def test_failure_is_a_server_error(self, monkeypatch):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            self._call(monkeypatch, 1, "[ERROR] 300-300: claude n'a pas quitté")
        assert exc.value.status_code == 500


class TestTerminalButtons:
    HEADER = BASE_DIR / 'web/frontend/src/components/terminal/TerminalHeader.jsx'
    TERMINAL = BASE_DIR / 'web/frontend/src/components/Terminal.jsx'

    def test_update_is_replaced_by_new_session_and_update_harness(self):
        src = self.HEADER.read_text()
        assert "'new session'" in src and "'update harness'" in src
        assert "'update'" not in src
        assert src.index("'new session'") < src.index("'update harness'")
        assert 'onClick={onNewSession}' in src and 'onClick={onUpdate}' in src
        # Une seule relance du CLI à la fois.
        assert src.count('disabled={busy}') == 2

    def test_new_session_calls_its_endpoint_after_confirmation(self):
        src = self.TERMINAL.read_text()
        handler = src[src.index('const handleNewSession'):]
        handler = handler[:handler.index('\n  }\n') + 4]
        assert 'window.confirm(' in handler
        assert "apiFetch(`api/agent/${agentId}/new-session`, { method: 'POST' })" in handler
        assert 'onNewSession={handleNewSession}' in src
