#!/usr/bin/env python3
"""
Crontab Scheduler — sends prompts to agents at aligned time intervals.

Scans crontab/*.prompt files, parses {agent}-{period}.prompt filenames,
and sends the prompt content via Redis XADD at aligned clock boundaries.

Periods and their alignment:
  10  -> :00, :10, :20, :30, :40, :50
  30  -> :00, :30
  60  -> :00
  120 -> even hours (00:00, 02:00, 04:00, ...)

Launch in tmux:
  tmux new-session -d -s A-agent-001-crontab \
    "python3 /home/ubuntu/multi-agent/scripts/crontab-scheduler.py"
"""

import os
import re
import time
import glob
import redis

CRONTAB_DIR = os.environ.get("CRONTAB_DIR", os.path.join(os.path.dirname(__file__), "..", "crontab"))
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
MA_PREFIX = os.environ.get("MA_PREFIX", "A")

VALID_PERIODS = {10, 30, 60, 120}
TICK_INTERVAL = 10  # seconds

# Track last execution to avoid double-fire within same aligned window
# Key: filename, Value: (minute_of_day or hour) when last fired
_last_fired = {}


def is_aligned(minute, hour, period):
    """Check if current time is aligned with the given period."""
    if period == 10:
        return minute % 10 == 0
    elif period == 30:
        return minute % 30 == 0
    elif period == 60:
        return minute == 0
    elif period == 120:
        return minute == 0 and hour % 2 == 0
    return False


def fire_key(hour, minute, period):
    """Return a unique key for the current aligned window to prevent double-fire."""
    if period == 120:
        return hour
    return hour * 60 + minute


def scan_and_execute(r):
    """Scan crontab dir and execute aligned prompts."""
    now = time.localtime()
    minute = now.tm_min
    hour = now.tm_hour

    pattern = os.path.join(CRONTAB_DIR, "*.prompt")
    for filepath in glob.glob(pattern):
        filename = os.path.basename(filepath)

        # Skip suspended files (they end with .suspended, not matched by *.prompt)
        # Parse: {agent}-{period}.prompt
        m = re.match(r'^(\d{3}(?:-\d{3})?)_(\d+)\.prompt$', filename)
        if not m:
            continue

        agent_id = m.group(1)
        period = int(m.group(2))

        if period not in VALID_PERIODS:
            print(f"[crontab] SKIP {filename}: invalid period {period}")
            continue

        if not is_aligned(minute, hour, period):
            continue

        # Check if already fired in this window
        key = fire_key(hour, minute, period)
        if _last_fired.get(filename) == key:
            continue

        # Read prompt content
        try:
            with open(filepath, 'r') as f:
                prompt = f.read().strip()
        except Exception as e:
            print(f"[crontab] ERROR reading {filename}: {e}")
            continue

        if not prompt:
            print(f"[crontab] SKIP {filename}: empty prompt")
            continue

        # Send via Redis XADD
        stream = f"{MA_PREFIX}:agent:{agent_id}:inbox"
        try:
            r.xadd(stream, {
                "prompt": prompt,
                "from_agent": "crontab",
                "timestamp": str(int(time.time())),
            })
            _last_fired[filename] = key
            ts = time.strftime("%H:%M:%S")
            print(f"[crontab] {ts} SENT agent={agent_id} period={period}min prompt={prompt[:80]}")
        except Exception as e:
            print(f"[crontab] ERROR sending to {agent_id}: {e}")


def main():
    print(f"[crontab] Starting scheduler (tick={TICK_INTERVAL}s, dir={CRONTAB_DIR})")
    print(f"[crontab] Redis: {REDIS_HOST}:{REDIS_PORT}, prefix: {MA_PREFIX}")

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    # Verify Redis connection
    try:
        r.ping()
        print("[crontab] Redis connected OK")
    except Exception as e:
        print(f"[crontab] WARNING: Redis not available yet: {e}")

    while True:
        try:
            scan_and_execute(r)
        except redis.ConnectionError as e:
            print(f"[crontab] Redis connection lost: {e}, retrying...")
        except Exception as e:
            print(f"[crontab] Unexpected error: {e}")

        time.sleep(TICK_INTERVAL)


if __name__ == "__main__":
    main()
