"""Session CLI sauvegardée à l'arrêt, reprise au démarrage.

`agent.sh stop` quitte un CLI au repos par sa commande de sortie, lit
l'identifiant de session qu'il imprime et écrit prompts/<dir>/<id>.session :

    <profil effectif du process>   claude1a, codex1a, claude3a…
    <moteur>                       claude | codex
    <identifiant>                  UUID

`agent.sh start` reprend cette session quand le profil et le moteur configurés
collent ; sinon nouvelle session, et le fichier part dans removed/.

Invariants verrouillés ici :
1. le fichier vit au chemin exact de l'agent, jamais lu en cascade : un
   satellite ne reprend jamais la session de son groupe ;
2. contenu validé : trois lignes, profil, moteur connu, UUID strict ;
3. stop au repos → fichier écrit avec le profil du PROCESS ; agent pas au repos
   → arrêt sans sauvegarde, fichier existant intact ; jamais bloquant ;
4. start → reprise si ça colle ; profil ou moteur changé, --fresh, reprise qui
   ne démarre pas → nouvelle session, fichier archivé dans removed/ ;
5. nouvelle session comme session reprise, le bridge envoie « deviens agent » ;
   « Continue. » (dernière ligne d'historique) seulement en nouvelle session ;
6. stop all sauvegarde chaque agent ; update garde le fichier à jour.
"""
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_agent_update_resume import (  # noqa: E402,F401  harnais partagé
    BASE_DIR, install, _tmux, _pane, _wait_for, _start_fake)

ENGINES_SH = BASE_DIR / 'scripts' / 'engines.sh'
LIB_SH = BASE_DIR / 'scripts' / 'lib.sh'
SID = '2e441a85-1c7e-48d4-a4b9-3262f18680e7'


def lib(snippet):
    return subprocess.run(
        ['bash', '-c', f'source "{ENGINES_SH}"; source "{LIB_SH}"\n{snippet}'],
        capture_output=True, text=True, timeout=15)


# ── Fichier .session (lib.sh) ────────────────────────────────────────────────

class TestSessionFileLocation:
    def test_file_sits_in_the_dir_that_holds_the_agent(self, tmp_path):
        (tmp_path / '300-a').mkdir()
        (tmp_path / '300-b').mkdir()
        (tmp_path / '300-b' / '300-100.md').write_text('')
        r = lib(f'agent_session_file 300-100 "{tmp_path}"')
        assert r.stdout.strip() == f'{tmp_path}/300-b/300-100.session'

    def test_history_alone_designates_the_dir(self, tmp_path):
        (tmp_path / '000-a').mkdir()
        (tmp_path / '000-hub-master').mkdir()
        (tmp_path / '000-hub-master' / '000.history').write_text('')
        r = lib(f'agent_session_file 000 "{tmp_path}"')
        assert r.stdout.strip() == f'{tmp_path}/000-hub-master/000.session'

    def test_flat_agent_falls_back_to_prompts(self, tmp_path):
        r = lib(f'agent_session_file 310 "{tmp_path}"')
        assert r.stdout.strip() == f'{tmp_path}/310.session'

    def test_satellite_never_reads_the_group_file(self, tmp_path):
        """Pas de cascade .model/.login : 300.session n'est pas à 300-100."""
        d = tmp_path / '300-demo'
        d.mkdir()
        (d / '300.session').write_text(f'claude1a\nclaude\n{SID}\n')
        r = lib(f'f=$(agent_session_file 300-100 "{tmp_path}"); '
                f'session_file_resume_id "$f" claude1a claude; echo "rc=$?"')
        assert r.stdout.strip() == 'rc=1'


class TestSessionFileContent:
    def test_written_file_is_private_and_read_back(self, tmp_path):
        f = tmp_path / '300-300.session'
        r = lib(f'session_file_write "{f}" claude3a claude {SID} && '
                f'session_file_resume_id "{f}" claude3a claude')
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == SID
        assert f.read_text() == f'claude3a\nclaude\n{SID}\n'
        assert stat.S_IMODE(f.stat().st_mode) == 0o600

    @pytest.mark.parametrize('profile,cli,sid', [
        ('', 'claude', SID),
        ('claude1a', 'gemini', SID),
        ('claude1a', 'claude', 'not-a-uuid'),
        ('claude1a', 'claude', f'{SID}; rm -rf /'),
        ('claude 1a', 'claude', SID),
    ])
    def test_invalid_values_are_never_written(self, tmp_path, profile, cli, sid):
        f = tmp_path / '300-300.session'
        r = lib(f'session_file_write "{f}" "{profile}" "{cli}" "{sid}"; echo "rc=$?"')
        assert r.stdout.strip() == 'rc=1'
        assert not f.exists()

    @pytest.mark.parametrize('content,want_profile,want_cli,reason', [
        (f'claude3a\nclaude\n{SID}\n', 'claude1a', 'claude', 'profil claude3a'),
        (f'codex1a\ncodex\n{SID}\n', 'claude1a', 'claude', 'moteur codex'),
        ('claude1a\nclaude\nnot-a-uuid\n', 'claude1a', 'claude', 'illisible'),
        (f'claude1a\nclaude\n{SID}\nextra\n', 'claude1a', 'claude', 'illisible'),
        ('', 'claude1a', 'claude', 'illisible'),
    ])
    def test_a_file_that_does_not_match_is_refused(self, tmp_path, content,
                                                   want_profile, want_cli, reason):
        f = tmp_path / '300-300.session'
        f.write_text(content)
        r = lib(f'session_file_resume_id "{f}" {want_profile} {want_cli}; echo "rc=$?"')
        out = r.stdout.strip().splitlines()
        assert out[-1] == 'rc=2'
        assert reason in out[0]

    def test_archive_moves_to_removed_and_never_deletes(self, tmp_path):
        f = tmp_path / '300-300.session'
        f.write_text(f'claude1a\nclaude\n{SID}\n')
        removed = tmp_path / 'removed'
        r = lib(f'session_file_archive "{f}" "{removed}"')
        assert not f.exists()
        dest = Path(r.stdout.strip())
        assert dest.parent == removed and dest.name.endswith('_300-300.session')
        assert dest.read_text() == f'claude1a\nclaude\n{SID}\n'


# ── Bridge : « deviens agent » rejoué, « Continue. » seulement en nouvelle session

def _bridge(tmp_path, x45=False):
    sys.path.insert(0, str(BASE_DIR / 'scripts' / 'agent-bridge'))
    from queue import Queue
    from agent import TmuxAgent
    d = tmp_path / '300-demo'
    d.mkdir()
    (d / '300-300.history').write_text('2026-11-14 10:00 | tâche précédente\n')
    if x45:
        prompt = d / 'x45'
        prompt.mkdir()
    else:
        prompt = d / '300-300.md'
        prompt.write_text('# agent\n')
    bridge = object.__new__(TmuxAgent)
    bridge.agent_id = '300-300'
    bridge.prompt_queue = Queue()
    bridge._log = lambda *a, **k: None
    bridge._find_prompt_file = lambda: str(prompt)
    bridge._get_x45_files = lambda p: ['RULES.md', '300-300-system.md']
    return bridge, prompt


def _queued(bridge):
    bridge._queue_auto_init()
    items = []
    while not bridge.prompt_queue.empty():
        items.append(bridge.prompt_queue.get_nowait())
    assert all(i['from_agent'] == 'auto_init' for i in items)
    return [i['prompt'] for i in items]


class TestBridgeAutoInit:
    def test_resumed_flag_is_read_from_the_environment(self, monkeypatch):
        sys.path.insert(0, str(BASE_DIR / 'scripts' / 'agent-bridge'))
        from agent import TmuxAgent
        monkeypatch.setenv('AGENT_RESUMED', '1')
        assert TmuxAgent._cli_session_resumed() is True
        monkeypatch.delenv('AGENT_RESUMED')
        assert TmuxAgent._cli_session_resumed() is False

    def test_new_session_gets_identity_then_history(self, tmp_path, monkeypatch):
        monkeypatch.delenv('AGENT_RESUMED', raising=False)
        bridge, prompt = _bridge(tmp_path)
        prompts = _queued(bridge)
        assert prompts[0] == f'deviens agent {prompt}'
        assert len(prompts) == 2 and prompts[1].endswith('Continue.')

    def test_resumed_session_gets_identity_without_continue(self, tmp_path, monkeypatch):
        """Une conversation reprise peut n'avoir jamais été amorcée (arrêt
        pendant la configuration du CLI) : « deviens agent » est rejoué ;
        « Continue. » ferait refaire la dernière tâche."""
        monkeypatch.setenv('AGENT_RESUMED', '1')
        bridge, prompt = _bridge(tmp_path)
        assert _queued(bridge) == [f'deviens agent {prompt}']

    def test_resumed_x45_agent_rereads_its_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv('AGENT_RESUMED', '1')
        bridge, _ = _bridge(tmp_path, x45=True)
        prompts = _queued(bridge)
        assert len(prompts) == 1
        assert prompts[0].startswith("Lis ces fichiers dans l'ordre et deviens cet agent")

    def test_auto_init_is_queued_before_delivery_opens(self):
        src = (BASE_DIR / 'scripts' / 'agent-bridge' / 'agent.py').read_text()
        run = src[src.index('    def run(self):'):]
        # Le verrou A6 n'est levé qu'une fois l'amorçage en queue.
        assert run.index('self._queue_auto_init()') < run.index('self._auto_init_queued.set()')

    def test_agent_sh_and_infra_pass_the_flag_only_when_resumed(self):
        for name, var in (('agent.sh', 'resumed'), ('infra.sh', 'RESUMED')):
            src = (BASE_DIR / 'scripts' / name).read_text()
            assert '${%s:+AGENT_RESUMED=1 }' % var in src, name


# ── Bout en bout sur CLI factices ────────────────────────────────────────────

FAKE_REDIS = r'''#!/bin/bash
# redis-cli factice : PING répond, le reste est vide (aucun état).
for a in "$@"; do
    case "$a" in ping|PING) echo PONG; exit 0 ;; esac
done
exit 0
'''


@pytest.fixture
def ns(install):
    """Harnais update + redis-cli et lsof factices : `start` exige l'infra."""
    bindir = install.root / 'bin'
    (bindir / 'redis-cli').write_text(FAKE_REDIS)
    (bindir / 'lsof').write_text('#!/bin/bash\nexit 0\n')
    for name in ('redis-cli', 'lsof'):
        (bindir / name).chmod(0o755)
    return install


def _agent_sh(ns, *args, **extra):
    env = dict(ns.env, **extra)
    return subprocess.run(['bash', str(ns.base / 'scripts' / 'agent.sh'), *args],
                          capture_output=True, text=True, timeout=180, env=env)


def _file(ns, agent_id):
    return ns.base / 'prompts' / '300-demo' / f'{agent_id}.session'


def _alive(ns, session):
    return _tmux(ns, 'has-session', '-t', session).returncode == 0


def _archived(ns, agent_id):
    removed = ns.base / 'removed'
    return sorted(removed.glob(f'*_{agent_id}.session')) if removed.exists() else []


def _last_sid(pane):
    """Identifiant de la DERNIÈRE session lancée dans le pane (repli compris)."""
    return pane.rsplit('SESSION ', 1)[1].split()[0]


def _bridge_line(ns, session):
    return _tmux(ns, 'capture-pane', '-t', f'{session}:bridge', '-p', '-J').stdout


class TestStopSavesTheSession:
    @pytest.mark.parametrize('agent_id,cli', [('300-300', 'claude'), ('300-301', 'codex')])
    def test_agent_at_rest_saves_profile_engine_and_id(self, ns, agent_id, cli):
        session, sid = _start_fake(ns, agent_id, cli)
        r = _agent_sh(ns, 'stop', agent_id)
        assert r.returncode == 0, r.stdout + r.stderr
        assert not _alive(ns, session)
        f = _file(ns, agent_id)
        assert f.read_text() == f'{cli}1a\n{cli}\n{sid}\n'
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
        assert 'sauvegardée' in r.stdout

    def test_profile_is_the_one_of_the_process(self, ns):
        """Le .login dit claude1a, le process tourne sur claude3a : la session
        vit dans claude3a — c'est lui qui est écrit."""
        _, sid = _start_fake(ns, '300-300', 'claude', profile='claude3a')
        _agent_sh(ns, 'stop', '300-300')
        assert _file(ns, '300-300').read_text() == f'claude3a\nclaude\n{sid}\n'

    @pytest.mark.parametrize('show', [
        'Enter to select · ↑/↓ to navigate · Esc to cancel',
        'Would you like to proceed?',
    ])
    def test_agent_not_at_rest_is_stopped_without_saving(self, ns, show):
        before = f'claude1a\nclaude\n{SID}\n'
        _file(ns, '300-300').write_text(before)
        session, _ = _start_fake(ns, '300-300', 'claude', env=f"FAKE_SHOW='{show}'")
        r = _agent_sh(ns, 'stop', '300-300')
        assert r.returncode == 0, r.stdout + r.stderr
        assert not _alive(ns, session)                    # jamais bloquant
        assert 'sans sauvegarde' in r.stdout
        assert _file(ns, '300-300').read_text() == before  # fichier intact

    def test_working_agent_is_stopped_without_saving(self, ns):
        status = '  ⏵⏵ bypass permissions on · esc to interrupt'
        session, _ = _start_fake(ns, '300-300', 'claude', env=f"FAKE_STATUS='{status}'")
        r = _agent_sh(ns, 'stop', '300-300')
        assert not _alive(ns, session)
        assert 'travaille' in r.stdout and not _file(ns, '300-300').exists()

    def test_group_members_are_saved_in_parallel(self, ns):
        """`stop 300` sur un groupe x45 : chaque membre est sauvegardé, en
        parallèle (bouton stop du dashboard : 120 s pour tout le groupe)."""
        for member in ('300-300', '300-301'):
            (ns.base / 'prompts' / '300-demo' / f'{member}.md').write_text('')
        _, sid_claude = _start_fake(ns, '300-300', 'claude')
        _, sid_codex = _start_fake(ns, '300-301', 'codex')
        t0 = time.monotonic()
        r = _agent_sh(ns, 'stop', '300')
        elapsed = time.monotonic() - t0
        assert r.returncode == 0, r.stdout + r.stderr
        assert _file(ns, '300-300').read_text() == f'claude1a\nclaude\n{sid_claude}\n'
        assert _file(ns, '300-301').read_text() == f'codex1a\ncodex\n{sid_codex}\n'
        assert elapsed < 30, f'membres arrêtés en série ? {elapsed:.1f} s'

    def test_stop_all_saves_every_agent(self, ns):
        _, sid_claude = _start_fake(ns, '300-300', 'claude')
        _, sid_codex = _start_fake(ns, '300-301', 'codex')
        t0 = time.monotonic()
        r = _agent_sh(ns, 'stop', 'all')
        elapsed = time.monotonic() - t0
        assert r.returncode == 0, r.stdout + r.stderr
        assert _file(ns, '300-300').read_text().endswith(f'{sid_claude}\n')
        assert _file(ns, '300-301').read_text().endswith(f'{sid_codex}\n')
        assert elapsed < 30, f'stop all séquentiel ? {elapsed:.1f} s'


class TestStartResumesTheSession:
    @pytest.mark.parametrize('agent_id,cli', [('300-300', 'claude'), ('300-301', 'codex')])
    def test_saved_session_is_resumed(self, ns, agent_id, cli):
        _file(ns, agent_id).write_text(f'{cli}1a\n{cli}\n{SID}\n')
        r = _agent_sh(ns, 'start', agent_id)
        assert r.returncode == 0, r.stdout + r.stderr
        session = f'agent-{agent_id}'
        assert f'RESUMED {SID}' in _pane(ns, session)
        assert f'session {SID} reprise' in r.stdout
        assert _wait_for(lambda: 'AGENT_RESUMED=1' in _bridge_line(ns, session), 10)
        assert _file(ns, agent_id).exists()        # suit encore la session en cours

    def test_stop_then_start_comes_back_on_the_same_session(self, ns):
        _, sid = _start_fake(ns, '300-300', 'claude')
        assert _agent_sh(ns, 'stop', '300-300').returncode == 0
        r = _agent_sh(ns, 'start', '300-300')
        assert r.returncode == 0, r.stdout + r.stderr
        assert f'RESUMED {sid}' in _pane(ns, 'agent-300-300')
        # Second cycle : le bridge lancé par start est arrêté avant la sortie.
        assert _agent_sh(ns, 'stop', '300-300').returncode == 0
        assert _file(ns, '300-300').read_text() == f'claude1a\nclaude\n{sid}\n'

    @pytest.mark.parametrize('content,reason', [
        (f'claude3a\nclaude\n{SID}\n', 'profil claude3a'),
        (f'claude1a\ncodex\n{SID}\n', 'moteur codex'),
        ('claude1a\nclaude\nnot-a-uuid\n', 'illisible'),
    ])
    def test_a_file_that_does_not_match_starts_fresh(self, ns, content, reason):
        _file(ns, '300-300').write_text(content)
        r = _agent_sh(ns, 'start', '300-300')
        assert r.returncode == 0, r.stdout + r.stderr
        pane = _pane(ns, 'agent-300-300')
        assert 'RESUMED' not in pane and 'SESSION ' in pane
        assert reason in r.stdout + r.stderr
        # Ancien fichier archivé ; le nouveau pointe la session neuve (relevée
        # au démarrage).
        assert _file(ns, '300-300').read_text() == f'claude1a\nclaude\n{_last_sid(pane)}\n'
        assert [p.read_text() for p in _archived(ns, '300-300')] == [content]
        assert _wait_for(lambda: 'AGENT_CLI=' in _bridge_line(ns, 'agent-300-300'), 10)
        assert 'AGENT_RESUMED' not in _bridge_line(ns, 'agent-300-300')

    def test_fresh_flag_ignores_and_archives_the_saved_session(self, ns):
        _file(ns, '300-300').write_text(f'claude1a\nclaude\n{SID}\n')
        r = _agent_sh(ns, 'start', '300-300', '--fresh')
        assert r.returncode == 0, r.stdout + r.stderr
        pane = _pane(ns, 'agent-300-300')
        assert 'RESUMED' not in pane
        assert _file(ns, '300-300').read_text() == f'claude1a\nclaude\n{_last_sid(pane)}\n'
        assert _last_sid(pane) != SID and len(_archived(ns, '300-300')) == 1
        assert '--fresh' in r.stdout + r.stderr

    def test_resume_that_does_not_start_falls_back_to_a_new_session(self, ns):
        (ns.base / 'fake-resume-fail').write_text('')
        _file(ns, '300-300').write_text(f'claude1a\nclaude\n{SID}\n')
        t0 = time.monotonic()
        r = _agent_sh(ns, 'start', '300-300')
        assert r.returncode == 0, r.stdout + r.stderr
        assert time.monotonic() - t0 < 45            # pas les 60 s d'attente
        pane = _pane(ns, 'agent-300-300')
        assert 'RESUMED' not in pane and 'SESSION ' in pane
        assert "n'a pas démarré" in r.stdout
        assert _file(ns, '300-300').read_text() == f'claude1a\nclaude\n{_last_sid(pane)}\n'
        assert _last_sid(pane) != SID and len(_archived(ns, '300-300')) == 1

    def test_restart_resumes_the_session(self, ns):
        _, sid = _start_fake(ns, '300-300', 'claude')
        r = _agent_sh(ns, 'restart', '300-300')
        assert r.returncode == 0, r.stdout + r.stderr
        assert f'RESUMED {sid}' in _pane(ns, 'agent-300-300')


class TestStartRecordsTheSession:
    """Sécurité en plus de la sortie : l'identifiant de la session en cours est
    relevé au démarrage par la commande de statut du CLI (/status) et écrit
    aussitôt. Un arrêt qui ne peut pas le relire (agent occupé, commandes en
    fond, CLI qui ne quitte pas — 338-138/238, 366-266, 385-185 le
    2026-11-16) laisse un fichier qui pointe la conversation en cours."""

    @pytest.mark.parametrize('agent_id,cli', [('300-300', 'claude'), ('300-301', 'codex')])
    def test_new_session_is_recorded_at_start(self, ns, agent_id, cli):
        r = _agent_sh(ns, 'start', agent_id)
        assert r.returncode == 0, r.stdout + r.stderr
        sid = _pane(ns, f'agent-{agent_id}').split('SESSION ', 1)[1].split()[0]
        assert _file(ns, agent_id).read_text() == f'{cli}1a\n{cli}\n{sid}\n'
        assert f'session {sid} relevée au démarrage' in r.stdout

    @pytest.mark.parametrize('agent_id,cli', [('300-300', 'claude'), ('300-301', 'codex')])
    def test_resumed_session_is_recorded_again(self, ns, agent_id, cli):
        _file(ns, agent_id).write_text(f'{cli}1a\n{cli}\n{SID}\n')
        r = _agent_sh(ns, 'start', agent_id)
        assert r.returncode == 0, r.stdout + r.stderr
        assert f'RESUMED {SID}' in _pane(ns, f'agent-{agent_id}')
        assert _file(ns, agent_id).read_text() == f'{cli}1a\n{cli}\n{SID}\n'
        assert 'annonce' not in r.stdout          # pas d'écart reprise/statut

    def test_status_dialog_is_closed_only_where_there_is_one(self, ns):
        """Claude : panneau /status fermé par Échap avant le bridge ; codex :
        fiche dans le transcript, aucune touche de fermeture."""
        for agent_id in ('300-300', '300-301'):
            r = _agent_sh(ns, 'start', agent_id)
            assert r.returncode == 0, r.stdout + r.stderr
        assert 'STATUS CLOSED' in _pane(ns, 'agent-300-300')
        assert 'STATUS CLOSED' not in _pane(ns, 'agent-300-301')

    def test_busy_stop_after_recorded_start_resumes_next_time(self, ns):
        r = _agent_sh(ns, 'start', '300-300')
        assert r.returncode == 0, r.stdout + r.stderr
        sid = _file(ns, '300-300').read_text().split()[-1]
        # Arrêt sans sauvegarde (CLI qui n'imprime rien à la sortie) : le
        # fichier relevé au démarrage pointe encore la conversation.
        (ns.base / 'fake-no-hint').write_text('')
        assert _agent_sh(ns, 'stop', '300-300').returncode == 0
        (ns.base / 'fake-no-hint').unlink()
        r = _agent_sh(ns, 'start', '300-300')
        assert r.returncode == 0, r.stdout + r.stderr
        assert f'RESUMED {sid}' in _pane(ns, 'agent-300-300')

    def test_missing_status_never_blocks_the_start(self, ns):
        (ns.base / 'fake-no-status').write_text('')
        r = _agent_sh(ns, 'start', '300-300')
        assert r.returncode == 0, r.stdout + r.stderr
        assert 'non relevé au démarrage' in r.stdout
        assert not _file(ns, '300-300').exists()


class TestUpdateKeepsTheFileInStep:
    def test_resumed_update_writes_the_session_file(self, ns):
        _, sid = _start_fake(ns, '300-300', 'claude')
        r = _agent_sh(ns, 'update', '300-300')
        assert r.returncode == 0, r.stdout + r.stderr
        assert f'mode=resumed session={sid}' in r.stdout
        assert _file(ns, '300-300').read_text() == f'claude1a\nclaude\n{sid}\n'
