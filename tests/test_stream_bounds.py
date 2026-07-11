"""A3 — Tout xadd Python du framework doit être borné (maxlen).

Lint AST : un stream Redis non borné croît indéfiniment ; chaque appel
.xadd(...) des modules producteurs doit passer maxlen= explicitement.
"""

import ast
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent

CHECKED_FILES = [
    "scripts/agent-bridge/agent.py",
    "scripts/agent-bridge/orchestrator.py",
    "scripts/agent-bridge/monitoring/alert_manager.py",
    "scripts/agent-bridge/monitoring/alerting.py",
]


def _unbounded_xadds(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "xadd"
        ):
            keywords = {kw.arg for kw in node.keywords}
            if "maxlen" not in keywords:
                offenders.append(node.lineno)
    return offenders


@pytest.mark.parametrize("relpath", CHECKED_FILES)
def test_all_xadd_calls_are_bounded(relpath):
    path = BASE / relpath
    assert path.exists(), f"fichier manquant: {relpath}"
    offenders = _unbounded_xadds(path)
    assert not offenders, (
        f"{relpath}: xadd sans maxlen aux lignes {offenders} — "
        "ajouter maxlen=..., approximate=True (brief A3)"
    )


def test_send_sh_xadd_is_bounded():
    text = (BASE / "scripts/send.sh").read_text(encoding="utf-8")
    for line in text.splitlines():
        if "REDIS_CLI XADD" in line and "MAXLEN" not in line.upper():
            pytest.fail(f"send.sh: XADD sans MAXLEN: {line.strip()}")
