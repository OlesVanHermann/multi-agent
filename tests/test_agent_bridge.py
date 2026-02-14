"""
Tests for agent bridge (core/agent-bridge/agent.py)
"""
import pytest
import subprocess
import time


class TestTmuxOperations:
    """Test tmux-related operations"""

    def test_tmux_session_detection(self, mock_tmux_session):
        """Test that we can detect if a tmux session exists"""
        result = subprocess.run(
            ["tmux", "has-session", "-t", mock_tmux_session],
            capture_output=True
        )
        assert result.returncode == 0, "Should detect existing session"

        # Non-existent session
        result = subprocess.run(
            ["tmux", "has-session", "-t", "nonexistent-session-xyz"],
            capture_output=True
        )
        assert result.returncode != 0, "Should not detect non-existent session"

    def test_tmux_send_keys(self, mock_tmux_session):
        """Test sending keys to tmux pane"""
        target = f"{mock_tmux_session}.0"

        # Send some text
        result = subprocess.run(
            ["tmux", "send-keys", "-t", target, "-l", "echo test"],
            capture_output=True
        )
        assert result.returncode == 0, "Should send keys successfully"

    def test_tmux_capture_pane(self, mock_tmux_session):
        """Test capturing tmux pane content"""
        target = f"{mock_tmux_session}.0"

        # Send text first
        subprocess.run(["tmux", "send-keys", "-t", target, "-l", "hello world"],
                      capture_output=True)
        time.sleep(0.1)

        # Capture
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", target, "-p"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, "Should capture pane"
        assert "hello world" in result.stdout, "Should contain sent text"

    def test_escape_enter_sequence(self, mock_tmux_session):
        """Test the Escape + Enter sequence that submits commands in Claude Code"""
        target = f"{mock_tmux_session}.0"

        # Send Escape
        result = subprocess.run(
            ["tmux", "send-keys", "-t", target, "Escape"],
            capture_output=True
        )
        assert result.returncode == 0, "Escape should work"

        time.sleep(0.5)

        # Send Enter
        result = subprocess.run(
            ["tmux", "send-keys", "-t", target, "Enter"],
            capture_output=True
        )
        assert result.returncode == 0, "Enter should work"


class TestMessageParsing:
    """Test message format parsing"""

    def test_from_prefix_parsing(self, sample_messages):
        """Test parsing FROM:xxx| prefix"""
        message = sample_messages['with_from']

        # Simulate parsing logic from agent.py
        from_agent = 'legacy'
        prompt = message
        if message.startswith('FROM:'):
            parts = message.split('|', 1)
            if len(parts) == 2:
                from_agent = parts[0][5:]  # Remove "FROM:" prefix
                prompt = parts[1]

        assert from_agent == '100', "Should extract agent ID"
        assert prompt == 'go scaleway.com', "Should extract prompt"

    def test_simple_message_parsing(self, sample_messages):
        """Test parsing simple message without prefix"""
        message = sample_messages['simple']

        from_agent = 'legacy'
        prompt = message
        if message.startswith('FROM:'):
            parts = message.split('|', 1)
            if len(parts) == 2:
                from_agent = parts[0][5:]
                prompt = parts[1]

        assert from_agent == 'legacy', "Should default to legacy"
        assert prompt == 'Hello agent', "Should keep original message"

    def test_done_message_format(self, sample_messages):
        """Test parsing DONE message format"""
        message = sample_messages['with_type']

        # Parse FROM prefix
        if message.startswith('FROM:'):
            parts = message.split('|', 1)
            from_agent = parts[0][5:]
            content = parts[1]
        else:
            from_agent = 'unknown'
            content = message

        # Parse type
        msg_type = content.split()[0] if content else ''

        assert from_agent == '300', "Should extract agent 300"
        assert msg_type == 'DONE', "Should detect DONE type"
        assert 'SUCCESS' in content, "Should contain status"
