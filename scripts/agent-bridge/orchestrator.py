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
IO_STREAM_MAXLEN = int(os.environ.get("IO_STREAM_MAXLEN", 10000))

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD or None, decode_responses=True)


def send_and_wait(to_agent, prompt, from_agent=0, timeout=120,
                  verify_cmd=None, task_id=None, project_dir=None):
    """Envoie un prompt et attend SA réponse (corrélée par correlation_id, F2).

    V3/C1 : verify_cmd optionnel — porté sur le message inbox, le bridge ne
    publie la réponse qu'après verify vert (ou [VERIFY_FAILED] si budget
    épuisé/hacking, qui lève RuntimeError → on_failure du workflow).
    Sans verify_cmd : comportement v2 inchangé."""

    # Marquer le dernier message avant d'envoyer
    outbox = f"agent:{to_agent}:outbox"
    last_id = '$'
    correlation_id = str(uuid.uuid4())

    # Envoyer
    fields = {
        'prompt': prompt,
        'from_agent': from_agent,
        'correlation_id': correlation_id,
        'timestamp': int(time.time())
    }
    if verify_cmd:
        fields['verify_cmd'] = verify_cmd
        fields['task_id'] = task_id or correlation_id[:8]
    if project_dir:
        fields['project_dir'] = project_dir
    r.xadd(f"agent:{to_agent}:inbox", fields,
           maxlen=IO_STREAM_MAXLEN, approximate=True)
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
                if response.startswith('[VERIFY_FAILED]'):
                    raise RuntimeError(response[:500])
                print(f"[{to_agent}] -> [{from_agent}]: {response[:80]}...")
                return response

    raise TimeoutError(f"No response from agent {to_agent} after {timeout}s")


def broadcast(agents, prompt, from_agent=0):
    """Envoie le même prompt à plusieurs agents"""
    for agent in agents:
        r.xadd(f"agent:{agent}:inbox", {
            'prompt': prompt,
            'from_agent': from_agent,
            'timestamp': int(time.time())
        }, maxlen=IO_STREAM_MAXLEN, approximate=True)
    print(f"Broadcasted to {agents}: {prompt[:50]}...")


def collect_responses(agents, timeout=60):
    """Collecte les réponses de plusieurs agents"""
    streams = {f"agent:{a}:outbox": '$' for a in agents}
    responses = {}
    start = time.time()

    while len(responses) < len(agents) and time.time() - start < timeout:
        result = r.xread(streams, block=2000, count=10)
        if result:
            for stream, messages in result:
                agent_id = stream.split(':')[1]  # agent:XXX:outbox
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


def load_workflow(spec, variables=None):
    """Charge un workflow par nom court (workflows/<nom>.yaml) ou chemin .yaml.

    variables : dict de substitutions textuelles {{clef}} → valeur, appliquées
    AVANT le parse YAML (utilisé par bench/run.sh via --var)."""
    if spec.endswith(('.yaml', '.yml')):
        path = spec
    else:
        path = os.path.join(WORKFLOWS_DIR, f"{spec}.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path) as f:
        text = f.read()
    for key, value in (variables or {}).items():
        text = text.replace("{{" + key + "}}", value)
    return yaml.safe_load(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Exécute un workflow déclaratif YAML via Redis Streams")
    parser.add_argument('workflow',
                        help=f"nom court ({', '.join(list_workflows())}) ou chemin .yaml")
    parser.add_argument('--state', metavar='FICHIER',
                        help="fichier d'état JSON (persistance + reprise)")
    parser.add_argument('--variant', default='baseline',
                        help="variante topologique déclarée (défaut: baseline)")
    parser.add_argument('--var', metavar='CLEF=VALEUR', action='append',
                        default=[],
                        help="substitution {{clef}} dans le YAML (répétable)")
    args = parser.parse_args()

    variables = {}
    for item in args.var:
        if '=' not in item:
            print(f"Error: --var attend CLEF=VALEUR, reçu: {item}")
            sys.exit(1)
        key, _, value = item.partition('=')
        variables[key] = value

    try:
        wf = workflow_engine.select_variant(
            load_workflow(args.workflow, variables), args.variant)
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
