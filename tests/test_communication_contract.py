"""Garde-fous du contrat de communication inter-agent."""

import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEND = ROOT / "scripts" / "send.sh"
DONE = ROOT / "scripts" / "done.sh"
REPORT_MASTER = ROOT / "scripts" / "report-master.sh"
BUS_PROTOCOL = ROOT / "scripts" / "agent-bridge" / "bus_protocol.py"
PUBLISH_LUA = ROOT / "scripts" / "agent-bridge" / "publish_event.lua"


def prompt_documents():
    for root_name in ("prompts", "templates", "examples"):
        for path in (ROOT / root_name).rglob("*.md"):
            if path.is_file() and "removed" not in path.parts:
                yield path


def test_no_legacy_transport_in_prompts():
    forbidden = re.compile(
        r'ma:(?:agent|inject):|redis-cli\s+(?:XADD|RPUSH)|'
        r'send\.sh[^\n]*(?:FROM:|\|DONE|\|SCORE)')
    failures = []
    for path in prompt_documents():
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if forbidden.search(line):
                failures.append(f"{path.relative_to(ROOT)}:{number}")
    assert not failures, "legacy transport: " + ", ".join(failures)


def test_common_contract_is_present():
    agent = (ROOT / "prompts" / "AGENT.md").read_text()
    assert "Contrat absolu de réponse inter-agent" in agent
    assert "PROMPT_RELOADED" in agent
    assert "ORPHANED" in agent
    assert "ALREADY_DELIVERED" in agent
    assert "NOT_DELIVERED" in agent
    assert "STATUS=WORKING" in agent
    assert "STATUS_REQUIRED" in agent
    assert "pool-requests/state/" in agent
    assert "Rapport obligatoire au coordinateur du triangle" in agent
    assert "report-master.sh" in agent
    assert "DECISION_REQUIRED" in agent
    assert "ALREADY_STORED" in agent
    assert "seconde copie manuelle" in agent


def test_blocking_report_contract_reaches_loaders_and_future_agents():
    sources = [
        ROOT / "prompts" / "AGENT.md",
        ROOT / "templates" / "x45" / "prompts" / "AGENT.md",
        ROOT / "examples" / "3-x45-simple" / "prompts" / "AGENT.md",
        ROOT / "examples" / "4-x45-complet" / "prompts" / "AGENT.md",
        ROOT / "patch" / "rebalance-agent-prompts.py",
    ]
    for path in sources:
        text = path.read_text()
        assert "DECISION_REQUIRED" in text or "identité de décision" in text, path
        assert "copie manuelle" in text, path
    generated = sources[-1].read_text()
    assert "publisher partage l'identité de décision" in generated


def test_common_contract_suppresses_noop_and_resumes_deferred_work():
    sources = [
        ROOT / "prompts" / "AGENT.md",
        ROOT / "prompts" / "RULES.md",
        ROOT / "templates" / "x45" / "prompts" / "AGENT.md",
        ROOT / "prompts" / "160-create-x45" / "160-160-system.md",
    ]
    for path in sources:
        text = path.read_text()
        assert "NOOP" in text, path
        assert "USER_RESULT_CONTRACT" in text, path
        assert "RESUME_EVENT" in text, path
    agent = sources[0].read_text()
    for transition in (
            "CLOSED_SUCCESS", "NEXT_CYCLE_OPENED",
            "USER_BLOCKED", "CLOSED_FAILED"):
        assert transition in agent
    assert "RUNTIME_INCONSISTENCY" in agent


def run_script(path, *args, env_extra=None, redis_client=None):
    env = dict(os.environ)
    env.pop("TMUX", None)
    if redis_client is not None:
        connection = redis_client.connection_pool.connection_kwargs
        env.update({
            "REDIS_HOST": str(connection["host"]),
            "REDIS_PORT": str(connection["port"]),
            "REDIS_DB": str(connection.get("db", 0)),
            "REDIS_PASSWORD": "",
        })
    env.update(env_extra or {})
    return subprocess.run(
        ["bash", str(path), *args],
        capture_output=True, text=True, env=env, timeout=30)


def test_send_rejects_implicit_interagent_correlation(redis_client):
    result = run_script(
        SEND, "300", "travail",
        env_extra={"FROM_AGENT": "100", "TASK_ID": "t", "CYCLE": "1"},
        redis_client=redis_client)
    assert result.returncode == 2
    assert "requires TASK_ID, CYCLE and CORRELATION_ID" in result.stderr


def test_dispatch_requires_expected_event(redis_client):
    result = run_script(
        SEND, "300", "travail",
        env_extra={
            "FROM_AGENT": "100", "TASK_ID": "t", "CYCLE": "1",
            "CORRELATION_ID": "c", "MESSAGE_EVENT": "DISPATCH"},
        redis_client=redis_client)
    assert result.returncode == 2
    assert "DISPATCH requires EXPECTED_EVENT" in result.stderr


def test_terminal_requires_complete_envelope(redis_client):
    result = run_script(
        DONE, "100", "DONE",
        env_extra={"FROM_AGENT": "300", "TASK_ID": "t", "CYCLE": "1"},
        redis_client=redis_client)
    assert result.returncode == 2
    assert "terminal requires TASK_ID, CYCLE and CORRELATION_ID" in result.stderr


def test_rescue_events_are_the_only_incomplete_envelope_escape_hatch():
    publisher = BUS_PROTOCOL.read_text()
    assert 'MESSAGE_RESCUES = {"INFO_REQUIRED", "PROTOCOL_ERROR", "STATUS_REQUIRED"}' in publisher
    assert 'TERMINAL_RESCUES = {"INFO_REQUIRED", "PROTOCOL_ERROR"}' in publisher
    assert 'task_id = task_id or "unattributed"' in publisher
    assert 'cycle = cycle or "unattributed"' in publisher
    assert '_stable_id(\n            "rescue"' in publisher


def test_terminal_dedup_distinguishes_replay_from_conflict():
    done = DONE.read_text()
    publisher = BUS_PROTOCOL.read_text()
    lua = PUBLISH_LUA.read_text()
    assert "_fingerprint" in publisher
    assert 'if mode == "terminal"' in lua
    assert '"payload_sha256"' in lua
    assert '"REPLAY"' in lua
    assert '"CONFLICT"' in lua
    assert "state=ALREADY_DELIVERED" in done
    assert "state=NOT_DELIVERED" in done
    assert "exit 3" in done


def test_prompt_migration_is_idempotent():
    result = subprocess.run(
        ["python3", str(ROOT / "patch" / "rebalance-agent-prompts.py"),
         "--base", str(ROOT), "--no-backup", "--check"],
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0
    assert result.stdout.strip().endswith("updated=0")


def test_master_report_is_supervision_not_business_completion():
    source = REPORT_MASTER.read_text()
    publisher = BUS_PROTOCOL.read_text()
    lua = PUBLISH_LUA.read_text()
    assert "bus_protocol.py" in source
    assert " publish" not in source.lower() or "PUBLISH_OUTPUT" in source
    assert 'f"agent:{args.to_agent}:reports"' in publisher
    assert '"event", "MASTER_REPORT"' in lua
    assert '"classification", "supervision"' in lua
    assert '"correlation_id", "turn-" .. ARGV[21]' in lua
    assert "XADD" not in source
    assert "done.sh" not in source
    assert "send.sh" not in source
    assert "triangle_master_id" in source
