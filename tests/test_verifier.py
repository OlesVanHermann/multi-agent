"""
V3/C1 — verifier.py : la complétion se prouve, ne se déclare pas.

Règles anti-hacking déterministes, exécution du harnais (vert/rouge/timeout),
checkpoint git, audit stream. Le stub Redis capture les XADD.

Gate verify dans agent.py (_process_queue réel dans un thread) :
invariant de rétrocompat (sans verify_cmd = flux v2 à l'identique),
vert, rouge→retry→vert (ack A4 conservé), budget épuisé, hacking.
"""
import json
import os
import subprocess
import sys
import time
from collections import deque
from queue import Queue
from threading import Lock, Thread

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts', 'agent-bridge'))

import verifier  # noqa: E402
import agent as agent_mod  # noqa: E402


class _StubRedis:
    def __init__(self):
        self.entries = []
        self.acks = []

    def xadd(self, stream, fields, **kw):
        self.entries.append((stream, fields))
        return f"0-{len(self.entries)}"

    def xack(self, stream, group, msg_id):
        self.acks.append((stream, group, msg_id))
        return 1

    def hset(self, *args, **kw):
        return 1


@pytest.fixture
def repo(tmp_path):
    """Repo git minimal avec un commit initial (HEAD existant)."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_ok.py").write_text(
        "def test_a():\n"
        "    assert 1\n"
        "    assert 2\n"
        "    assert 3\n"
        "    assert 4\n"
        "    assert 5\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"], check=True)
    return tmp_path


class TestHackingRules:
    def test_clean_diff_not_hacked(self, repo):
        (repo / "feature.py").write_text("def add(a, b):\n    return a + b\n")
        hacked, reasons = verifier.hacking_rules(str(repo))
        assert hacked is False
        assert reasons == []

    def test_write_to_forbidden_path(self, repo):
        target = repo / "pool-requests" / "tests" / "t1"
        target.mkdir(parents=True)
        (target / "verify.sh").write_text("exit 0\n")
        hacked, reasons = verifier.hacking_rules(str(repo))
        assert hacked is True
        assert any("pool-requests/tests/t1/verify.sh" in r for r in reasons)

    def test_similar_prefix_not_flagged(self, repo):
        """pool-requests/tests-utils/ ne matche pas pool-requests/tests/."""
        target = repo / "pool-requests" / "tests-utils"
        target.mkdir(parents=True)
        (target / "helper.py").write_text("x = 1\n")
        hacked, _ = verifier.hacking_rules(str(repo))
        assert hacked is False

    def test_modified_oracle_flagged(self, repo):
        target = repo / "bench" / "oracle" / "t1"
        target.mkdir(parents=True)
        (target / "verify.sh").write_text("exit 0\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "oracle"], check=True)
        (target / "verify.sh").write_text("exit 1\n")
        hacked, reasons = verifier.hacking_rules(str(repo))
        assert hacked is True
        assert any("bench/oracle" in r for r in reasons)

    def test_removed_asserts_flagged(self, repo):
        (repo / "tests" / "test_ok.py").write_text("def test_a():\n    pass\n")
        hacked, reasons = verifier.hacking_rules(str(repo))
        assert hacked is True
        assert any("assertions supprimées" in r for r in reasons)

    def test_added_skip_marker_flagged(self, repo):
        path = repo / "tests" / "test_ok.py"
        path.write_text("import pytest\n\n@pytest.mark.skip\n" + path.read_text())
        hacked, reasons = verifier.hacking_rules(str(repo))
        assert hacked is True
        assert any("skip" in r for r in reasons)


class TestRunCmd:
    def test_green(self, repo):
        green, rapport = verifier.run_cmd("echo ok && exit 0", str(repo))
        assert green is True
        assert "ok" in rapport

    def test_red_captures_output(self, repo):
        green, rapport = verifier.run_cmd("echo BOOM >&2 && exit 3", str(repo))
        assert green is False
        assert "BOOM" in rapport

    def test_timeout(self, repo, monkeypatch):
        monkeypatch.setattr(verifier, "VERIFY_TIMEOUT", 1)
        green, rapport = verifier.run_cmd("sleep 5", str(repo))
        assert green is False
        assert "timeout" in rapport

    def test_rapport_truncated(self, repo):
        green, rapport = verifier.run_cmd("yes x | head -c 10000; exit 1", str(repo))
        assert green is False
        assert len(rapport) <= verifier.RAPPORT_MAX


class TestCheckpoint:
    def test_green_creates_checkpoint_commit(self, repo):
        (repo / "feature.py").write_text("x = 1\n")
        verifier.checkpoint("t42", str(repo))
        log = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%s"],
                             capture_output=True, text=True).stdout
        assert "[v3-checkpoint] task=t42 verify=green" in log


class TestRun:
    def test_green_path_audits_and_checkpoints(self, repo):
        (repo / "feature.py").write_text("x = 1\n")
        r = _StubRedis()
        green, hacked, _ = verifier.run(
            {"verify_cmd": "exit 0", "task_id": "t1"}, r, "300", str(repo))
        assert (green, hacked) == (True, False)
        stream, fields = r.entries[0]
        assert stream == "completion"
        assert fields["signal"] == "SCORE 100"
        assert fields["origin"] == "verify"
        assert fields["task_id"] == "t1"
        log = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%s"],
                             capture_output=True, text=True).stdout
        assert "task=t1" in log

    def test_red_path_returns_rapport(self, repo):
        r = _StubRedis()
        green, hacked, rapport = verifier.run(
            {"verify_cmd": "echo KO && exit 1", "task_id": "t2"}, r, "300", str(repo))
        assert (green, hacked) == (False, False)
        assert "KO" in rapport
        assert r.entries == []  # pas d'audit sur simple rouge

    def test_hacked_path_short_circuits(self, repo):
        target = repo / "bench" / "oracle" / "t3"
        target.mkdir(parents=True)
        (target / "verify.sh").write_text("exit 0\n")
        r = _StubRedis()
        green, hacked, rapport = verifier.run(
            {"verify_cmd": "exit 0", "task_id": "t3"}, r, "300", str(repo))
        assert (green, hacked) == (False, True)
        assert "anti-hacking" in rapport
        assert r.entries[0][1]["signal"] == "HACK_DETECTED"
        # le verify_cmd n'a PAS produit de checkpoint
        log = subprocess.run(["git", "-C", str(repo), "log", "--format=%s"],
                             capture_output=True, text=True).stdout
        assert "v3-checkpoint" not in log


# ============================================================
# Gate verify dans agent.py — _process_queue réel dans un thread
# ============================================================

def _make_bridge_agent(tmp_path, response="réponse simulée"):
    """TmuxAgent minimal sans __init__ (pattern des tests bridge existants).
    _run_claude/_capture_pane/_agent_alive stubbés ; le reste est réel."""
    a = object.__new__(agent_mod.TmuxAgent)
    a.agent_id = "300"
    a.inbox = "agent:300:inbox"
    a.outbox = "agent:300:outbox"
    a.group = "bridge"
    a.redis = _StubRedis()
    a.prompt_queue = Queue()
    a.state_lock = Lock()
    a.state = agent_mod.State.IDLE
    a.current_task = None
    a.running = True
    a.metrics = None
    a.history = deque(maxlen=50)
    a.tasks_completed = 0
    a.messages_since_reload = 0
    a._messages_processed = 0
    a._last_message_ts = 0
    a.log_dir = tmp_path
    a.logs = []
    a._log = a.logs.append
    a.seen_prompts = []

    def _fake_run(prompt):
        a.seen_prompts.append(prompt)
        return response

    a._run_claude = _fake_run
    a._capture_pane = lambda lines=100: ""
    a._agent_alive = lambda x: False
    return a


def _wait_for(cond, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


def _outbox(a):
    return [f for s, f in a.redis.entries if s == a.outbox]


def _run_gate(a, task, done, timeout=8.0):
    """Lance _process_queue, pousse la tâche, attend done(), arrête le thread."""
    t = Thread(target=a._process_queue, daemon=True)
    t.start()
    a.prompt_queue.put(task)
    ok = _wait_for(done, timeout)
    a.running = False
    t.join(timeout=3)
    assert ok, f"condition non atteinte; logs={a.logs}"


def _events(tmp_path):
    p = tmp_path / "events.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().strip().split("\n") if line]


class TestVerifyGate:
    def test_retrocompat_sans_verify_cmd(self, tmp_path, monkeypatch):
        """Invariant v2 : sans verify_cmd, verifier.run n'est JAMAIS appelé
        et la réponse est publiée telle quelle (annexe §6)."""
        calls = []
        monkeypatch.setattr(verifier, "run",
                            lambda *args, **kw: calls.append(args) or (True, False, ""))
        a = _make_bridge_agent(tmp_path)
        _run_gate(a, {'prompt': 'tâche v2', 'from_agent': 'cli',
                      'msg_id': 'm1', 'ack_id': 'ack-1'},
                  lambda: len(_outbox(a)) >= 1)
        assert calls == []
        out = _outbox(a)
        assert out[0]['response'] == "réponse simulée"
        assert "[VERIFY_GREEN]" not in out[0]['response']
        assert a.redis.acks == [(a.inbox, a.group, 'ack-1')]

    def test_green_ajoute_marqueur_et_ack(self, tmp_path, monkeypatch):
        monkeypatch.setattr(verifier, "run",
                            lambda *args, **kw: (True, False, ""))
        a = _make_bridge_agent(tmp_path)
        _run_gate(a, {'prompt': 'go', 'from_agent': 'cli', 'msg_id': 'm1',
                      'ack_id': 'ack-2', 'verify_cmd': 'exit 0', 'task_id': 't1'},
                  lambda: len(_outbox(a)) >= 1)
        out = _outbox(a)
        assert out[0]['response'].endswith("[VERIFY_GREEN]")
        assert a.redis.acks == [(a.inbox, a.group, 'ack-2')]
        assert any(e["type"] == "verify_green" for e in _events(tmp_path))

    def test_rouge_puis_vert_retry_conserve_ack(self, tmp_path, monkeypatch):
        """Rouge → requeue FROM:verify|FAIL (deadline/verify_cmd portés),
        rien publié ; vert au 2e tour → publication + ack original (A4)."""
        tasks_seen = []

        def fake_run(task, *args, **kw):
            tasks_seen.append(dict(task))
            if len(tasks_seen) == 1:
                return (False, False, "AssertionError: BOOM")
            return (True, False, "")

        monkeypatch.setattr(verifier, "run", fake_run)
        a = _make_bridge_agent(tmp_path)
        _run_gate(a, {'prompt': 'go', 'from_agent': 'cli', 'msg_id': 'm1',
                      'ack_id': 'ack-3', 'verify_cmd': 'pytest -q',
                      'task_id': 't2', 'deadline': '1799999999'},
                  lambda: len(_outbox(a)) >= 1)
        # un seul message publié : le vert final (rien sur simple rouge)
        out = _outbox(a)
        assert len(out) == 1
        assert out[0]['response'].endswith("[VERIFY_GREEN]")
        # la tentative 2 est le retry, avec tous les champs portés
        assert len(tasks_seen) == 2
        retry = tasks_seen[1]
        assert retry['from_agent'] == 'verify'
        assert retry['_verify_retry'] == 1
        assert retry['verify_cmd'] == 'pytest -q'
        assert retry['task_id'] == 't2'
        assert retry['deadline'] == '1799999999'
        assert retry['ack_id'] == 'ack-3'
        # le prompt de retry contient le rapport d'échec
        assert a.seen_prompts[1].startswith("FROM:verify|FAIL (tentative 1/")
        assert "BOOM" in a.seen_prompts[1]
        # l'ack n'a été fait qu'une fois, après publication (A4)
        assert a.redis.acks == [(a.inbox, a.group, 'ack-3')]

    def test_budget_epuise_publie_verify_failed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agent_mod, "VERIFY_MAX_RETRIES", 2)
        calls = []
        monkeypatch.setattr(verifier, "run",
                            lambda *args, **kw: calls.append(1) or (False, False, "toujours rouge"))
        a = _make_bridge_agent(tmp_path)
        _run_gate(a, {'prompt': 'go', 'from_agent': 'cli', 'msg_id': 'm1',
                      'ack_id': 'ack-4', 'verify_cmd': 'exit 1', 'task_id': 't3'},
                  lambda: len(_outbox(a)) >= 1)
        out = _outbox(a)
        assert out[0]['response'].startswith(
            "[VERIFY_FAILED] BLOCKED|task=t3|raison=budget_retries")
        # essai initial + 2 retries = 3 passages au verify
        assert len(calls) == 3
        # publié → ack (le workflow décide de la suite)
        assert a.redis.acks == [(a.inbox, a.group, 'ack-4')]
        assert any(e["type"] == "verify_escalation" for e in _events(tmp_path))

    def test_hacking_court_circuite_sans_retry(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(verifier, "run",
                            lambda *args, **kw: calls.append(1) or (False, True, "anti-hacking: oracle"))
        a = _make_bridge_agent(tmp_path)
        _run_gate(a, {'prompt': 'go', 'from_agent': 'cli', 'msg_id': 'm1',
                      'ack_id': 'ack-5', 'verify_cmd': 'exit 0', 'task_id': 't4'},
                  lambda: len(_outbox(a)) >= 1)
        out = _outbox(a)
        assert "raison=hacking" in out[0]['response']
        assert out[0]['response'].startswith("[VERIFY_FAILED] BLOCKED|task=t4")
        assert len(calls) == 1  # pas de retry sur hacking

    def test_correlation_id_echo_sur_verify_failed(self, tmp_path, monkeypatch):
        """F2 : le correlation_id est renvoyé même en échec verify —
        l'orchestrateur peut matcher la réponse."""
        monkeypatch.setattr(agent_mod, "VERIFY_MAX_RETRIES", 0)
        monkeypatch.setattr(verifier, "run",
                            lambda *args, **kw: (False, False, "rouge"))
        a = _make_bridge_agent(tmp_path)
        _run_gate(a, {'prompt': 'go', 'from_agent': 'cli', 'msg_id': 'm1',
                      'correlation_id': 'corr-9', 'verify_cmd': 'exit 1',
                      'task_id': 't5'},
                  lambda: len(_outbox(a)) >= 1)
        out = _outbox(a)
        assert out[0]['correlation_id'] == 'corr-9'
        assert out[0]['response'].startswith("[VERIFY_FAILED]")


class TestDeadlineBudget:
    """V3/C2 : budget wall-time — deadline (epoch) portée par la tâche."""

    def test_deadline_expiree_ne_lance_ni_claude_ni_verify(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(verifier, "run",
                            lambda *args, **kw: calls.append(1) or (True, False, ""))
        a = _make_bridge_agent(tmp_path)
        _run_gate(a, {'prompt': 'go', 'from_agent': 'cli', 'msg_id': 'm1',
                      'ack_id': 'ack-d', 'verify_cmd': 'exit 0',
                      'task_id': 't6', 'deadline': str(int(time.time()) - 60)},
                  lambda: len(_outbox(a)) >= 1)
        out = _outbox(a)
        assert out[0]['response'] == "[VERIFY_FAILED] BLOCKED|task=t6|raison=deadline"
        assert a.seen_prompts == []   # _run_claude jamais appelé
        assert calls == []            # verifier.run jamais appelé
        assert a.redis.acks == [(a.inbox, a.group, 'ack-d')]

    def test_deadline_future_flux_normal(self, tmp_path, monkeypatch):
        monkeypatch.setattr(verifier, "run",
                            lambda *args, **kw: (True, False, ""))
        a = _make_bridge_agent(tmp_path)
        _run_gate(a, {'prompt': 'go', 'from_agent': 'cli', 'msg_id': 'm1',
                      'verify_cmd': 'exit 0', 'task_id': 't7',
                      'deadline': str(int(time.time()) + 3600)},
                  lambda: len(_outbox(a)) >= 1)
        assert _outbox(a)[0]['response'].endswith("[VERIFY_GREEN]")

    def test_deadline_invalide_ignoree(self, tmp_path, monkeypatch):
        """deadline non numérique = absente (robustesse aux messages malformés)."""
        monkeypatch.setattr(verifier, "run",
                            lambda *args, **kw: (True, False, ""))
        a = _make_bridge_agent(tmp_path)
        _run_gate(a, {'prompt': 'go', 'from_agent': 'cli', 'msg_id': 'm1',
                      'verify_cmd': 'exit 0', 'task_id': 't8',
                      'deadline': 'demain'},
                  lambda: len(_outbox(a)) >= 1)
        assert _outbox(a)[0]['response'].endswith("[VERIFY_GREEN]")


class TestWalEmissions:
    """V3/C2 : le bridge journalise task_assigned / verify_* dans le WAL."""

    def _wal_events(self, a):
        stream = "wal"
        return [f['event'] for s, f in a.redis.entries if s == stream]

    def test_green_path_emits_assigned_then_green(self, tmp_path, monkeypatch):
        monkeypatch.setattr(verifier, "run",
                            lambda *args, **kw: (True, False, ""))
        a = _make_bridge_agent(tmp_path)
        _run_gate(a, {'prompt': 'go', 'from_agent': 'cli', 'msg_id': 'm1',
                      'verify_cmd': 'exit 0', 'task_id': 't9'},
                  lambda: len(_outbox(a)) >= 1)
        assert self._wal_events(a) == ["task_assigned", "verify_green"]

    def test_red_then_green_emits_full_trace(self, tmp_path, monkeypatch):
        seen = []

        def fake_run(task, *args, **kw):
            seen.append(1)
            return (False, False, "KO") if len(seen) == 1 else (True, False, "")

        monkeypatch.setattr(verifier, "run", fake_run)
        a = _make_bridge_agent(tmp_path)
        _run_gate(a, {'prompt': 'go', 'from_agent': 'cli', 'msg_id': 'm1',
                      'verify_cmd': 'exit 0', 'task_id': 't10'},
                  lambda: len(_outbox(a)) >= 1)
        assert self._wal_events(a) == [
            "task_assigned", "verify_red", "verify_retry",
            "task_assigned", "verify_green"]

    def test_v2_task_emits_only_task_assigned(self, tmp_path, monkeypatch):
        monkeypatch.setattr(verifier, "run",
                            lambda *args, **kw: (True, False, ""))
        a = _make_bridge_agent(tmp_path)
        _run_gate(a, {'prompt': 'tâche v2', 'from_agent': 'cli', 'msg_id': 'm1'},
                  lambda: len(_outbox(a)) >= 1)
        assert self._wal_events(a) == ["task_assigned"]

    def test_wal_indisponible_ne_tue_pas_le_bridge(self, tmp_path, monkeypatch):
        """Panne Redis sur le WAL uniquement : la tâche aboutit quand même."""
        monkeypatch.setattr(verifier, "run",
                            lambda *args, **kw: (True, False, ""))
        a = _make_bridge_agent(tmp_path)
        wal_stream = "wal"
        original_xadd = a.redis.xadd

        def failing_xadd(stream, fields, **kw):
            if stream == wal_stream:
                raise ConnectionError("WAL indisponible")
            return original_xadd(stream, fields, **kw)

        a.redis.xadd = failing_xadd
        _run_gate(a, {'prompt': 'go', 'from_agent': 'cli', 'msg_id': 'm1',
                      'verify_cmd': 'exit 0', 'task_id': 't11'},
                  lambda: len(_outbox(a)) >= 1)
        assert _outbox(a)[0]['response'].endswith("[VERIFY_GREEN]")
