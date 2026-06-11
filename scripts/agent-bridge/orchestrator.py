#!/usr/bin/env python3
"""
orchestrator.py - Orchestre des workflows multi-agents via Redis Streams
Usage: python orchestrator.py <workflow|fichier.yaml> [--state FICHIER]

F1 : les workflows sont déclaratifs (workflows/*.yaml) et exécutés par le
moteur générique workflow_engine.py (DAG, parallélisme, on_failure, reprise).
Un nom court (seq, par, review, pipeline) charge workflows/<nom>.yaml ;
un chemin .yaml charge ce fichier. --state FICHIER persiste l'état après
chaque étape et permet la reprise (les étapes 'done' ne sont pas rejouées).
"""

import argparse
import glob
import redis
import time
import sys
import os
import uuid

import yaml

import workflow_engine

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
MA_PREFIX = os.environ.get("MA_PREFIX", "A")
IO_STREAM_MAXLEN = int(os.environ.get("IO_STREAM_MAXLEN", 10000))

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD or None, decode_responses=True)


def send_and_wait(to_agent, prompt, from_agent=0, timeout=120):
    """Envoie un prompt et attend SA réponse (corrélée par correlation_id, F2)"""

    # Marquer le dernier message avant d'envoyer
    outbox = f"{MA_PREFIX}:agent:{to_agent}:outbox"
    last_id = '$'
    correlation_id = str(uuid.uuid4())

    # Envoyer
    r.xadd(f"{MA_PREFIX}:agent:{to_agent}:inbox", {
        'prompt': prompt,
        'from_agent': from_agent,
        'correlation_id': correlation_id,
        'timestamp': int(time.time())
    }, maxlen=IO_STREAM_MAXLEN, approximate=True)
    print(f"[{from_agent}] -> [{to_agent}]: {prompt[:60]}...")

    # Attendre la réponse
    start = time.time()
    while time.time() - start < timeout:
        result = r.xread({outbox: last_id}, block=5000, count=1)
        if result:
            _, messages = result[0]
            for msg_id, data in messages:
                last_id = msg_id
                if 'response' not in data:
                    continue
                # F2: ne retenir que la réponse à NOTRE requête.
                # Compat : un bridge ancien n'écho pas correlation_id → accepter.
                resp_corr = data.get('correlation_id', '')
                if resp_corr and resp_corr != correlation_id:
                    continue
                response = data['response']
                print(f"[{to_agent}] -> [{from_agent}]: {response[:80]}...")
                return response

    raise TimeoutError(f"No response from agent {to_agent} after {timeout}s")


def broadcast(agents, prompt, from_agent=0):
    """Envoie le même prompt à plusieurs agents"""
    for agent in agents:
        r.xadd(f"{MA_PREFIX}:agent:{agent}:inbox", {
            'prompt': prompt,
            'from_agent': from_agent,
            'timestamp': int(time.time())
        }, maxlen=IO_STREAM_MAXLEN, approximate=True)
    print(f"Broadcasted to {agents}: {prompt[:50]}...")


def collect_responses(agents, timeout=60):
    """Collecte les réponses de plusieurs agents"""
    streams = {f"{MA_PREFIX}:agent:{a}:outbox": '$' for a in agents}
    responses = {}
    start = time.time()

    while len(responses) < len(agents) and time.time() - start < timeout:
        result = r.xread(streams, block=2000, count=10)
        if result:
            for stream, messages in result:
                agent_id = stream.split(':')[2]  # A:agent:XXX:outbox
                for msg_id, data in messages:
                    streams[stream] = msg_id
                    if 'response' in data and agent_id not in responses:
                        responses[agent_id] = data['response']
                        print(f"Got response from {agent_id}")

    return responses


# === Workflows déclaratifs (F1) ===

WORKFLOWS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'workflows')


def list_workflows():
    """Noms courts disponibles dans workflows/*.yaml"""
    return sorted(os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(WORKFLOWS_DIR, '*.yaml')))


def load_workflow(spec):
    """Charge un workflow par nom court (workflows/<nom>.yaml) ou chemin .yaml"""
    if spec.endswith(('.yaml', '.yml')):
        path = spec
    else:
        path = os.path.join(WORKFLOWS_DIR, f"{spec}.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path) as f:
        return yaml.safe_load(f)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Exécute un workflow déclaratif YAML via Redis Streams")
    parser.add_argument('workflow',
                        help=f"nom court ({', '.join(list_workflows())}) ou chemin .yaml")
    parser.add_argument('--state', metavar='FICHIER',
                        help="fichier d'état JSON (persistance + reprise)")
    args = parser.parse_args()

    try:
        wf = load_workflow(args.workflow)
        workflow_engine.validate_workflow(wf)
    except FileNotFoundError as exc:
        print(f"Error: workflow introuvable: {exc}")
        print(f"Workflows: {list_workflows()}")
        sys.exit(1)
    except workflow_engine.WorkflowError as exc:
        print(f"Error: workflow invalide: {exc}")
        sys.exit(1)

    try:
        r.ping()
    except redis.ConnectionError:
        print(f"Error: Cannot connect to Redis at {REDIS_HOST}:{REDIS_PORT}")
        sys.exit(1)

    print(f"\n=== Workflow {wf['name']} ===\n")
    results = workflow_engine.run_workflow(wf, send=send_and_wait, state_file=args.state)

    print(f"\n=== Resultats ({wf['name']}) ===")
    failed = False
    for name, entry in results.items():
        status = entry['status']
        if status in ('failed', 'aborted', 'skipped'):
            failed = True
        detail = entry.get('response', entry.get('error', ''))
        print(f"\n[{status}] {name}")
        if detail:
            print(str(detail)[:300])
    sys.exit(1 if failed else 0)
