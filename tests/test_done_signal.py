"""
A7 — Signaux DONE/SCORE via canal Redis dédié (scripts/done.sh)

Le bridge ne doit plus scanner le texte des réponses du modèle pour
relayer des signaux de complétion (anti faux DONE par hallucination).
"""
import os
import subprocess

_HERE = os.path.dirname(os.path.realpath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
_AGENT_PY = os.path.join(_REPO_ROOT, 'scripts', 'agent-bridge', 'agent.py')
_DONE_SH = os.path.join(_REPO_ROOT, 'scripts', 'done.sh')
_SEND_SH = os.path.join(_REPO_ROOT, 'scripts', 'send.sh')
_PUBLISH_LUA = os.path.join(
    _REPO_ROOT, 'scripts', 'agent-bridge', 'publish_event.lua')
_BUS_PROTOCOL = os.path.join(
    _REPO_ROOT, 'scripts', 'agent-bridge', 'bus_protocol.py')


class TestNoTextScraping:
    def test_done_pattern_removed_from_bridge(self):
        """Aucun scraping regex DONE/SCORE dans agent.py (A7)."""
        source = open(_AGENT_PY, encoding='utf-8').read()
        assert 'done_pattern' not in source
        assert 'send\\.sh' not in source, \
            "agent.py ne doit plus chercher d'appels send.sh dans les réponses"

    def test_no_relay_log_events(self):
        source = open(_AGENT_PY, encoding='utf-8').read()
        assert 'done_relay' not in source


class TestOriginField:
    def test_done_sh_emits_origin_agent(self):
        """V3 : le signal done.sh porte origin=agent (consultatif sur une
        tâche à verify_cmd — seul origin=verify fait foi)."""
        wrapper = open(_DONE_SH, encoding='utf-8').read()
        publisher = open(_PUBLISH_LUA, encoding='utf-8').read()
        protocol = open(_BUS_PROTOCOL, encoding='utf-8').read()
        assert 'bus_protocol.py' in wrapper
        assert '"origin", ARGV[22]' in publisher
        assert '"operator" if not inter_agent else "agent"' in protocol


class TestDoneShValidation:
    def _run(self, *args, env_extra=None):
        env = dict(os.environ)
        env.pop('TMUX', None)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            ['bash', _DONE_SH, *args],
            capture_output=True, text=True, env=env, timeout=30)

    def test_script_exists_and_executable(self):
        assert os.path.isfile(_DONE_SH)
        assert os.access(_DONE_SH, os.X_OK)

    def test_missing_args_fails(self):
        result = self._run()
        assert result.returncode != 0

    def test_invalid_target_id_fails(self):
        result = self._run('abc', 'DONE')
        assert result.returncode != 0
        assert 'Invalid agent ID' in result.stderr

    def test_invalid_signal_fails(self):
        result = self._run('100', 'FINISHED')
        assert result.returncode != 0
        assert 'Unknown terminal' in result.stderr

    def test_score_requires_numeric_value(self):
        result = self._run('100', 'SCORE', 'high')
        assert result.returncode != 0
        assert 'numeric' in result.stderr

    def test_self_signal_rejected(self):
        result = self._run('100', 'DONE', env_extra={'FROM_AGENT': '100'})
        assert result.returncode != 0
        assert 'itself' in result.stderr


class TestDoneShIntegration:
    @staticmethod
    def _matching(r, stream, **expected):
        return [
            (msg_id, data)
            for msg_id, data in r.xrange(stream)
            if all(data.get(key) == value for key, value in expected.items())
        ]

    @staticmethod
    def _env(r, **extra):
        connection = r.connection_pool.connection_kwargs
        env = dict(os.environ)
        env.pop('TMUX', None)
        env.pop('TMUX_PANE', None)
        env.update({
            'REDIS_HOST': str(connection['host']),
            'REDIS_PORT': str(connection['port']),
            'REDIS_DB': str(connection.get('db', 0)),
            # Vide explicite : redis.sh ne doit pas recharger le secret local.
            'REDIS_PASSWORD': '',
        })
        env.update({key: str(value) for key, value in extra.items()})
        return env

    def test_incomplete_metadata_can_emit_protocol_rescue(self, redis_client):
        r = redis_client
        r.flushdb()
        completion = 'completion'
        inbox = 'agent:998:inbox'
        env = self._env(
            r, FROM_AGENT='300', TASK_ID='unknown', CYCLE='unknown')
        env.pop('CORRELATION_ID', None)
        result = subprocess.run(
            ['bash', _DONE_SH, '998', 'INFO_REQUIRED',
             'enveloppe incomplète'],
            capture_output=True, text=True, env=env, timeout=30)

        assert result.returncode == 2
        assert 'rescue: incomplete metadata' in result.stderr
        assert 'state=ORPHANED' in result.stderr
        entries = self._matching(
            r, completion, **{
                'from': '300',
                'to': '998',
                'event': 'INFO_REQUIRED',
                'task_id': 'unattributed',
                'cycle': 'unattributed',
            })
        assert len(entries) == 1
        _completion_id, data = entries[0]
        assert data['task_id'] == 'unattributed'
        assert data['cycle'] == 'unattributed'
        assert data['correlation_id'].startswith('rescue-')
        inbox_entries = self._matching(
            r, inbox, correlation_id=data['correlation_id'])
        assert len(inbox_entries) == 1

    def test_incomplete_metadata_can_send_nonterminal_rescue(
            self, redis_client):
        r = redis_client
        r.flushdb()
        inbox = 'agent:998:inbox'
        env = self._env(
            r, FROM_AGENT='300', TASK_ID='unknown', CYCLE='unknown',
            MESSAGE_EVENT='INFO_REQUIRED')
        env.pop('CORRELATION_ID', None)
        result = subprocess.run(
            ['bash', _SEND_SH, '998', 'enveloppe incomplète'],
            capture_output=True, text=True, env=env, timeout=30)

        assert result.returncode == 2
        assert 'rescue: incomplete metadata' in result.stderr
        assert 'state=ORPHANED' in result.stderr
        entries = self._matching(
            r, inbox,
            from_agent='300',
            event='INFO_REQUIRED',
            task_id='unattributed',
            cycle='unattributed')
        assert len(entries) == 1
        _msg_id, data = entries[0]
        assert data['task_id'] == 'unattributed'
        assert data['cycle'] == 'unattributed'
        assert data['correlation_id'].startswith('rescue-')

    def test_signal_written_to_completion_stream_and_inbox(
            self, redis_client):
        r = redis_client
        r.flushdb()
        completion = 'completion'
        inbox = 'agent:100:inbox'
        corr = 'corr-a7-private'
        env = self._env(
            r, FROM_AGENT='300', CORRELATION_ID=corr,
            TASK_ID='task-a7', CYCLE='3', TURN_ID='turn-a7')
        result = subprocess.run(
            ['bash', _DONE_SH, '100', 'SCORE', '85', 'qualité OK'],
            capture_output=True, text=True, env=env, timeout=30)

        entries = self._matching(r, completion, correlation_id=corr)
        assert len(entries) == 1
        _completion_id, data = entries[0]
        assert data['from'] == '300'
        assert data['to'] == '100'
        assert data['signal'] == 'SCORE 85 qualité OK'
        assert data['origin'] == 'agent'  # V3 : signal consultatif
        assert data['correlation_id'] == corr
        assert data['task_id'] == 'task-a7'
        assert data['cycle'] == '3'
        assert data['source_turn_id'] == 'turn-a7'

        inbox_entries = self._matching(r, inbox, correlation_id=corr)
        assert len(inbox_entries) == 1
        _inbox_id, msg = inbox_entries[0]
        assert msg['prompt'] == (
            f'EVENT:SCORE|TASK:task-a7|CYCLE:3|CORR:{corr}|'
            'DETAIL:SCORE 85 qualité OK')
        assert msg['from_agent'] == '300'
        assert msg['event'] == 'SCORE'
        assert msg['correlation_id'] == corr
        assert msg['task_id'] == 'task-a7'
        assert msg['cycle'] == '3'
        assert msg['source_turn_id'] == 'turn-a7'

        # exit code: 0 si la cible tourne, sinon ORPHANED (2) ; dans les
        # deux cas la transaction privée est déjà atomiquement persistée.
        if result.returncode != 0:
            assert result.returncode == 2
            assert 'state=ORPHANED' in result.stderr

        duplicate = subprocess.run(
            ['bash', _DONE_SH, '100', 'SCORE', '85', 'qualité OK'],
            capture_output=True, text=True, env=env, timeout=30)
        assert duplicate.returncode == 0
        assert 'state=ALREADY_DELIVERED' in duplicate.stdout
        assert len(self._matching(r, completion, correlation_id=corr)) == 1
        assert len(self._matching(r, inbox, correlation_id=corr)) == 1

        conflicting = subprocess.run(
            ['bash', _DONE_SH, '100', 'SCORE', '86', 'contenu différent'],
            capture_output=True, text=True, env=env, timeout=30)
        assert conflicting.returncode == 3
        assert 'state=NOT_DELIVERED' in conflicting.stderr
        # A9 : le slot terminal est indépendant du tour — un nouveau TURN ne
        # suffit plus, la réémission exige un nouveau CYCLE/CORR.
        assert 'open a new CYCLE/CORR' in conflicting.stderr
        assert len(self._matching(r, completion, correlation_id=corr)) == 1
        assert len(self._matching(r, inbox, correlation_id=corr)) == 1
