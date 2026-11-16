"""
A5 — Fix re-injection bridge (constate en prod 11/07/2026 sur 371-371).

Symptomes couverts :
  1. Le drain des pending (XREADGROUP '0') re-queuait LE MEME message a
     chaque tour tant qu'il n'etait pas XACK (19393 "Recovering" logges,
     130 injections du meme dispatch) -> curseur avancant : une entree
     pending est livree UNE fois par demarrage.
  2. Toute re-livraison d'un msg_id deja en vol (queue ou execution) est
     ignoree jusqu'a son XACK (une injection = un ack).
  3. Un message XDEL de l'inbox pendant qu'il attendait en queue memoire
     n'est PAS injecte (l'etat de verite est Redis, pas la copie memoire).
  4. QUEUED MESSAGE (Claude occupe, prompt mis en file par la TUI) :
     le bridge attend l'idle au lieu de retourner le pane comme reponse.
"""
import os
import sys
import time
import threading
from queue import Queue
from unittest.mock import MagicMock

_HERE = os.path.dirname(os.path.realpath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
sys.path.insert(0, os.path.join(_REPO_ROOT, 'scripts', 'agent-bridge'))


def _make_agent():
    from agent import TmuxAgent
    agent = object.__new__(TmuxAgent)
    agent.agent_id = "300"
    agent.inbox = "agent:300:inbox"
    agent.outbox = "agent:300:outbox"
    agent.group = "bridge"
    agent.consumer = "agent-300"
    agent.running = True
    agent.prompt_queue = Queue()
    agent.metrics = None
    agent.redis = MagicMock()
    agent._log = MagicMock()
    agent._log_event = MagicMock()
    agent._wal = MagicMock()
    agent._inflight_ids = set()
    agent._inflight_lock = threading.Lock()
    return agent


class TestInflightDedup:
    def test_duplicate_delivery_not_requeued(self):
        """Le meme msg_id livre 2x (drain pending + flux) -> 1 seule entree."""
        agent = _make_agent()
        agent._handle_inbox_message("1-0", {"prompt": "go", "from_agent": "100"})
        agent._handle_inbox_message("1-0", {"prompt": "go", "from_agent": "100"})
        assert agent.prompt_queue.qsize() == 1

    def test_ack_releases_inflight(self):
        """Apres XACK, une nouvelle livraison du meme id redevient queuable."""
        agent = _make_agent()
        agent._handle_inbox_message("2-0", {"prompt": "go", "from_agent": "100"})
        agent._ack_inbox("2-0")
        agent._handle_inbox_message("2-0", {"prompt": "go", "from_agent": "100"})
        assert agent.prompt_queue.qsize() == 2

    def test_distinct_ids_all_queued(self):
        agent = _make_agent()
        agent._handle_inbox_message("3-0", {"prompt": "a", "from_agent": "100"})
        agent._handle_inbox_message("3-1", {"prompt": "b", "from_agent": "100"})
        assert agent.prompt_queue.qsize() == 2


class TestPendingDrainCursor:
    def test_unacked_pending_delivered_once(self):
        """L'entree pending JAMAIS ackee n'est livree qu'UNE fois par
        demarrage (l'ancien code repartait de '0' et bouclait dessus)."""
        agent = _make_agent()
        pending = ("10-0", {"prompt": "dispatch", "from_agent": "171"})

        def fake_xreadgroup(group, consumer, streams, count=None, block=None):
            cursor = list(streams.values())[0]
            if cursor == '0':
                return [(agent.inbox, [pending])]
            # Curseur avance (>= 10-0) ou flux '>' : plus rien.
            return []

        agent.redis.xreadgroup.side_effect = fake_xreadgroup
        agent._ensure_group = MagicMock()
        agent._handle_inbox_message = MagicMock()

        t = threading.Thread(target=agent._listen_redis, daemon=True)
        t.start()
        time.sleep(0.5)
        agent.running = False
        t.join(timeout=3)

        assert agent._handle_inbox_message.call_count == 1
        assert agent._handle_inbox_message.call_args[0][0] == "10-0"


class TestXdelRespected:
    def test_deleted_message_not_injected(self):
        """Un message XDEL de l'inbox alors qu'il attendait en queue
        memoire est droppe (ack + pas d'injection tmux)."""
        agent = _make_agent()
        agent.redis.xrange.return_value = []  # XDEL : l'entree n'existe plus
        agent._run_claude = MagicMock()
        agent.prompt_queue.put({
            'prompt': 'dispatch', 'from_agent': '171',
            'msg_id': '20-0', 'ack_id': '20-0', 'source': 'redis',
        })

        t = threading.Thread(target=agent._process_queue, daemon=True)
        t.start()
        time.sleep(0.5)
        agent.running = False
        t.join(timeout=3)

        agent._run_claude.assert_not_called()
        agent.redis.xack.assert_called_once_with(agent.inbox, "bridge", "20-0")


class TestQueuedMessageWaitsIdle:
    def test_stall_does_not_complete_or_ack_while_queued(self):
        """Pane affichant le marqueur 'queued' : _wait_for_response ne doit
        PAS retourner immediatement (l'ancien code renvoyait le pane comme
        reponse en <1 poll, d'ou publication+ack d'une fausse reponse)."""
        import agent as agent_mod
        agent = _make_agent()
        pane = f"some output\n{agent_mod.QUEUED_MSG}\nmore"
        agent._capture_pane = MagicMock(return_value=pane)

        result = []
        t = threading.Thread(
            target=lambda: result.append(agent._wait_for_response(timeout=0.3)),
            daemon=True)
        t.start()
        time.sleep(1.6)

        # Le seuil produit un diagnostic STALLED mais ne termine pas la tache.
        assert t.is_alive()
        assert result == []
        agent.redis.hset.assert_any_call(
            f"agent:{agent.agent_id}", "status", "stalled")
        # Log unique, pas de spam.
        waits = [c for c in agent._log.call_args_list
                 if "waiting for idle" in str(c)]
        assert len(waits) == 1
        stalls = [c for c in agent._log.call_args_list
                  if "STALL DETECTED" in str(c)]
        assert len(stalls) == 1

        agent.running = False
        t.join(timeout=2)
        assert result == ["__BRIDGE_STOPPED__"]


def _drain(agent):
    items = []
    while not agent.prompt_queue.empty():
        items.append(agent.prompt_queue.get_nowait())
    return items


class TestCompactionKeepsInboxAck:
    """322-222 (2026-11-15) : deux compactions Codex dans un même tour. La
    seconde, pendant le message 1 de reprise, vidait le message 2 — seul
    porteur de l'ack_id — et le rebâtissait sans : l'id restait en vol et le
    listener ne livrait plus rien pendant 9 h."""

    ORIGIN = {'prompt': 'ARBITRAGES L020', 'from_agent': 'cli', 'msg_id': 'A',
              'ack_id': 'A', 'source': 'redis', 'correlation_id': 'corr-1',
              'task_id': 't-1', 'verify_cmd': 'true'}

    def _agent(self):
        agent = _make_agent()
        agent._find_prompt_file = lambda: "/p/322-lighton/322-222.md"
        return agent

    def test_single_compaction_acks_through_message_2(self):
        agent = self._agent()
        agent._requeue_after_compaction(dict(self.ORIGIN))
        r1, r2 = _drain(agent)
        assert 'ack_id' not in r1 and r1['_origin']['ack_id'] == 'A'
        assert r2['ack_id'] == 'A' and r2['correlation_id'] == 'corr-1'
        assert r2['verify_cmd'] == 'true' and 'ARBITRAGES L020' in r2['prompt']

    def test_second_compaction_during_message_1_keeps_the_ack(self):
        agent = self._agent()
        agent._requeue_after_compaction(dict(self.ORIGIN))
        r1 = agent.prompt_queue.get_nowait()       # le worker exécute R1…
        agent._requeue_after_compaction(r1)        # …seconde compaction
        r1b, r2b = _drain(agent)                   # l'ancien R2 a été vidé
        assert r2b['ack_id'] == 'A'
        assert r2b['correlation_id'] == 'corr-1' and r2b['task_id'] == 't-1'
        assert 'ARBITRAGES L020' in r2b['prompt']  # pas « deviens agent »
        assert r1b['_origin']['ack_id'] == 'A'

    def test_ack_recovered_from_a_drained_message_2_alone(self):
        """Message 1 d'un bridge antérieur (sans _origin) : l'ack est repris
        sur le message 2 vidé."""
        agent = self._agent()
        agent.prompt_queue.put({'prompt': 'Continue.', 'msg_id': 'resume2_1',
                                'from_agent': 'compaction_resume',
                                'ack_id': 'A', 'correlation_id': 'corr-1'})
        legacy_r1 = {'prompt': 'deviens agent x', 'msg_id': 'resume1_1',
                     'from_agent': 'compaction_resume',
                     '_original_prompt': 'ARBITRAGES L020'}
        agent._requeue_after_compaction(legacy_r1)
        _, r2b = _drain(agent)
        assert r2b['ack_id'] == 'A' and r2b['correlation_id'] == 'corr-1'

    def test_third_compaction_still_keeps_the_ack(self):
        agent = self._agent()
        task = dict(self.ORIGIN)
        for _ in range(3):
            agent._requeue_after_compaction(task)
            task = agent.prompt_queue.get_nowait()   # chaque fois pendant R1
        r2 = _drain(agent)[-1]
        assert r2['ack_id'] == 'A'


class TestOrphanInflightIsReleased:
    def _agent(self, monkeypatch, grace=300):
        import agent as agent_mod
        monkeypatch.setattr(agent_mod, "INFLIGHT_ORPHAN_GRACE_S", grace)
        agent = _make_agent()
        agent.state_lock = threading.Lock()
        agent.current_task = None
        agent._inflight_ids.add('A')
        return agent

    def test_orphan_released_after_grace_without_xack(self, monkeypatch):
        agent = self._agent(monkeypatch)
        assert agent._release_orphan_inflight(now=1000.0) == []
        assert agent._release_orphan_inflight(now=1299.0) == []
        assert agent._release_orphan_inflight(now=1300.0) == ['A']
        assert agent._inflight_ids == set()
        agent.redis.xack.assert_not_called()         # rejoué au redémarrage
        assert agent.redis.xadd.call_args.args[0] == "monitoring:alerts"

    def test_id_carried_by_a_task_is_never_released(self, monkeypatch):
        agent = self._agent(monkeypatch, grace=0)
        agent.prompt_queue.put({'msg_id': 'resume1_1', 'prompt': 'x',
                                '_origin': {'ack_id': 'A'}})
        assert agent._release_orphan_inflight(now=10**9) == []
        agent.prompt_queue.get_nowait()
        agent.current_task = {'ack_id': 'A', 'prompt': 'x'}
        assert agent._release_orphan_inflight(now=10**9) == []
        assert agent._inflight_ids == {'A'}

    def test_listener_resumes_delivery_after_release(self, monkeypatch):
        agent = self._agent(monkeypatch, grace=0)
        agent._ensure_group = MagicMock()
        seen = []
        agent._handle_inbox_message = lambda msg_id, data: seen.append(msg_id)
        nxt = ("B", {"prompt": "suite", "from_agent": "cli"})

        def fake_xreadgroup(group, consumer, streams, count=None, block=None):
            return [] if list(streams.values())[0] == '0' else [(agent.inbox, [nxt])]
        agent.redis.xreadgroup.side_effect = fake_xreadgroup
        t = threading.Thread(target=agent._listen_redis, daemon=True)
        t.start()
        time.sleep(0.6)
        agent.running = False
        t.join(timeout=3)
        assert "B" in seen
