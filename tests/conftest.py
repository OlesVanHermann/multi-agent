"""
Fixtures partagées pour les tests 345-output
Complémente tests/conftest.py du projet principal

EF-001, EF-002, EF-003, EF-004 — Fixtures pour mocks Redis, tmux, CDP
"""
import pytest
import os
import sys
import subprocess
import time
from unittest.mock import MagicMock, patch

# Add paths — R-SYMLINKPROOF: robust path resolution via marker search
def _find_project_root(start, markers=('CLAUDE.md', '.git')):
    """Remonte les répertoires jusqu'à trouver un marqueur du projet (R-SYMLINKPROOF)."""
    current = os.path.realpath(start)
    while current != os.path.dirname(current):
        if any(os.path.exists(os.path.join(current, m)) for m in markers):
            return current
        current = os.path.dirname(current)
    raise FileNotFoundError(f"Marqueur {markers} introuvable en remontant depuis {start}")

_BASE = _find_project_root(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(_BASE, 'core', 'agent-bridge'))
sys.path.insert(0, os.path.join(os.path.realpath(os.path.dirname(__file__)), '..', 'refactoring'))


@pytest.fixture
def mock_redis_client():
    """Mock Redis client with common operations pre-configured"""
    client = MagicMock()
    client.ping.return_value = True
    client.get.return_value = None
    client.set.return_value = True
    client.delete.return_value = 1
    client.keys.return_value = []
    client.hset.return_value = True
    client.hgetall.return_value = {}
    client.xadd.return_value = "1-0"
    client.xread.return_value = None
    client.blpop.return_value = None
    client.rpush.return_value = 1
    return client


@pytest.fixture
def mock_websocket():
    """Mock WebSocket connection for CDP tests"""
    ws = MagicMock()
    ws.send = MagicMock()
    ws.recv = MagicMock(return_value='{"id": 1, "result": {}}')
    ws.close = MagicMock()
    ws.settimeout = MagicMock()
    return ws


@pytest.fixture
def sample_cdp_responses():
    """Sample CDP response data for testing"""
    import json
    return {
        'empty': json.dumps({"id": 1, "result": {}}),
        'string_value': json.dumps({
            "id": 1,
            "result": {"result": {"type": "string", "value": "test"}}
        }),
        'bool_true': json.dumps({
            "id": 1,
            "result": {"result": {"type": "boolean", "value": True}}
        }),
        'bool_false': json.dumps({
            "id": 1,
            "result": {"result": {"type": "boolean", "value": False}}
        }),
        'coords': json.dumps({
            "id": 1,
            "result": {"result": {"type": "object", "value": {"x": 100, "y": 200}}}
        }),
        'null_value': json.dumps({
            "id": 1,
            "result": {"result": {"type": "object", "value": None}}
        }),
        'error': json.dumps({
            "id": 1,
            "error": {"message": "Element not found"}
        }),
        'screenshot': json.dumps({
            "id": 1,
            "result": {"data": "iVBORw0KGgo="}  # minimal base64
        }),
    }


@pytest.fixture
def agent_bridge_mocks():
    """Common mocks for TmuxAgent initialization"""
    with patch('agent.subprocess.run') as mock_run, \
         patch('agent.redis.Redis') as mock_redis_cls:
        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.return_value = True
        mock_redis_cls.return_value = mock_redis_instance
        mock_run.return_value = MagicMock(returncode=0, stdout="10\n")
        yield {
            'run': mock_run,
            'redis_cls': mock_redis_cls,
            'redis': mock_redis_instance,
        }
