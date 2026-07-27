"""
A7 — Signaux DONE/SCORE via canal Redis dédié (scripts/done.sh)

Le bridge ne doit plus scanner le texte des réponses du modèle pour
relayer des signaux de complétion (anti faux DONE par hallucination).
"""
import os
import subprocess
import uuid

import pytest

_HERE = os.path.dirname(os.path.realpath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
_AGENT_PY = os.path.join(_REPO_ROOT, 'scripts', 'agent-bridge', 'agent.py')
_DONE_SH = os.path.join(_REPO_ROOT, 'scripts', 'done.sh')
_SEND_SH = os.path.join(_REPO_ROOT, 'scripts', 'send.sh')


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
        source = open(_DONE_SH, encoding='utf-8').read()
        assert 'origin "agent"' in source


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


def _redis_available():
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379,
                        password=os.environ.get('REDIS_PASSWORD') or None,
                        socket_connect_timeout=2)
        return r.ping()
    except Exception:
        return False


@pytest.mark.skipif(not _redis_available(), reason="Redis indisponible")
class TestDoneShIntegration:
    @staticmethod
    def _matching(r, stream, **expected):
        return [
            (msg_id, data)
            for msg_id, data in r.xrange(stream)
            if all(data.get(key) == value for key, value in expected.items())
        ]

    def test_incomplete_metadata_can_emit_protocol_rescue(self):
        import redis
        r = redis.Redis(host='localhost', port=6379,
                        password=os.environ.get('REDIS_PASSWORD') or None,
                        decode_responses=True)
        completion = 'completion'
        inbox = 'agent:998:inbox'
        dedup = None
        created = []
        try:
            env = dict(os.environ)
            env['FROM_AGENT'] = '300'
            env['TASK_ID'] = 'unknown'
            env['CYCLE'] = 'unknown'
            env.pop('CORRELATION_ID', None)
            env.pop('TMUX', None)
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
            completion_id, data = entries[0]
            created.append((completion, completion_id))
            assert data['task_id'] == 'unattributed'
            assert data['cycle'] == 'unattributed'
            assert data['correlation_id'].startswith('rescue-')
            inbox_entries = self._matching(
                r, inbox, correlation_id=data['correlation_id'])
            assert len(inbox_entries) == 1
            created.append((inbox, inbox_entries[0][0]))
            dedup = (
                'terminal:300:INFO_REQUIRED:unattributed:unattributed:'
                + data['correlation_id'])
        finally:
            for stream, msg_id in created:
                r.xdel(stream, msg_id)
            if dedup:
                r.delete(dedup)

    def test_incomplete_metadata_can_send_nonterminal_rescue(self):
        import redis
        r = redis.Redis(host='localhost', port=6379,
                        password=os.environ.get('REDIS_PASSWORD') or None,
                        decode_responses=True)
        inbox = 'agent:998:inbox'
        created = []
        try:
            env = dict(os.environ)
            env['FROM_AGENT'] = '300'
            env['TASK_ID'] = 'unknown'
            env['CYCLE'] = 'unknown'
            env['MESSAGE_EVENT'] = 'INFO_REQUIRED'
            env.pop('CORRELATION_ID', None)
            env.pop('TMUX', None)
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
            msg_id, data = entries[0]
            created.append((inbox, msg_id))
            assert data['task_id'] == 'unattributed'
            assert data['cycle'] == 'unattributed'
            assert data['correlation_id'].startswith('rescue-')
        finally:
            for stream, msg_id in created:
                r.xdel(stream, msg_id)

    def test_signal_written_to_completion_stream_and_inbox(self):
        import redis
        r = redis.Redis(host='localhost', port=6379,
                        password=os.environ.get('REDIS_PASSWORD') or None,
                        decode_responses=True)
        completion = 'completion'
        inbox = 'agent:100:inbox'
        corr = f'corr-a7-{uuid.uuid4()}'
        dedup = f'terminal:300:SCORE:task-a7:3:{corr}'
        created = []
        try:
            env = dict(os.environ)
            env['FROM_AGENT'] = '300'
            env['CORRELATION_ID'] = corr
            env['TASK_ID'] = 'task-a7'
            env['CYCLE'] = '3'
            env.pop('TMUX', None)
            result = subprocess.run(
                ['bash', _DONE_SH, '100', 'SCORE', '85', 'qualité OK'],
                capture_output=True, text=True, env=env, timeout=30)

            entries = self._matching(r, completion, correlation_id=corr)
            assert len(entries) == 1
            completion_id, data = entries[0]
            created.append((completion, completion_id))
            assert data['from'] == '300'
            assert data['to'] == '100'
            assert data['signal'] == 'SCORE 85 qualité OK'
            assert data['origin'] == 'agent'  # V3 : signal consultatif
            assert data['correlation_id'] == corr
            assert data['task_id'] == 'task-a7'
            assert data['cycle'] == '3'

            inbox_entries = self._matching(r, inbox, correlation_id=corr)
            assert len(inbox_entries) == 1
            inbox_id, msg = inbox_entries[0]
            created.append((inbox, inbox_id))
            assert msg['prompt'] == (
                f'EVENT:SCORE|TASK:task-a7|CYCLE:3|CORR:{corr}|'
                'DETAIL:SCORE 85 qualité OK')
            assert msg['from_agent'] == '300'
            assert msg['event'] == 'SCORE'
            assert msg['correlation_id'] == corr
            assert msg['task_id'] == 'task-a7'
            assert msg['cycle'] == '3'

            # exit code: 0 si la cible tourne, sinon ko (orphan queue) —
            # ici pas de tmux cible, le message doit quand même être délivré
            if result.returncode != 0:
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
            assert 'open a new CYCLE/CORR' in conflicting.stderr
            assert len(self._matching(r, completion, correlation_id=corr)) == 1
            assert len(self._matching(r, inbox, correlation_id=corr)) == 1
        finally:
            for stream, msg_id in created:
                r.xdel(stream, msg_id)
            r.delete(dedup)
