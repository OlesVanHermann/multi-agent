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
import json
import time
import glob
import subprocess
import concurrent.futures
import redis

CRONTAB_DIR = os.environ.get("CRONTAB_DIR", os.path.join(os.path.dirname(__file__), "..", "crontab"))
KEEPALIVE_DIR = os.environ.get("KEEPALIVE_DIR", os.path.join(os.path.dirname(__file__), "..", "keepalive"))
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
MA_PREFIX = os.environ.get("MA_PREFIX", "A")

VALID_PERIODS = {10, 30, 60, 120}
KEEPALIVE_PERIOD = 1440  # 24 hours
USAGE_PERIOD = 30  # minutes

# Round-robin index for usage scraping (one profile every 5 min)
_usage_rr_idx = 0
CLAUDE_PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
TICK_INTERVAL = 10  # seconds

# Track last execution to avoid double-fire within same aligned window
# Key: filename, Value: (minute_of_day or hour) when last fired
_last_fired = {}


def is_aligned(minute, hour, period):
    """Check if current time is aligned with the given period."""
    if period == 5:
        return minute % 5 == 0
    elif period == 10:
        return minute % 10 == 0
    elif period == 30:
        return minute % 30 == 0
    elif period == 60:
        return minute == 0
    elif period == 120:
        return minute == 0 and hour % 2 == 0
    elif period == 720:
        return minute == 0 and hour % 12 == 0
    elif period == 1440:
        return minute == 0 and hour == 0
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
            print(f"SKIP {filename}: invalid period {period}")
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
            print(f"ERROR reading {filename}: {e}")
            continue

        if not prompt:
            print(f"SKIP {filename}: empty prompt")
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
            print(f"{ts} SENT agent={agent_id} period={period}min prompt={prompt[:40]}")
        except Exception as e:
            print(f"ERROR sending to {agent_id}: {e}")


KEEPALIVE_USAGE_PERIOD = 5  # minutes — scrape one profile every 5 min (round-robin)


def _scrape_usage_tab(session_name):
    """Send /status to a tmux session, capture info, navigate to Usage tab, scrape, Escape.

    Process: /status Enter → capture info → Right → Right → scrape usage → Escape

    Returns (bars, info) tuple. bars is list of dicts or None, info is dict.
    """
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", session_name, "/status", "Enter"],
            timeout=5
        )
        time.sleep(2)

        # Capture Status tab (info fields)
        cap_info = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-30"],
            capture_output=True, text=True, timeout=5
        )
        info = {}
        if cap_info.returncode == 0:
            for line in cap_info.stdout.split('\n'):
                line = line.strip()
                for field in ["Login method", "Organization", "Email", "Model", "cwd", "Memory"]:
                    if line.startswith(f"{field}:"):
                        info[field.lower().replace(" ", "_")] = line.split(":", 1)[1].strip()

        # Navigate: Status → Config → Usage (Right, Right — one at a time)
        subprocess.run(
            ["tmux", "send-keys", "-t", session_name, "Right"],
            timeout=5
        )
        time.sleep(1)
        subprocess.run(
            ["tmux", "send-keys", "-t", session_name, "Right"],
            timeout=5
        )

        # Wait for usage data to load
        # Poll every 2s up to 10s total
        output = ""
        for _ in range(5):
            time.sleep(2)
            cap = subprocess.run(
                ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-30"],
                capture_output=True, text=True, timeout=5
            )
            output = cap.stdout
            if "% used" in output:
                break
            if "Loading" not in output:
                break  # dialog closed or something else

        # Close settings
        subprocess.run(
            ["tmux", "send-keys", "-t", session_name, "Escape"],
            timeout=5
        )

        # Parse bars: "Current session\n  ██████▌   15% used\n  Resets ..."
        bars = []
        lines = output.split("\n")
        for i, line in enumerate(lines):
            pct_match = re.search(r'(\d+)%\s+used', line)
            if not pct_match:
                continue
            pct = int(pct_match.group(1))
            label = ""
            for j in range(i - 1, max(i - 4, -1), -1):
                stripped = lines[j].strip()
                if stripped.startswith("Current") or stripped.startswith("Daily") or stripped.startswith("Weekly"):
                    label = stripped
                    break
            resets = ""
            for j in range(i + 1, min(i + 3, len(lines))):
                reset_match = re.search(r'Resets\s+(.+)', lines[j])
                if reset_match:
                    resets = reset_match.group(1).strip()
                    break
            bars.append({"label": label, "percent": pct, "resets": resets})

        return (bars if bars else None, info)

    except Exception as e:
        # Try to close settings on error
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", session_name, "Escape"],
                timeout=5
            )
        except Exception:
            pass
        ts = time.strftime("%H:%M:%S")
        print(f"{ts} KEEPALIVE usage scrape error [{session_name}]: {e}")
        return (None, {})


def scan_keepalive():
    """Scan keepalive dir: usage scraping every 5min, one profile at a time (round-robin).

    The /status scrape also serves as keepalive — no separate heartbeat needed.
    With 8 profiles, each is scraped every 40 minutes.
    """
    now = time.localtime()
    minute = now.tm_min
    hour = now.tm_hour

    if not is_aligned(minute, hour, KEEPALIVE_USAGE_PERIOD):
        return

    global _usage_rr_idx
    usage_key = fire_key(hour, minute, KEEPALIVE_USAGE_PERIOD)
    if _last_fired.get("keepalive_usage_rr") == usage_key:
        return

    # Build sorted list of active profiles with valid tmux sessions
    pattern = os.path.join(KEEPALIVE_DIR, "*.active")
    all_profiles = []
    for filepath in sorted(glob.glob(pattern)):
        filename = os.path.basename(filepath)
        profile = filename.replace(".active", "")
        session = f"{MA_PREFIX}-agent-002-{profile}"
        check = subprocess.run(
            ["tmux", "has-session", "-t", session],
            capture_output=True, timeout=5
        )
        if check.returncode == 0:
            all_profiles.append((profile, session))

    if all_profiles:
        # Pick one profile by round-robin
        idx = _usage_rr_idx % len(all_profiles)
        profile, session = all_profiles[idx]
        _usage_rr_idx = idx + 1

        ts = time.strftime("%H:%M:%S")
        print(f"{ts} KEEPALIVE usage scraping {profile} ({idx+1}/{len(all_profiles)})")

        bars, info = _scrape_usage_tab(session)

        # Write static info file
        if info:
            info_path = os.path.join(KEEPALIVE_DIR, f"info_{profile}.json")
            try:
                with open(info_path, "w") as f:
                    json.dump(info, f, indent=2)
            except Exception:
                pass

        usage_data = {
            "profile": profile,
            "bars": bars or [],
            "last_scan": int(time.time()),
        }
        out_path = os.path.join(KEEPALIVE_DIR, f"usage_{profile}.json")
        try:
            with open(out_path, "w") as f:
                json.dump(usage_data, f, indent=2)
        except Exception as e:
            print(f"{ts} KEEPALIVE usage write error {out_path}: {e}")

        if bars:
            bar_summary = " | ".join(f"{b['percent']}%" for b in bars)
            print(f"{ts} KEEPALIVE usage {profile}: {bar_summary}")
        else:
            print(f"{ts} KEEPALIVE usage {profile}: no bars")

    _last_fired["keepalive_usage_rr"] = usage_key


def scan_usage(r):
    """Scan Claude Code JSONL sessions and publish usage to Redis."""
    now = time.localtime()
    if not is_aligned(now.tm_min, now.tm_hour, USAGE_PERIOD):
        return

    key = fire_key(now.tm_hour, now.tm_min, USAGE_PERIOD)
    if _last_fired.get("usage_scan") == key:
        return

    cutoff = time.time() - 86400  # 24h

    global_totals = {
        "input_tokens": 0, "output_tokens": 0,
        "cache_read": 0, "cache_creation": 0,
        "total_sessions": 0, "total_messages": 0,
    }
    active_sessions = []

    try:
        project_dirs = glob.glob(CLAUDE_PROJECTS_DIR + "/*/")
    except Exception:
        project_dirs = []

    for project_dir in project_dirs:
        project_name = os.path.basename(project_dir.rstrip("/"))

        for jsonl_path in glob.glob(project_dir + "*.jsonl"):
            try:
                if os.path.getmtime(jsonl_path) < cutoff:
                    continue
            except OSError:
                continue

            session_file = os.path.basename(jsonl_path)
            session_id = session_file.replace(".jsonl", "")[:8]

            # Parse JSONL: deduplicate by message ID (streaming sends multiple chunks)
            msg_usage = {}  # msg_id -> {usage dict}
            model = ""
            last_activity = 0

            try:
                with open(jsonl_path, "r") as f:
                    for line in f:
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        msg = obj.get("message")
                        if not isinstance(msg, dict):
                            continue
                        usage = msg.get("usage")
                        if not usage:
                            continue
                        mid = msg.get("id", "")
                        if not mid:
                            continue
                        msg_usage[mid] = usage
                        if msg.get("model"):
                            model = msg["model"]
            except Exception:
                continue

            if not msg_usage:
                continue

            # Sum usage across deduplicated messages
            s_input = 0
            s_output = 0
            s_cache_read = 0
            s_cache_creation = 0

            for usage in msg_usage.values():
                s_input += usage.get("input_tokens", 0)
                s_output += usage.get("output_tokens", 0)
                s_cache_read += usage.get("cache_read_input_tokens", 0)
                s_cache_creation += usage.get("cache_creation_input_tokens", 0)

            msg_count = len(msg_usage)

            try:
                last_activity = int(os.path.getmtime(jsonl_path))
            except OSError:
                last_activity = 0

            # Publish per-session
            session_key = f"mi:usage:session:{session_id}"
            try:
                r.hset(session_key, mapping={
                    "project": project_name,
                    "model": model,
                    "input_tokens": s_input,
                    "output_tokens": s_output,
                    "cache_read": s_cache_read,
                    "cache_creation": s_cache_creation,
                    "messages": msg_count,
                    "last_activity": last_activity,
                })
                r.expire(session_key, 86400)
            except Exception:
                pass

            active_sessions.append(session_id)

            global_totals["input_tokens"] += s_input
            global_totals["output_tokens"] += s_output
            global_totals["cache_read"] += s_cache_read
            global_totals["cache_creation"] += s_cache_creation
            global_totals["total_sessions"] += 1
            global_totals["total_messages"] += msg_count

    # Publish global totals
    global_totals["last_scan"] = int(time.time())
    try:
        r.hset("mi:usage:global", mapping=global_totals)
        # Update active sessions set
        if active_sessions:
            r.delete("mi:usage:sessions")
            r.sadd("mi:usage:sessions", *active_sessions)
        else:
            r.delete("mi:usage:sessions")
    except Exception:
        pass

    _last_fired["usage_scan"] = key
    ts = time.strftime("%H:%M:%S")
    print(f"{ts} USAGE sessions={global_totals['total_sessions']} "
          f"messages={global_totals['total_messages']} "
          f"input={global_totals['input_tokens']} "
          f"output={global_totals['output_tokens']} "
          f"cache_read={global_totals['cache_read']} "
          f"cache_creation={global_totals['cache_creation']}")



def main():
    print(f"Starting scheduler (tick={TICK_INTERVAL}s, dir={CRONTAB_DIR})")
    print(f"Keepalive dir: {KEEPALIVE_DIR}")
    print(f"Redis: {REDIS_HOST}:{REDIS_PORT}, prefix: {MA_PREFIX}")

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    # Verify Redis connection
    try:
        r.ping()
        print("Redis connected OK")
    except Exception as e:
        print(f"WARNING: Redis not available yet: {e}")

    while True:
        try:
            scan_and_execute(r)
            scan_keepalive()
            scan_usage(r)
        except redis.ConnectionError as e:
            print(f"Redis connection lost: {e}, retrying...")
        except Exception as e:
            print(f"Unexpected error: {e}")

        time.sleep(TICK_INTERVAL)


if __name__ == "__main__":
    main()
