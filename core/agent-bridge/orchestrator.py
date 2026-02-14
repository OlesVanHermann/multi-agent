#!/usr/bin/env python3
"""
orchestrator.py - Orchestre des workflows multi-agents via Redis Streams
Usage: python orchestrator.py <workflow>

Workflows:
  seq     - Séquentiel: Explorer -> Developer -> Tester
  par     - Parallèle: plusieurs workers simultanément
  review  - Code review: Developer -> Reviewer -> Developer
"""

import redis
import time
import sys
import os

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
MA_PREFIX = os.environ.get("MA_PREFIX", "ma")

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def send_and_wait(to_agent, prompt, from_agent=0, timeout=120):
    """Envoie un prompt et attend la réponse"""

    # Marquer le dernier message avant d'envoyer
    outbox = f"{MA_PREFIX}:agent:{to_agent}:outbox"
    last_id = '$'

    # Envoyer
    r.xadd(f"{MA_PREFIX}:agent:{to_agent}:inbox", {
        'prompt': prompt,
        'from_agent': from_agent,
        'timestamp': int(time.time())
    })
    print(f"[{from_agent}] -> [{to_agent}]: {prompt[:60]}...")

    # Attendre la réponse
    start = time.time()
    while time.time() - start < timeout:
        result = r.xread({outbox: last_id}, block=5000, count=1)
        if result:
            _, messages = result[0]
            for msg_id, data in messages:
                last_id = msg_id
                # Vérifier que c'est une réponse à notre requête
                if 'response' in data:
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
        })
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
                agent_id = stream.split(':')[2]  # ma:agent:XXX:outbox
                for msg_id, data in messages:
                    streams[stream] = msg_id
                    if 'response' in data and agent_id not in responses:
                        responses[agent_id] = data['response']
                        print(f"Got response from {agent_id}")

    return responses


# === Workflows ===

def workflow_sequential():
    """Workflow séquentiel: Explorer -> Developer -> Tester"""
    print("\n=== Workflow Sequentiel ===\n")

    # 1. Explorer analyse
    analysis = send_and_wait(200,
        "Liste tous les fichiers .py dans le dossier courant",
        from_agent=100)

    # 2. Developer code
    code = send_and_wait(300,
        f"Base sur cette liste:\n{analysis[:500]}\n\nCree un fichier index.py qui importe tous ces modules",
        from_agent=100)

    # 3. Tester valide
    result = send_and_wait(500,
        f"Verifie ce code:\n{code[:500]}\n\nY a-t-il des erreurs?",
        from_agent=100)

    print("\n=== Resultat final ===")
    print(result[:500])


def workflow_parallel():
    """Workflow parallèle: plusieurs workers en même temps"""
    print("\n=== Workflow Parallele ===\n")

    workers = [300, 301, 302]
    tasks = [
        "Cree une fonction add(a, b) qui additionne deux nombres",
        "Cree une fonction multiply(a, b) qui multiplie deux nombres",
        "Cree une fonction divide(a, b) qui divise deux nombres avec gestion d'erreur",
    ]

    # Envoyer toutes les tâches
    for worker, task in zip(workers, tasks):
        r.xadd(f"{MA_PREFIX}:agent:{worker}:inbox", {
            'prompt': task,
            'from_agent': 100,
            'timestamp': int(time.time())
        })
        print(f"Assigned to {worker}: {task[:40]}...")

    # Collecter les résultats
    responses = collect_responses(workers, timeout=120)

    print("\n=== Resultats ===")
    for agent, response in responses.items():
        print(f"\nAgent {agent}:")
        print(response[:300])


def workflow_review():
    """Workflow review: Developer code, Reviewer review"""
    print("\n=== Workflow Code Review ===\n")

    # Developer écrit du code
    code = send_and_wait(300,
        "Ecris une fonction Python fibonacci(n) recursive",
        from_agent=100)

    # Reviewer analyse
    review = send_and_wait(301,
        f"Review ce code et suggere des ameliorations:\n```python\n{code}\n```",
        from_agent=100)

    # Developer améliore
    improved = send_and_wait(300,
        f"Ameliore ton code base sur ce review:\n{review}",
        from_agent=100)

    print("\n=== Code ameliore ===")
    print(improved[:500])


def workflow_pipeline():
    """Workflow pipeline complet: Explorer -> Master -> Devs -> Merge -> Test"""
    print("\n=== Workflow Pipeline Complet ===\n")

    # 1. Explorer crée une spec
    print("1. Explorer analyse...")
    spec = send_and_wait(200,
        "Analyse le dossier project/ et cree une spec pour ajouter une fonction de validation d'email",
        from_agent=100, timeout=180)

    # 2. Master dispatch aux devs
    print("\n2. Master dispatch...")
    send_and_wait(100,
        f"Dispatch cette spec aux developers:\n{spec[:1000]}",
        from_agent=0, timeout=60)

    # 3. Attendre que les devs finissent
    print("\n3. Attente des developers...")
    time.sleep(30)  # Simplification - en vrai on attendrait les réponses

    # 4. Merge
    print("\n4. Merge...")
    merge_result = send_and_wait(400,
        "Cherry-pick toutes les branches dev-* vers la branche dev",
        from_agent=100, timeout=120)

    # 5. Test
    print("\n5. Test...")
    test_result = send_and_wait(500,
        "Execute tous les tests et rapport le resultat",
        from_agent=100, timeout=180)

    print("\n=== Pipeline termine ===")
    print(f"Merge: {merge_result[:200]}")
    print(f"Tests: {test_result[:200]}")


if __name__ == "__main__":
    workflows = {
        'seq': workflow_sequential,
        'par': workflow_parallel,
        'review': workflow_review,
        'pipeline': workflow_pipeline,
    }

    if len(sys.argv) < 2 or sys.argv[1] not in workflows:
        print(f"Usage: python {sys.argv[0]} <workflow>")
        print(f"Workflows: {list(workflows.keys())}")
        sys.exit(1)

    try:
        r.ping()
    except redis.ConnectionError:
        print(f"Error: Cannot connect to Redis at {REDIS_HOST}:{REDIS_PORT}")
        sys.exit(1)

    workflows[sys.argv[1]]()
