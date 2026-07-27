"""Garde-fous du contrat de communication inter-agent."""

import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEND = ROOT / "scripts" / "send.sh"
DONE = ROOT / "scripts" / "done.sh"


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


def run_script(path, *args, env_extra=None):
    env = dict(os.environ)
    env.pop("TMUX", None)
    env.update(env_extra or {})
    return subprocess.run(
        ["bash", str(path), *args],
        capture_output=True, text=True, env=env, timeout=30)


def test_send_rejects_implicit_interagent_correlation():
    result = run_script(
        SEND, "300", "travail",
        env_extra={"FROM_AGENT": "100", "TASK_ID": "t", "CYCLE": "1"})
    assert result.returncode == 2
    assert "requires TASK_ID, CYCLE and CORRELATION_ID" in result.stderr


def test_dispatch_requires_expected_event():
    result = run_script(
        SEND, "300", "travail",
        env_extra={
            "FROM_AGENT": "100", "TASK_ID": "t", "CYCLE": "1",
            "CORRELATION_ID": "c", "MESSAGE_EVENT": "DISPATCH"})
    assert result.returncode == 2
    assert "DISPATCH requires EXPECTED_EVENT" in result.stderr


def test_terminal_requires_complete_envelope():
    result = run_script(
        DONE, "100", "DONE",
        env_extra={"FROM_AGENT": "300", "TASK_ID": "t", "CYCLE": "1"})
    assert result.returncode == 2
    assert "terminal requires TASK_ID, CYCLE and CORRELATION_ID" in result.stderr


def test_rescue_events_are_the_only_incomplete_envelope_escape_hatch():
    send = SEND.read_text()
    done = DONE.read_text()
    assert "INFO_REQUIRED|PROTOCOL_ERROR|STATUS_REQUIRED" in send
    assert "INFO_REQUIRED|PROTOCOL_ERROR)" in done
    assert 'TASK_ID="unattributed"' in send
    assert 'CYCLE="unattributed"' in done
    assert "rescue-" in done


def test_terminal_dedup_distinguishes_replay_from_conflict():
    done = DONE.read_text()
    assert "SIGNAL_FINGERPRINT" in done
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
