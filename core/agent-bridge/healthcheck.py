#!/usr/bin/env python3
"""
healthcheck.py - Vérifie l'état de tous les agents
Usage: python healthcheck.py [--watch]

Options:
  --watch    Mode continu (refresh toutes les 2s)
"""

import redis
import time
import sys
import os
import argparse

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
MA_PREFIX = os.environ.get("MA_PREFIX", "ma")

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def check_agents():
    """Liste et vérifie tous les agents"""
    agents = {}

    for key in r.keys(f"{MA_PREFIX}:agent:*"):
        # Filtrer pour avoir seulement ma:agent:XXX (pas inbox/outbox)
        parts = key.split(':')
        if len(parts) == 3:  # ma:agent:XXX
            agent_id = parts[2]
            data = r.hgetall(key)

            if not data:
                continue

            last_seen = int(data.get('last_seen', 0))
            age = time.time() - last_seen

            agents[agent_id] = {
                'status': data.get('status', 'unknown'),
                'queue': data.get('queue_size', '?'),
                'task_from': data.get('current_task_from', ''),
                'headless': data.get('headless', 'false'),
                'session': data.get('session_id', '')[:8],
                'tasks': data.get('tasks_completed', '0'),
                'age_seconds': int(age),
                'healthy': age < 30  # Moins de 30s depuis dernier heartbeat
            }

    return agents


def print_status(agents, clear=False):
    """Affiche le status des agents"""
    if clear:
        print("\033[2J\033[H", end='')  # Clear screen

    print("Multi-Agent Health Check")
    print("=" * 80)
    print(f"{'ID':<6} {'Status':<10} {'Queue':<6} {'Tasks':<6} {'Session':<10} {'Age':<10} {'Health'}")
    print("-" * 80)

    for agent_id, info in sorted(agents.items(), key=lambda x: x[0]):
        status = info['status']
        # Couleurs
        if status == 'idle':
            status_str = f"\033[32m{status:<10}\033[0m"  # vert
        elif status == 'busy':
            status_str = f"\033[33m{status:<10}\033[0m"  # jaune
        else:
            status_str = f"\033[31m{status:<10}\033[0m"  # rouge

        health = "\033[32mOK\033[0m" if info['healthy'] else "\033[31mSTALE\033[0m"
        age = f"{info['age_seconds']}s"

        print(f"{agent_id:<6} {status_str} {info['queue']:<6} {info['tasks']:<6} {info['session']:<10} {age:<10} {health}")

    print("-" * 80)

    healthy_count = sum(1 for i in agents.values() if i['healthy'])
    total = len(agents)
    print(f"Total: {total} agents, {healthy_count} healthy, {total - healthy_count} stale")

    unhealthy = [a for a, i in agents.items() if not i['healthy']]
    if unhealthy:
        print(f"\n\033[33mWarning:\033[0m Stale agents: {', '.join(sorted(unhealthy))}")

    return len(unhealthy) == 0


def check_streams():
    """Vérifie les streams Redis"""
    print("\n" + "=" * 80)
    print("Redis Streams Status")
    print("-" * 80)

    for key in sorted(r.keys(f"{MA_PREFIX}:agent:*:inbox") + r.keys(f"{MA_PREFIX}:agent:*:outbox")):
        try:
            info = r.xinfo_stream(key)
            length = info.get('length', 0)
            last_id = info.get('last-generated-id', '-')
            print(f"  {key}: {length} messages, last={last_id}")
        except redis.ResponseError:
            pass  # Stream doesn't exist yet


def main():
    parser = argparse.ArgumentParser(description='Multi-Agent Health Check')
    parser.add_argument('--watch', action='store_true', help='Continuous monitoring mode')
    parser.add_argument('--streams', action='store_true', help='Show stream stats')
    parser.add_argument('--interval', type=int, default=2, help='Refresh interval in watch mode')
    args = parser.parse_args()

    try:
        r.ping()
    except redis.ConnectionError:
        print(f"\033[31mError:\033[0m Cannot connect to Redis at {REDIS_HOST}:{REDIS_PORT}")
        return 1

    if args.watch:
        print("Watching agents (Ctrl+C to quit)...")
        try:
            while True:
                agents = check_agents()
                print_status(agents, clear=True)
                if args.streams:
                    check_streams()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
            return 0
    else:
        agents = check_agents()
        if not agents:
            print("No agents found in Redis")
            return 0

        all_healthy = print_status(agents)
        if args.streams:
            check_streams()

        return 0 if all_healthy else 1


if __name__ == "__main__":
    sys.exit(main())
