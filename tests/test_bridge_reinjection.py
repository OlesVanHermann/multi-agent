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
    agent.inbox = "A:agent:300:inbox"
    agent.outbox = "A:agent:300:outbox"
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
            f"A:agent:{agent.agent_id}", "status", "stalled")
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
