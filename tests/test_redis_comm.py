"""
Tests for Redis communication
"""
import pytest
import time


class TestRedisStreams:
    """Test Redis Streams operations"""

    def test_xadd_and_xread(self, redis_client):
        """Test adding and reading from streams"""
        stream_key = "ma:test:stream"

        # Add message
        msg_id = redis_client.xadd(stream_key, {
            'prompt': 'test message',
            'from_agent': '100',
            'timestamp': str(int(time.time()))
        })
        assert msg_id is not None, "Should return message ID"

        # Read message
        result = redis_client.xread({stream_key: '0'}, count=1)
        assert len(result) == 1, "Should have one stream"

        stream_name, messages = result[0]
        assert len(messages) == 1, "Should have one message"

        read_id, data = messages[0]
        assert data['prompt'] == 'test message'
        assert data['from_agent'] == '100'

    def test_xread_blocking(self, redis_client):
        """Test blocking read with timeout"""
        stream_key = "ma:test:stream_empty"

        # Should timeout quickly with no messages
        start = time.time()
        result = redis_client.xread({stream_key: '$'}, block=100, count=1)
        elapsed = time.time() - start

        assert result is None or len(result) == 0
        assert elapsed < 0.5, "Should timeout after ~100ms"

    def test_response_routing(self, redis_client):
        """Test response message routing"""
        sender_outbox = "ma:test:agent:300:outbox"
        receiver_inbox = "ma:test:agent:100:inbox"

        # Simulate agent 300 sending response to 100
        response_data = {
            'response': 'Task completed successfully',
            'from_agent': '300',
            'type': 'response',
            'timestamp': str(int(time.time())),
            'complete': 'true'
        }

        # Add to receiver's inbox
        redis_client.xadd(receiver_inbox, response_data)

        # Verify it's there
        result = redis_client.xread({receiver_inbox: '0'}, count=1)
        assert result is not None
        _, messages = result[0]
        _, data = messages[0]
        assert data['from_agent'] == '300'
        assert data['type'] == 'response'


class TestRedisLists:
    """Test Redis Lists (legacy format)"""

    def test_rpush_blpop(self, redis_client):
        """Test legacy list-based messaging"""
        list_key = "ma:test:inject:300"

        # Push message
        redis_client.rpush(list_key, "FROM:100|go scaleway.com")

        # Pop with timeout
        result = redis_client.blpop(list_key, timeout=1)
        assert result is not None
        key, message = result
        assert message == "FROM:100|go scaleway.com"

    def test_multiple_messages_order(self, redis_client):
        """Test that messages are received in order (FIFO)"""
        list_key = "ma:test:inject:order"

        # Push in order
        redis_client.rpush(list_key, "message1")
        redis_client.rpush(list_key, "message2")
        redis_client.rpush(list_key, "message3")

        # Pop should be in same order
        _, msg1 = redis_client.blpop(list_key, timeout=1)
        _, msg2 = redis_client.blpop(list_key, timeout=1)
        _, msg3 = redis_client.blpop(list_key, timeout=1)

        assert msg1 == "message1"
        assert msg2 == "message2"
        assert msg3 == "message3"


class TestAgentStatus:
    """Test agent status in Redis"""

    def test_status_hash(self, redis_client):
        """Test storing/reading agent status as hash"""
        status_key = "ma:test:agent:300"

        redis_client.hset(status_key, mapping={
            'status': 'busy',
            'last_seen': str(int(time.time())),
            'queue_size': '2',
            'tasks_completed': '5',
            'mode': 'tmux-interactive'
        })

        status = redis_client.hgetall(status_key)
        assert status['status'] == 'busy'
        assert status['mode'] == 'tmux-interactive'
        assert int(status['tasks_completed']) == 5
