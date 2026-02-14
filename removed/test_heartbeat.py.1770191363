"""
Tests for heartbeat functionality
"""
import pytest
import time


class TestHeartbeatFormat:
    """Test heartbeat message format"""

    def test_heartbeat_message_structure(self):
        """Test that heartbeat messages have correct structure"""
        # Simulate heartbeat creation (from agent.py logic)
        agent_id = "300"
        status = "WORKING"
        idle_seconds = 45
        task_duration = 120
        queue_size = 0
        preview = "Analyzing files... | Reading config..."

        heartbeat_msg = (
            f"HEARTBEAT {agent_id} | "
            f"status:{status} | "
            f"idle:{idle_seconds}s | "
            f"task_duration:{task_duration}s | "
            f"queue:{queue_size} | "
            f"preview: {preview[:200]}"
        )

        assert f"HEARTBEAT {agent_id}" in heartbeat_msg
        assert "status:WORKING" in heartbeat_msg
        assert "idle:45s" in heartbeat_msg
        assert "task_duration:120s" in heartbeat_msg
        assert "queue:0" in heartbeat_msg
        assert "preview:" in heartbeat_msg

    def test_status_determination(self):
        """Test status logic based on state and idle time"""
        BLOCKED_THRESHOLD = 300  # 5 minutes

        test_cases = [
            # (is_busy, idle_seconds, expected_status)
            (False, 0, "IDLE"),
            (False, 100, "IDLE"),
            (True, 0, "WORKING"),
            (True, 100, "WORKING"),
            (True, 299, "WORKING"),
            (True, 300, "POSSIBLY_BLOCKED"),
            (True, 600, "POSSIBLY_BLOCKED"),
        ]

        for is_busy, idle_seconds, expected in test_cases:
            if is_busy:
                if idle_seconds >= BLOCKED_THRESHOLD:
                    status = "POSSIBLY_BLOCKED"
                else:
                    status = "WORKING"
            else:
                status = "IDLE"

            assert status == expected, f"is_busy={is_busy}, idle={idle_seconds} should be {expected}"


class TestHeartbeatRedis:
    """Test heartbeat storage in Redis"""

    def test_heartbeat_to_master(self, redis_client):
        """Test sending heartbeat to master's inbox"""
        master_inbox = "ma:test:agent:100:inbox"

        heartbeat_data = {
            'heartbeat': 'HEARTBEAT 300 | status:WORKING | idle:45s',
            'from_agent': '300',
            'type': 'heartbeat',
            'status': 'WORKING',
            'idle_seconds': '45',
            'timestamp': str(int(time.time()))
        }

        redis_client.xadd(master_inbox, heartbeat_data)

        # Verify
        result = redis_client.xread({master_inbox: '0'}, count=10)
        assert result is not None
        _, messages = result[0]

        # Find heartbeat
        heartbeats = [m for m in messages if m[1].get('type') == 'heartbeat']
        assert len(heartbeats) >= 1
        assert heartbeats[0][1]['from_agent'] == '300'
        assert heartbeats[0][1]['status'] == 'WORKING'

    def test_multiple_agent_heartbeats(self, redis_client):
        """Test receiving heartbeats from multiple agents"""
        master_inbox = "ma:test:agent:100:inbox_multi"

        # Heartbeats from different agents
        for agent_id in ['300', '301', '302']:
            redis_client.xadd(master_inbox, {
                'type': 'heartbeat',
                'from_agent': agent_id,
                'status': 'WORKING',
                'timestamp': str(int(time.time()))
            })

        result = redis_client.xread({master_inbox: '0'}, count=10)
        _, messages = result[0]

        agents = set(m[1]['from_agent'] for m in messages)
        assert '300' in agents
        assert '301' in agents
        assert '302' in agents


class TestActivityDetection:
    """Test activity detection via pane comparison"""

    def test_content_change_detection(self):
        """Test detecting when pane content changes"""
        last_content = "Line 1\nLine 2\nPrompt >"
        current_content = "Line 1\nLine 2\nProcessing...\nPrompt >"

        content_changed = current_content != last_content
        assert content_changed is True

    def test_no_change_detection(self):
        """Test detecting when pane content stays same"""
        last_content = "Line 1\nLine 2\nPrompt >"
        current_content = "Line 1\nLine 2\nPrompt >"

        content_changed = current_content != last_content
        assert content_changed is False

    def test_idle_time_tracking(self):
        """Test tracking time since last activity"""
        last_activity_time = time.time() - 60  # 60 seconds ago
        current_time = time.time()

        idle_seconds = int(current_time - last_activity_time)
        assert 59 <= idle_seconds <= 61, "Should be ~60 seconds idle"
