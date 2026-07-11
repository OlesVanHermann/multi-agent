"""G1 — Tests E2E du bridge agent.py avec un faux CLI Claude.

Chaîne complète testée : Redis (serveur privé) → agent.py (subprocess) →
tmux (pane exécutant tests/fixtures/fake_claude.sh) → outbox Redis.

Scénarios couverts (markers.yaml) :
- nominal : inbox → réponse corrélée dans l'outbox + XACK
- compaction : "Conversation compacted" → ré-injection identité + rappel
- api_error : "API Error: 401" → retry avec backoff (events.jsonl) puis succès
- survey : "How is Claude doing" → auto-rejet ("0") puis réponse
- plan : "Would you like to proceed" → statut waiting_approval, approbation, réponse

Tests isolés : redis-server privé sur port libre, MA_PREFIX et session tmux
uniques par test, LOG_DIR dans tmp_path, nettoyage systématique. Skippés si
tmux ou redis-server manquent (CI : .github/workflows/e2e.yml les installe).
"""

import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

redis = pytest.importorskip("redis")

BASE = Path(__file__).resolve().parent.parent
AGENT_PY = BASE / "scripts" / "agent-bridge" / "agent.py"
FAKE_CLAUDE = BASE / "tests" / "fixtures" / "fake_claude.sh"

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux absent"),
    pytest.mark.skipif(shutil.which("redis-server") is None,
                       reason="redis-server absent"),
]


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for(cond, timeout, message):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return
        time.sleep(0.1)
    pytest.fail(message)


@pytest.fixture(scope="module")
def redis_server():
    """redis-server privé, éphémère, sans persistance."""
    port = _free_port()
    proc = subprocess.Popen(
        ["redis-server", "--port", str(port), "--bind", "127.0.0.1",
         "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = redis.Redis(host="127.0.0.1", port=port, decode_responses=True)
    deadline = time.time() + 10
    while True:
        try:
            client.ping()
            break
        except redis.ConnectionError:
            if time.time() > deadline:
                proc.terminate()
                pytest.skip("redis-server n'a pas démarré")
            time.sleep(0.1)
    yield port, client
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def bridge(redis_server, tmp_path):
    """Fabrique : session tmux (faux Claude) + bridge agent.py pour un scénario."""
    port, client = redis_server
    started = []

    def _start(scenario, agent_id):
        prefix = f"G1{agent_id}"
        session = f"{prefix}-agent-{agent_id}"
        fake_log = tmp_path / f"fake_{agent_id}.log"
        fake_log.touch()
        log_dir = tmp_path / f"logs_{agent_id}"

        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session, "-x", "200", "-y", "50",
             "-e", f"FAKE_CLAUDE_SCENARIO={scenario}",
             "-e", f"FAKE_CLAUDE_LOG={fake_log}",
             "-e", "FAKE_CLAUDE_DELAY=1",
             f"bash {FAKE_CLAUDE}"],
            check=True)

        env = dict(
            os.environ,
            REDIS_HOST="127.0.0.1", REDIS_PORT=str(port), REDIS_PASSWORD="",
            MA_PREFIX=prefix, LOG_DIR=str(log_dir),
            RESPONSE_TIMEOUT="60", POLL_MIN="0.1", POLL_MAX="0.5",
            STABLE_READY_SECS="1", STABLE_FALLBACK_SECS="3",
            RETRY_BACKOFF_SECS="1", AGENT_HEALTH_PORT_BASE="19100")
        # stdin=PIPE jamais fermé : EOF sur stdin arrête le bridge (run()).
        out = open(tmp_path / f"bridge_{agent_id}.out", "w")
        proc = subprocess.Popen(
            [sys.executable, str(AGENT_PY), agent_id],
            stdin=subprocess.PIPE, stdout=out, stderr=subprocess.STDOUT,
            env=env, cwd=str(AGENT_PY.parent))
        started.append((session, proc, out))

        h = SimpleNamespace(
            prefix=prefix, session=session, agent_id=agent_id, client=client,
            inbox=f"{prefix}:agent:{agent_id}:inbox",
            outbox=f"{prefix}:agent:{agent_id}:outbox",
            fake_log=fake_log, log_dir=log_dir, proc=proc)

        # A4 : le groupe est créé avec id='$' — envoyer avant sa création
        # perdrait le message. Attendre qu'il existe.
        def group_ready():
            try:
                return any(g["name"] == "bridge"
                           for g in client.xinfo_groups(h.inbox))
            except redis.ResponseError:
                return False
        _wait_for(group_ready, 15,
                  f"consumer group 'bridge' jamais créée sur {h.inbox}")
        return h

    yield _start

    for session, proc, out in started:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        out.close()
        subprocess.run(["tmux", "kill-session", "-t", session],
                       capture_output=True)


def _send(h, prompt):
    corr = str(uuid.uuid4())
    h.client.xadd(h.inbox, {
        "prompt": prompt, "from_agent": "cli",
        "correlation_id": corr, "timestamp": int(time.time())})
    return corr


def _pane(h):
    return subprocess.run(
        ["tmux", "capture-pane", "-t", f"{h.session}:0", "-p", "-S", "-200"],
        capture_output=True, text=True).stdout


def _wait_response(h, corr, timeout=45):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for _id, data in h.client.xrange(h.outbox):
            if data.get("correlation_id") == corr and "response" in data:
                return data["response"]
        time.sleep(0.2)
    pytest.fail(
        f"pas de réponse corrélée {corr} sur {h.outbox} après {timeout}s\n"
        f"--- pane tmux ---\n{_pane(h)}")


def _wait_status(h, value, timeout=30):
    key = f"{h.prefix}:agent:{h.agent_id}"
    _wait_for(lambda: h.client.hget(key, "status") == value, timeout,
              f"statut '{value}' jamais observé sur {key} "
              f"(actuel: {h.client.hget(key, 'status')})\n"
              f"--- pane tmux ---\n{_pane(h)}")


def test_nominal_inbox_to_outbox(bridge):
    """Chemin nominal : prompt inbox → faux Claude → réponse corrélée + XACK."""
    h = bridge("nominal", "391")
    corr = _send(h, "Dis bonjour")
    response = _wait_response(h, corr)

    assert "RESPONSE_OK" in response
    assert "Dis bonjour" in h.fake_log.read_text()
    # A4 : le message est XACK après publication de la réponse
    _wait_for(lambda: h.client.xpending(h.inbox, "bridge")["pending"] == 0,
              10, "message inbox jamais acquitté (XACK)")


def test_compaction_reinjects_identity(bridge):
    """Compaction : sentinel détecté → 'deviens agent' + rappel de contexte,
    puis la réponse finale porte le correlation_id d'origine."""
    h = bridge("compaction", "392")
    corr = _send(h, "Travaille sur la tache X")
    response = _wait_response(h, corr, timeout=90)

    assert "RESPONSE_OK" in response
    log = h.fake_log.read_text()
    assert "deviens agent" in log, "identité non ré-injectée après compaction"
    assert "Tu étais en train de travailler" in log, "rappel de contexte absent"


def test_api_error_retry_then_success(bridge):
    """Erreur API : retry avec backoff (events.jsonl), puis réponse correcte."""
    h = bridge("api_error", "393")
    corr = _send(h, "Declenche une panne")
    response = _wait_response(h, corr, timeout=90)

    assert "RETRY_OK" in response
    assert "API Error" not in response
    events = (h.log_dir / "393" / "events.jsonl").read_text()
    assert "api_error_retry" in events, "événement api_error_retry non journalisé"


def test_survey_auto_dismissed(bridge):
    """Sondage de session : auto-rejeté par '0', la réponse arrive ensuite."""
    h = bridge("survey", "394")
    corr = _send(h, "Donne le statut")
    response = _wait_response(h, corr, timeout=90)

    assert "SURVEY_DISMISSED_OK" in response
    assert "0" in h.fake_log.read_text().splitlines(), \
        "le bridge n'a pas envoyé '0' pour rejeter le sondage"


def test_plan_mode_waits_for_approval(bridge):
    """Plan mode : statut waiting_approval tant que l'utilisateur n'a pas
    approuvé, puis la réponse part après approbation."""
    h = bridge("plan", "395")
    corr = _send(h, "Propose un plan")

    _wait_status(h, "waiting_approval", timeout=30)

    # L'utilisateur approuve (frappe directe dans le pane, hors bridge)
    subprocess.run(["tmux", "send-keys", "-t", f"{h.session}:0", "1", "Enter"],
                   check=True)
    response = _wait_response(h, corr, timeout=60)
    assert "PLAN_APPROVED_OK" in response
