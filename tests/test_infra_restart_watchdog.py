"""restart-watchdog : recharge le seul watchdog, jamais un stop/start global."""

import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INFRA = (ROOT / "scripts" / "infra.sh").read_text()
LIB = ROOT / "scripts" / "lib.sh"


def _function_body(source, name):
    start = source.index(f"{name}() {{")
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
    raise AssertionError(f"{name} body not found")


def test_dispatch_has_dedicated_action():
    assert "restart-watchdog) do_restart_watchdog ;;" in INFRA


def test_restart_watchdog_never_touches_global_services():
    """La commande préserve Redis, Keycloak, le dashboard, 000 et les
    agents : aucun appel global ne doit apparaître dans son corps."""
    body = _function_body(INFRA, "do_restart_watchdog")
    for forbidden in ("do_stop", "do_start", "docker", "tmux",
                      "agent.sh", "web.sh", "systemctl", "redis_cli",
                      "stop_watchdog"):
        assert forbidden not in body, forbidden


def test_restart_watchdog_verifies_pid_identity_before_kill():
    body = _function_body(INFRA, "do_restart_watchdog")
    assert "WATCHDOG_PID_FILE" in body
    assert "watchdog_pid_matches" in body
    assert body.index("watchdog_pid_matches") < body.index('kill "$pid"')
    assert "start_watchdog" in body
    assert "/proc/uptime" in body  # durée mesurée sur horloge monotone


def _pid_matches(pid):
    return subprocess.run(
        ["bash", "-c", f'source "{LIB}"; watchdog_pid_matches {pid}'],
        capture_output=True).returncode == 0


def test_pid_identity_check_accepts_only_watchdog():
    fake = subprocess.Popen(
        ["python3", "-c", "import time; time.sleep(60)",
         "healthcheck.py", "--watchdog"])
    other = subprocess.Popen(["sleep", "60"])
    try:
        time.sleep(0.2)
        assert _pid_matches(fake.pid)
        assert not _pid_matches(other.pid)
        assert not _pid_matches(99999999)
        assert not _pid_matches("")
    finally:
        fake.kill()
        other.kill()
        fake.wait()
        other.wait()
