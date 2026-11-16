"""Bouton « update » : relancer le CLI d'un agent en reprenant SA session.

`agent.sh update <id>` quitte le CLI par Ctrl-C, lit l'identifiant que le CLI
imprime en quittant (Claude Code : `--resume <id>`, Codex : `codex resume
<id>`), relance le même profil avec reprise et réapplique modèle/effort. Le
bridge n'est pas relancé ; il retient ses livraisons pendant la relance
(agent:<id>:cli_hold) — sinon un prompt serait collé, puis EXÉCUTÉ, dans le
shell du pane.

Invariants verrouillés ici :
1. la commande de reprise est construite par la couche moteur, UUID strict ;
2. l'identifiant vient des marqueurs (resume_hint_pattern), jamais d'un
   ancien identifiant resté dans le scrollback ;
3. le bridge annonce cli_hold et ne livre rien tant que le verrou existe ;
4. rien n'est touché si l'agent n'est pas au repos (tour en cours, question,
   menu…) — aucun forçage ;
5. la relance garde le profil du process (claude1a, codex1a, claude3a…) ; un
   profil ou un moteur changé depuis le lancement est refusé (restart) ;
6. bout en bout, sur des CLI factices : reprise claude et codex, refus sans
   effet, repli sur un redémarrage complet quand rien n'est imprimé.
"""
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
ENGINES_SH = BASE_DIR / 'scripts' / 'engines.sh'
sys.path.insert(0, str(BASE_DIR / 'scripts' / 'agent-bridge'))
import engines  # noqa: E402

CLAUDE_ID = '2e441a85-1c7e-48d4-a4b9-3262f18680e7'
CODEX_ID = '01a1c626-0661-78b1-8b9e-c786c964e58b'

# Sorties réelles relevées sur mx5 le 2026-11-10 (capture-pane -J).
CLAUDE_EXIT = (
    "  Press Ctrl-C again to exit\n"
    "Resume this session with:\n"
    "claude --dangerously-skip-permissions --dangerously-skip-permissions "
    f"--model haiku --resume {CLAUDE_ID}\n"
    "ubuntu@mx5:~/multi-agent$ \n")
CODEX_EXIT = (
    "Token usage: total=9,463 input=9,458 (+ 12,032 cached) output=5\n"
    "To continue this session, run:\n"
    f"  codex resume {CODEX_ID}\n"
    "Or run codex resume and select Répondre OK.\n")


def sh(snippet, env=None):
    return subprocess.run(['bash', '-c', f'source "{ENGINES_SH}"\n{snippet}'],
                          capture_output=True, text=True, timeout=15, env=env)


class TestLaunchCommand:
    def test_claude_resume_is_an_option(self):
        r = sh(f'engine_launch_cmd claude /b/login claude1a "" "" "" {CLAUDE_ID}')
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == (
            'CLAUDE_CONFIG_DIR=/b/login/claude1a claude '
            f'--dangerously-skip-permissions --resume {CLAUDE_ID}')

    def test_codex_resume_is_a_subcommand_before_the_options(self):
        r = sh(f'engine_launch_cmd codex /b/login codex1a "" "" "" {CODEX_ID}')
        assert r.returncode == 0, r.stderr
        cmd = r.stdout.strip()
        assert f' codex resume {CODEX_ID} --dangerously-bypass-approvals-and-sandbox' in cmd
        # Les verrous de facturation restent en place sur la reprise.
        assert cmd.startswith('env -u OPENAI_API_KEY -u CODEX_API_KEY ')
        assert cmd.endswith('-c forced_login_method=chatgpt')

    @pytest.mark.parametrize('bad', ['abc', f'{CLAUDE_ID}; rm -r x', f'$({CLAUDE_ID})',
                                     CLAUDE_ID[:-1]])
    def test_resume_id_must_be_a_strict_uuid(self, bad):
        r = sh(f"engine_launch_cmd claude /b/login claude1a '' '' '' '{bad}'")
        assert r.returncode == 1 and r.stdout == ''

    def test_without_resume_the_command_is_unchanged(self):
        for cli, login in (('claude', 'claude1a'), ('codex', 'codex1a')):
            plain = sh(f'engine_launch_cmd {cli} /b/login {login} ""').stdout
            assert 'resume' not in plain


class TestResumeMarkers:
    @pytest.mark.parametrize('cli', engines.ENGINES)
    def test_pattern_has_exactly_one_group(self, cli):
        import re
        markers = engines.load_markers(cli)
        assert re.compile(markers['resume_hint_pattern']).groups == 1
        assert isinstance(markers['resume_loading_markers'], list)

    def test_real_exit_texts(self):
        assert engines.resume_session_ids(
            CLAUDE_EXIT, engines.load_markers('claude')) == [CLAUDE_ID]
        assert engines.resume_session_ids(
            CODEX_EXIT, engines.load_markers('codex')) == [CODEX_ID]

    def test_an_engine_never_reads_the_other_engines_hint(self):
        assert engines.resume_session_ids(CODEX_EXIT, engines.load_markers('claude')) == []
        assert engines.resume_session_ids(CLAUDE_EXIT, engines.load_markers('codex')) == []

    def test_wrapped_uuid_needs_a_joined_capture(self):
        """Sans `capture-pane -J`, le pane coupe l'UUID : aucun faux identifiant."""
        wrapped = CLAUDE_EXIT.replace(CLAUDE_ID, CLAUDE_ID[:23] + '\n' + CLAUDE_ID[23:])
        assert engines.resume_session_ids(wrapped, engines.load_markers('claude')) == []

    def test_cli_returns_ids_in_order(self):
        text = CLAUDE_EXIT.replace(CLAUDE_ID, str(uuid.UUID(int=1))) + CLAUDE_EXIT
        r = subprocess.run([sys.executable, str(BASE_DIR / 'scripts/agent-bridge/engines.py'),
                            'resume-ids', '--cli', 'claude'],
                           input=text, capture_output=True, text=True, timeout=15)
        assert r.returncode == 0
        assert r.stdout.split() == [str(uuid.UUID(int=1)), CLAUDE_ID]

    def test_loading_marker_is_inert_for_claude(self):
        r = sh('engine_marker_get claude resume_loading_markers')
        assert r.stdout.strip() == engines.NEVER_MATCH


class TestBridgeHold:
    def _agent(self, exists):
        from agent import TmuxAgent
        agent = object.__new__(TmuxAgent)
        agent.agent_id = '300-300'
        agent.redis = MagicMock()
        agent.redis.exists.side_effect = exists
        agent.running = True
        agent._log = MagicMock()
        return agent

    def test_hold_is_read_from_its_own_key(self):
        agent = self._agent(lambda key: 1)
        assert agent._cli_hold_active() is True
        agent.redis.exists.assert_called_with('agent:300-300:cli_hold')

    def test_fake_or_failing_redis_is_not_a_hold(self):
        assert self._agent(lambda key: 0)._cli_hold_active() is False
        assert self._agent(ConnectionError('down'))._cli_hold_active() is False
        agent = self._agent(None)
        agent.redis = MagicMock()          # exists() → MagicMock, jamais == 1
        assert agent._cli_hold_active() is False

    def test_delivery_waits_until_release(self, monkeypatch):
        answers = iter([1, 1, 1, 0])
        agent = self._agent(lambda key: next(answers))
        monkeypatch.setattr('agent.time.sleep', lambda s: None)
        agent._wait_cli_hold()
        assert agent.redis.exists.call_count == 4

    def test_queue_and_auto_responder_respect_the_hold(self):
        source = (BASE_DIR / 'scripts/agent-bridge/agent.py').read_text()
        queue_body = source.split('def _process_queue(self):', 1)[1]
        assert queue_body.index('self._wait_cli_hold()') < queue_body.index('tui_reserved = self.state')
        auto_body = source.split('def _auto_respond_while_idle', 1)[1].split('\n    def ', 1)[0]
        assert 'self._cli_hold_active()' in auto_body

    def test_capability_is_published_with_the_status(self):
        from agent import BRIDGE_CAPS
        source = (BASE_DIR / 'scripts/agent-bridge/agent.py').read_text()
        status_body = source.split('def _set_redis_status(self):', 1)[1].split('\n    def ', 1)[0]
        assert '"bridge_caps": BRIDGE_CAPS' in status_body
        assert 'cli_hold' in BRIDGE_CAPS.split()


IDLE = {'busy': False, 'compacted': False, 'done_compacting': False,
        'context_limit': False, 'api_error': False, 'has_bashes': False,
        'plan_mode': False, 'waiting_approval': False, 'login_required': False,
        'claude_alive': True}


class TestRestBlockers:
    """« Au repos » : la lecture du pane du dashboard, plus approbation et file."""

    @pytest.mark.parametrize('cli', engines.ENGINES)
    def test_idle_agent_has_no_blocker(self, cli):
        assert engines.rest_blockers(IDLE, 'texte quelconque', engines.load_markers(cli)) == []

    @pytest.mark.parametrize('field,reason', [
        ('busy', 'travaille'), ('has_bashes', 'commandes_en_fond'),
        ('waiting_approval', 'question'), ('plan_mode', 'plan_mode'),
        ('login_required', 'login'), ('api_error', 'erreur'),
        ('context_limit', 'erreur')])
    def test_each_pane_state_blocks(self, field, reason):
        state = dict(IDLE, **{field: True})
        assert reason in engines.rest_blockers(state, '', engines.load_markers('claude'))

    def test_dead_cli_and_compaction_block(self):
        m = engines.load_markers('claude')
        assert engines.rest_blockers(dict(IDLE, claude_alive=False), '', m) == ['cli_absent']
        assert engines.rest_blockers(dict(IDLE, compacted=True), '', m) == ['compaction']
        assert engines.rest_blockers(
            dict(IDLE, compacted=True, done_compacting=True), '', m) == []

    @pytest.mark.parametrize('cli', engines.ENGINES)
    def test_approval_and_queued_markers_are_read_from_the_pane(self, cli):
        m = engines.load_markers(cli)
        assert engines.rest_blockers(IDLE, f"x {m['approval']} ?", m) == ['question']
        # `queued` peut être une liste (Codex : un rendu par version du CLI).
        for queued in engines.queued_markers(m):
            assert engines.rest_blockers(IDLE, f"x {queued}", m) == ['messages_en_file']

    def test_question_markers_of_each_engine(self):
        """Menu / question : le marqueur waiting_select de chaque moteur."""
        assert engines.load_markers('claude')['waiting_select'] == 'Enter to select'
        assert engines.load_markers('codex')['waiting_select'] == 'Press enter to confirm'


class TestBackendEndpoint:
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
        coro = agents_router.update_agent(agent_id=agent_id)
        return asyncio.run(coro), calls

    def test_resumed_result_is_parsed(self, monkeypatch):
        out = ('\x1b[0;32m[OK]\x1b[0m Agent 300-300: claude relancé\n'
               f'UPDATE_RESULT agent=300-300 mode=resumed session={CLAUDE_ID}\n')
        result, calls = self._call(monkeypatch, 0, out)
        assert result['results'] == [
            {'agent_id': '300-300', 'mode': 'resumed', 'session_id': CLAUDE_ID}]
        assert '\x1b' not in result['output']
        assert calls[0][0] == 'bash' and calls[0][-2:] == ['update', '300-300']

    @pytest.mark.parametrize('rc,reason', [
        (3, 'not_idle'), (4, 'bridge_reload'), (5, 'restart_required')])
    def test_refusals_are_conflicts_with_a_reason(self, monkeypatch, rc, reason):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            self._call(monkeypatch, rc, '[WARN] 300-300 refusé')
        assert exc.value.status_code == 409
        assert exc.value.detail == {'reason': reason, 'message': '[WARN] 300-300 refusé'}

    def test_there_is_no_force(self):
        """Pas au repos = pas d'update : aucun paramètre ne lève le refus."""
        import inspect
        from web.backend.multi_agent.routers import agents as agents_router
        assert list(inspect.signature(agents_router.update_agent).parameters) == ['agent_id']
        source = (BASE_DIR / 'scripts' / 'agent.sh').read_text()
        assert 'FORCE_UPDATE' not in source

    def test_failure_is_a_server_error(self, monkeypatch):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            self._call(monkeypatch, 1, "[ERROR] 300-300: claude n'a pas quitté")
        assert exc.value.status_code == 500

    def test_architect_needs_the_explicit_opening(self, monkeypatch):
        _result, calls = self._call(monkeypatch, 0, '', agent_id='000')
        assert 'ALLOW_PROTECTED_000=1' in calls[0]


# ── Bout en bout : agent.sh update sur des CLI factices, tmux isolé ──────────

FAKE_CLI = r'''
import os, signal, sys, termios, time, tty, uuid

flavor, args = sys.argv[1], sys.argv[2:]
if '--version' in args:
    print(f'{flavor} fake 9.9'); sys.exit(0)
sid = None
if flavor == 'codex' and args[:1] == ['resume']:
    sid = args[1]
if flavor == 'claude' and '--resume' in args:
    sid = args[args.index('--resume') + 1]
resumed = sid is not None
if resumed and os.path.exists('fake-resume-fail'):
    # Session introuvable dans le profil : le CLI le dit et sort.
    print('No conversation found with session ID: ' + sid, flush=True)
    sys.exit(1)
sid = sid or str(uuid.uuid4())
print('SESSION ' + sid, flush=True)
if flavor == 'codex':
    print('>_ OpenAI Codex (v9.9)', flush=True)
    if resumed:
        print('Resuming session…', flush=True); time.sleep(1.5)
        print('\x1b[1A\x1b[2K', end='', flush=True)
if resumed:
    print('RESUMED ' + sid, flush=True)
print('❯ ' if flavor == 'claude' else '› ', flush=True)
# Ligne de statut des vrais TUI (status_line des marqueurs) : sans elle, le
# scan du dashboard lit un agent occupé (claude) ou en erreur (codex).
print(os.environ.get('FAKE_STATUS') or (
    '  ⏵⏵ bypass permissions on (shift+tab to cycle)' if flavor == 'claude'
    else '  gpt-5.6-sol high · 100% left · ~/b'), flush=True)
if os.environ.get('FAKE_SHOW'):
    print(os.environ['FAKE_SHOW'], flush=True)

def quit_cli():
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, saved)
    if not os.path.exists('fake-no-hint'):
        if flavor == 'claude':
            print('Resume this session with:\nclaude --resume ' + sid, flush=True)
        else:
            print('To continue this session, run:\n  codex resume ' + sid, flush=True)
    os._exit(0)

# Ctrl-C ne quitte PAS (comportement relevé mx6 2026-11-13) : seule la
# commande de sortie (exit_command) ferme le CLI.
def on_sigint(*_):
    print('Press Ctrl-C again to exit', flush=True)
signal.signal(signal.SIGINT, on_sigint)

saved = termios.tcgetattr(sys.stdin)
tty.setcbreak(sys.stdin)
line, picker = '', None
while True:
    ch = os.read(0, 1).decode(errors='replace')
    if ch == '\x15':
        line = ''; continue
    if ch == '\x1b':
        if picker == 'status':
            print('STATUS CLOSED', flush=True)
        picker = None; continue
    if picker and ch.isdigit():
        if picker == 'model':
            print('Select Reasoning Level\n1. Low\n2. Medium\n3. High', flush=True)
            picker = 'effort'
        else:
            print('Model changed', flush=True); picker = None
        continue
    if ch not in '\r\n':
        line += ch; continue
    cmd, line = line.strip(), ''
    if cmd == '/exit':
        quit_cli()
    if cmd.startswith('/effort '):
        print('Set effort level to ' + cmd.split()[-1], flush=True)
    elif cmd == '/advisor off':
        print('Advisor disabled', flush=True)
    elif cmd == '/status' and not os.path.exists('fake-no-status'):
        # Formats relevés mx81 2026-11-16 (Claude Code 2.1.325, codex-cli
        # 0.169.0) ; la fiche codex porte aussi l'UUID du workspace.
        if flavor == 'claude':
            print('  Settings  Status   Config\n  Session ID:        ' + sid
                  + '\n  Esc to cancel', flush=True)
            picker = 'status'          # panneau ouvert : Échap le ferme
        else:
            print('  ChatGPT workspace:   ' + str(uuid.uuid4())
                  + '\n  Session:             ' + sid, flush=True)
    elif cmd == '/model' and flavor == 'codex':
        print('Select Model and Effort\n1. gpt-5.6-sol (current)', flush=True)
        picker = 'model'
    elif cmd.startswith('/model '):
        print('Set model to ' + cmd.split()[-1], flush=True)
'''


@pytest.fixture
def install():
    """Arbre minimal : scripts copiés, prompts de démo, CLI factices, tmux isolé."""
    root = Path(tempfile.mkdtemp(prefix='mu', dir='/tmp'))   # chemin court : socket tmux
    base = root / 'b'
    (base / 'scripts' / 'agent-bridge').mkdir(parents=True)
    for name in ('agent.sh', 'lib.sh', 'engines.sh', 'redis.sh'):
        shutil.copy(BASE_DIR / 'scripts' / name, base / 'scripts' / name)
    for name in ('engines.py', 'markers.claude.yaml', 'markers.codex.yaml'):
        shutil.copy(BASE_DIR / 'scripts' / 'agent-bridge' / name,
                    base / 'scripts' / 'agent-bridge' / name)
    prompts = base / 'prompts' / '300-demo'
    prompts.mkdir(parents=True)
    (prompts / '300-300.model').write_text('claude-opus-5\n')
    (prompts / '300-301.model').write_text('gpt-5.6-sol\n')
    (base / 'prompts' / 'default.login').write_text('login1a\n')
    bindir = root / 'bin'
    bindir.mkdir()
    (root / 'fake_cli.py').write_text(FAKE_CLI)
    for cli in ('claude', 'codex'):
        wrapper = bindir / cli
        # exec -a : #{pane_current_command} lit argv[0] → « claude » / « codex »
        wrapper.write_text(f'#!/bin/bash\nexec -a {cli} {sys.executable} {root}/fake_cli.py {cli} "$@"\n')
        wrapper.chmod(0o755)
    tmuxdir = root / 't'
    tmuxdir.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in ('TMUX', 'MA_RUNTIME_DIR')}
    env.update(PATH=f'{bindir}:{env["PATH"]}', TMUX_TMPDIR=str(tmuxdir),
               REDIS_PORT='1', REDIS_HOST='127.0.0.1', REDIS_PASSWORD='',
               CODEX_SKIP_LOGIN_CHECK='1', TMUX_COLS='110', TMUX_ROWS='40')
    ns = SimpleNamespace(root=root, base=base, env=env)
    # Shell nu dans les panes : ~/.bashrc pourrait aliaser `claude` ou remettre
    # le vrai binaire devant les CLI factices dans le PATH.
    _tmux(ns, 'new-session', '-d', '-s', 'ma-test-keep')
    _tmux(ns, 'set-option', '-g', 'default-command', 'bash --norc --noprofile')
    yield ns
    subprocess.run(['tmux', 'kill-server'], env=env, capture_output=True)
    shutil.rmtree(root, ignore_errors=True)


def _tmux(ns, *args):
    return subprocess.run(['tmux', *args], env=ns.env, capture_output=True, text=True)


def _pane(ns, session):
    return _tmux(ns, 'capture-pane', '-t', f'{session}:0', '-p', '-J', '-S', '-').stdout


def _wait_for(predicate, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.2)
    return False


def _start_fake(ns, agent_id, cli, preamble='', profile=None, env=''):
    """Lance un CLI factice comme agent.sh : variable d'auth du profil en préfixe."""
    session = f'agent-{agent_id}'
    profile = profile or f'{cli}1a'          # default.login = login1a
    var = 'CLAUDE_CONFIG_DIR' if cli == 'claude' else 'CODEX_HOME'
    _tmux(ns, 'new-session', '-d', '-s', session, '-x', '110', '-y', '40')
    if preamble:
        _tmux(ns, 'send-keys', '-t', session, preamble, 'Enter')
    _tmux(ns, 'send-keys', '-t', session,
          f"cd '{ns.base}' && {env} {var}={ns.base}/login/{profile} {cli}", 'Enter')
    assert _wait_for(lambda: 'SESSION ' in _pane(ns, session)), _pane(ns, session)
    return session, _pane(ns, session).split('SESSION ', 1)[1].split()[0]


def _running_profile(ns, session, cli):
    """Profil lu dans l'environnement du process au premier plan du pane.

    Seule la variable du moteur compte : un process codex peut hériter d'un
    CLAUDE_CONFIG_DIR de son shell (et inversement).
    """
    var = 'CLAUDE_CONFIG_DIR' if cli == 'claude' else 'CODEX_HOME'
    pane_pid = _tmux(ns, 'display', '-p', '-t', f'{session}:0', '#{pane_pid}').stdout.strip()
    fg = subprocess.run(['ps', '-o', 'tpgid=', '-p', pane_pid],
                        capture_output=True, text=True).stdout.strip()
    for item in Path(f'/proc/{fg}/environ').read_bytes().split(b'\0'):
        key, _, value = item.decode().partition('=')
        if key == var:
            return os.path.basename(value)
    return None


def _update(ns, agent_id, **extra):
    env = dict(ns.env, **extra)
    return subprocess.run(['bash', str(ns.base / 'scripts' / 'agent.sh'), 'update', agent_id],
                          capture_output=True, text=True, timeout=180, env=env)


class TestAgentShUpdate:
    @pytest.mark.parametrize('agent_id,cli', [('300-300', 'claude'), ('300-301', 'codex')])
    def test_cli_is_relaunched_on_its_own_session(self, install, agent_id, cli):
        session, sid = _start_fake(install, agent_id, cli)
        r = _update(install, agent_id)
        assert r.returncode == 0, r.stdout + r.stderr
        assert f'UPDATE_RESULT agent={agent_id} mode=resumed session={sid}' in r.stdout
        assert f'RESUMED {sid}' in _pane(install, session)
        cmd = _tmux(install, 'display', '-p', '-t', f'{session}:0', '#{pane_current_command}')
        assert cmd.stdout.strip() == cli
        assert _running_profile(install, session, cli) == f'{cli}1a'   # même profil

    def _assert_untouched(self, ns, session, sid, r, rc):
        assert r.returncode == rc, r.stdout + r.stderr
        pane = _pane(ns, session)
        assert 'Press Ctrl-C' not in pane and 'RESUMED' not in pane
        assert pane.count('SESSION ') == 1 and f'SESSION {sid}' in pane

    @pytest.mark.parametrize('agent_id,cli,show,reason', [
        ('300-300', 'claude', 'Enter to select · ↑/↓ to navigate · Esc to cancel', 'question'),
        ('300-301', 'codex', 'Press enter to confirm or esc to cancel', 'question'),
        ('300-300', 'claude', 'Would you like to proceed?', 'question'),
        ('300-301', 'codex', '• Working (3s • esc to interrupt)', 'travaille'),
    ])
    def test_agent_not_at_rest_is_left_untouched(self, install, agent_id, cli, show, reason):
        session, sid = _start_fake(install, agent_id, cli, env=f"FAKE_SHOW='{show}'")
        r = _update(install, agent_id)
        self._assert_untouched(install, session, sid, r, 3)
        assert reason in r.stdout and 'pas au repos' in r.stdout

    def test_working_claude_is_left_untouched(self, install):
        status = '  ⏵⏵ bypass permissions on · esc to interrupt'
        session, sid = _start_fake(install, '300-300', 'claude', env=f"FAKE_STATUS='{status}'")
        r = _update(install, '300-300')
        self._assert_untouched(install, session, sid, r, 3)
        assert 'travaille' in r.stdout

    def test_other_profile_is_a_restart_not_an_update(self, install):
        """Le .login a changé depuis le lancement : la session vit dans claude3a."""
        session, sid = _start_fake(install, '300-300', 'claude', profile='claude3a')
        r = _update(install, '300-300')
        self._assert_untouched(install, session, sid, r, 5)
        assert 'claude3a' in r.stdout and 'claude1a' in r.stdout
        assert 'restart 300-300' in r.stdout

    def test_other_engine_is_a_restart_not_an_update(self, install):
        """Modèle passé en gpt-* depuis le lancement : claude tourne encore."""
        session, sid = _start_fake(install, '300-301', 'claude')
        r = _update(install, '300-301')
        self._assert_untouched(install, session, sid, r, 5)
        assert 'restart 300-301' in r.stdout

    def test_bridge_without_capability_is_refused(self, install):
        """Un bridge qui ne sait pas patienter collerait ses messages dans le shell."""
        session, sid = _start_fake(install, '300-300', 'claude')
        _tmux(install, 'new-window', '-t', session, '-n', 'bridge', 'sleep 600')
        _tmux(install, 'select-window', '-t', f'{session}:0')
        r = _update(install, '300-300')
        self._assert_untouched(install, session, sid, r, 4)
        assert 'reload-bridge 300-300' in r.stdout

    def test_old_id_in_scrollback_is_never_resumed(self, install):
        """Rien imprimé à la sortie → repli complet, pas l'ancien identifiant."""
        old = str(uuid.UUID(int=7))
        (install.base / 'fake-no-hint').write_text('')
        _start_fake(install, '300-300', 'claude', preamble=f'echo claude --resume {old}')
        r = _update(install, '300-300')
        assert r.returncode == 0, r.stdout + r.stderr
        assert 'UPDATE_RESULT agent=300-300 mode=restarted session=' in r.stdout
        assert old not in r.stdout.split('UPDATE_RESULT', 1)[1]

    def test_missing_session_is_an_error(self, install):
        r = _update(install, '300-300')
        assert r.returncode == 1 and 'not running' in r.stdout + r.stderr
