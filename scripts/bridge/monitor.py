#!/usr/bin/env python3
"""
monitor.py - Real-time monitor for all agent communications
Usage: python3 monitor.py [--compact]
"""

import sys
import time
import redis
from datetime import datetime

# Colors
COLORS = {
    'reset': '\033[0m',
    'red': '\033[0;31m',
    'green': '\033[0;32m',
    'yellow': '\033[1;33m',
    'blue': '\033[0;34m',
    'magenta': '\033[0;35m',
    'cyan': '\033[0;36m',
    'white': '\033[1;37m',
    'gray': '\033[0;90m',
}

# Agent type colors
AGENT_COLORS = {
    '0': 'magenta',   # Super-Master
    '1': 'cyan',      # Master
    '2': 'blue',      # Explorer
    '3': 'green',     # Developer
    '4': 'yellow',    # Integrator
    '5': 'red',       # Tester
    '6': 'magenta',   # Releaser
    '9': 'red',       # Architect
}

def c(color, text):
    """Colorize text"""
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"

def agent_color(agent_id):
    """Get color for agent based on ID"""
    if agent_id:
        return AGENT_COLORS.get(str(agent_id)[0], 'white')
    return 'white'

def truncate(text, max_len=60):
    """Truncate text with ellipsis"""
    if not text:
        return ''
    text = text.replace('\n', ' ').strip()
    if len(text) > max_len:
        return text[:max_len] + '...'
    return text

def format_message(stream, msg_id, data, compact=False):
    """Format a message for display"""
    # Parse stream: ma:agent:300:inbox or ma:agent:300:outbox
    parts = stream.split(':')
    if len(parts) < 4:
        return None

    agent_id = parts[2]
    direction = parts[3]
    color = agent_color(agent_id)

    timestamp = datetime.now().strftime('%H:%M:%S')

    # Extract fields
    prompt = data.get('prompt', '')
    response = data.get('response', '')
    from_agent = data.get('from_agent', '')
    to_agent = data.get('to_agent', '')
    msg_type = data.get('type', 'prompt')

    if direction == 'inbox':
        arrow = c('yellow', '→')
        if prompt:
            content = truncate(prompt, 80 if not compact else 40)
            src = f"from:{from_agent}" if from_agent else ""
            return f"{c('gray', timestamp)} {arrow} {c(color, f'[{agent_id}]')} {c('gray', src)} {c('white', content)}"
        elif response:
            src = f"response from:{from_agent}" if from_agent else "response"
            return f"{c('gray', timestamp)} {arrow} {c(color, f'[{agent_id}]')} {c('gray', src)} ({len(response)} chars)"
    else:  # outbox
        arrow = c('green', '←')
        if response:
            content = truncate(response, 80 if not compact else 40)
            dst = f"to:{to_agent}" if to_agent else ""
            return f"{c('gray', timestamp)} {arrow} {c(color, f'[{agent_id}]')} {c('gray', dst)} {c('green', content)}"

    return None

def main():
    compact = '--compact' in sys.argv or '-c' in sys.argv

    print(c('cyan', '╔' + '═'*60 + '╗'))
    print(c('cyan', '║') + '       MULTI-AGENT REAL-TIME MONITOR'.center(60) + c('cyan', '║'))
    print(c('cyan', '╚' + '═'*60 + '╝'))
    print()
    print(c('yellow', 'Legend:'),
          c('magenta', '0XX=Super'),
          c('cyan', '1XX=Master'),
          c('blue', '2XX=Explorer'),
          c('green', '3XX=Dev'),
          c('yellow', '4XX=Merge'),
          c('red', '5XX=Test'))
    print(c('yellow', 'Press Ctrl+C to quit'))
    print()

    r = redis.Redis(host='localhost', port=6379, decode_responses=True)

    # Track last IDs per stream
    last_ids = {}

    try:
        while True:
            # Get all agent streams
            inbox_streams = r.keys('ma:agent:*:inbox')
            outbox_streams = r.keys('ma:agent:*:outbox')
            all_streams = inbox_streams + outbox_streams

            if not all_streams:
                time.sleep(1)
                continue

            # Build stream dict for XREAD
            streams_dict = {}
            for stream in all_streams:
                streams_dict[stream] = last_ids.get(stream, '$')

            # Read with short block
            try:
                result = r.xread(streams_dict, block=500, count=10)
            except redis.ConnectionError:
                print(c('red', '[ERROR] Redis connection lost, retrying...'))
                time.sleep(2)
                continue

            if result:
                for stream, messages in result:
                    for msg_id, data in messages:
                        last_ids[stream] = msg_id

                        line = format_message(stream, msg_id, data, compact)
                        if line:
                            print(line, flush=True)

    except KeyboardInterrupt:
        print(c('yellow', '\nMonitor stopped.'))

if __name__ == '__main__':
    main()
