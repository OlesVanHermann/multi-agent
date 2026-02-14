"""
Pytest fixtures for multi-agent tests
"""
import pytest
import subprocess
import time
import os
import sys

# Add core to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core', 'agent-bridge'))


@pytest.fixture
def redis_client():
    """Get a Redis client for testing"""
    try:
        import redis
        client = redis.Redis(host='localhost', port=6379, decode_responses=True)
        client.ping()
        yield client
        # Cleanup test keys
        for key in client.keys('ma:test:*'):
            client.delete(key)
    except Exception as e:
        pytest.skip(f"Redis not available: {e}")


@pytest.fixture
def mock_tmux_session():
    """Create a mock tmux session for testing"""
    session_name = "test-agent-999"

    # Kill if exists
    subprocess.run(["tmux", "kill-session", "-t", session_name],
                   capture_output=True)

    # Create session
    subprocess.run(["tmux", "new-session", "-d", "-s", session_name, "-x", "200", "-y", "50"],
                   capture_output=True)

    yield session_name

    # Cleanup
    subprocess.run(["tmux", "kill-session", "-t", session_name],
                   capture_output=True)


@pytest.fixture
def sample_messages():
    """Sample messages for testing"""
    return {
        'simple': 'Hello agent',
        'with_from': 'FROM:100|go scaleway.com',
        'with_type': 'FROM:300|DONE scaleway.com - SUCCESS',
        'multiline': 'Line 1\nLine 2\nLine 3',
    }
