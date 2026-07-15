"""Agent 000 reste dans la liste HTTP et dans les mises à jour frontend."""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web/backend"))

from multi_agent import state
from multi_agent.routers.agents import list_agents


@pytest.mark.anyio
async def test_api_agents_includes_architect_000():
    previous = state._cache
    state._cache = {
        "agents": [
            {"id": "000", "status": "active"},
            {"id": "300", "status": "idle"},
        ],
        "timestamp": 123,
    }
    try:
        result = await list_agents()
    finally:
        state._cache = previous

    assert [agent["id"] for agent in result["agents"]] == ["000", "300"]
    assert result["count"] == 2


def test_frontend_websocket_update_does_not_filter_000():
    source = (ROOT / "web/frontend/src/hooks/useAgentsData.js").read_text(
        encoding="utf-8"
    )
    assert "const incoming = data.agents" in source
    assert ".filter(a => (a.id || '').split('-')[0] !== '000')" not in source


def test_000_is_controllable_like_any_agent():
    """000 (Architect) est pilotable depuis le dashboard comme tout agent :
    plus aucune garde 403 `base_id == "000"` dans les routes agents, et le
    flux /ws/agent/000 n'est plus rejeté (l'endpoint WS est en lecture seule —
    seuls les pings client y sont traités)."""
    agents = (ROOT / "web/backend/multi_agent/routers/agents.py").read_text(
        encoding="utf-8"
    )
    websocket = (ROOT / "web/backend/multi_agent/routers/ws.py").read_text(
        encoding="utf-8"
    )
    assert 'detail="Cannot control architect agent' not in agents
    assert 'await _reject(websocket, 4005)' not in websocket


def test_000_lifecycle_explicitly_unlocks_agent_script():
    agents = (ROOT / "web/backend/multi_agent/routers/agents.py").read_text(
        encoding="utf-8"
    )
    agent_script = (ROOT / "scripts/agent.sh").read_text(encoding="utf-8")
    assert '"ALLOW_PROTECTED_000=1"' in agents
    assert '${ALLOW_PROTECTED_000:-0}' in agent_script
