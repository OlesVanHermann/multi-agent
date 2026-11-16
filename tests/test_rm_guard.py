"""Le hook PreToolUse refuse les invocations de rm/rmdir/unlink, jamais une
mention citée du motif."""

import importlib.util
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "claude-rm-guard.py"


def load_guard():
    spec = importlib.util.spec_from_file_location("claude_rm_guard", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUARD = load_guard()


# --- formes refusées (scan renvoie un motif) -------------------------------

REFUSED = [
    "rm -rf x",
    "rm -r x",
    "rm x",
    "rm -rf /dev/null",
    "cmd && rm -rf x",
    "cmd; rm x",
    "true || rmdir d",
    "bash -c 'rm -r x'",
    "sh -c \"rm -rf $HOME/x\"",
    "ls | xargs rm",
    "ls | xargs -0 rm -rf",
    "find . -delete",
    "find . -exec rm {} +",
    "find . -execdir rm {} \\;",
    "rmdir d",
    "unlink f",
    "echo hi && rm -rf build",
    "$(rm -rf x)",
    "foo `rm -rf x`",
    "sudo rm -rf /x",
    "sudo -u root rm -rf /x",
    "env A=b rm x",
    "/bin/rm -rf x",
    "nohup rm -rf x",
    "( rm -rf x )",
]


@pytest.mark.parametrize("cmd", REFUSED)
def test_refused_forms_are_blocked(cmd):
    assert GUARD.scan(cmd), f"non bloqué : {cmd!r}"


# --- formes acceptées (scan renvoie vide) ----------------------------------

ACCEPTED = [
    "mv x $BASE/removed/20260930_000000_x",
    "mv x \"$BASE/removed/$(date +%Y%m%d_%H%M%S)_x\"",
    "cargo clean --target-dir /tmp/t",
    "git worktree remove foo",
    "echo 'rm -rf'",
    "echo \"rm -rf /dev/null\"",
    "grep -n 'rm -rf' f",
    "grep rm file",
    "./scripts/send.sh 305-105 \"FROM:305|DONE rm -rf /dev/null interdit\"",
    "printf '%s\\n' 'rm -rf /tmp'",
    "$(date) rm",
    "ls -la",
    "find . -name '*.tmp' -print",
    "rg 'rm -r' docs/",
]


@pytest.mark.parametrize("cmd", ACCEPTED)
def test_accepted_forms_pass(cmd):
    assert GUARD.scan(cmd) == "", f"faux positif : {cmd!r}"


# --- I/O du hook -----------------------------------------------------------

def run_hook(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    return GUARD.main()


def test_hook_blocks_bash_rm(monkeypatch, capsys):
    rc = run_hook(monkeypatch, {
        "tool_name": "Bash", "tool_input": {"command": "rm -rf build"}})
    assert rc == 2
    assert "Suppression interdite" in capsys.readouterr().err


def test_hook_allows_bash_mv(monkeypatch):
    rc = run_hook(monkeypatch, {
        "tool_name": "Bash",
        "tool_input": {"command": "mv build $BASE/removed/b"}})
    assert rc == 0


def test_witness_hook_inert_on_non_bash_tool(monkeypatch):
    """Témoin : hors de l'outil Bash (hook non applicable / retiré), la forme
    refusée n'est pas bloquée."""
    rc = run_hook(monkeypatch, {
        "tool_name": "Read", "tool_input": {"command": "rm -rf x"}})
    assert rc == 0
