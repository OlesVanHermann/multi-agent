"""Séquences de touches sérialisées par TUI (dashboard Login & Model).

Constat mx3 2026-10-08 : modèle/effort et advisor envoyés coup sur coup
s'entrelaçaient dans le composer de agent-000 → « /advisor claude-fable-5-1/
effort max » refusé trois fois.
"""

import asyncio
from pathlib import Path

from web.backend.multi_agent import state
from web.backend.multi_agent.routers import config as config_router


class _Result:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


def test_model_effort_and_advisor_never_overlap(monkeypatch):
    spans = []

    async def fake_run(command, **kwargs):
        if command[:2] == ["tmux", "has-session"]:
            return _Result(0)
        start = asyncio.get_running_loop().time()
        await asyncio.sleep(0.05)
        spans.append((start, asyncio.get_running_loop().time()))
        return _Result(0)

    monkeypatch.setattr(config_router, "_run_subprocess", fake_run)
    monkeypatch.setattr(config_router, "_effective_model_id", lambda *_: "claude-opus-5")
    monkeypatch.setattr(state, "redis_pool", None)

    async def scenario():
        return await asyncio.gather(
            config_router._apply_to_live_tui(Path("."), "000", "X", True),
            config_router._apply_advisor_to_live_tui(Path("."), "000", "claude-fable-5-2"),
        )

    results = asyncio.run(scenario())
    assert [applied for applied, _ in results] == [True, True]
    assert len(spans) == 2
    (a_start, a_end), (b_start, b_end) = sorted(spans)
    assert b_start >= a_end, "les deux séquences de touches se chevauchent"
