#!/usr/bin/env python3
"""
workflow_engine.py - Moteur générique de workflows déclaratifs YAML (F1)

Schéma d'un workflow (scripts/agent-bridge/workflows/*.yaml) :

  name: mon-workflow            # requis
  defaults:                     # optionnel
    from_agent: 100             # défaut 0
    timeout: 120                # défaut 120 s
  steps:                        # requis, liste non vide
    - name: analyse             # requis, unique
      agent: 200                # requis (sauf étape wait) — NNN ou NNN-NNN
      prompt: "..."             # requis (sauf wait)
      depends_on: [autre]       # optionnel — arêtes du DAG
      timeout: 180              # optionnel
      from_agent: 100           # optionnel
      on_success: notifier      # optionnel — déclenche une étape `manual: true`
      on_failure: abort         # abort (défaut) | continue | <étape manual>
      manual: true              # ne s'exécute que si déclenchée
    - name: pause
      wait: 30                  # étape d'attente (exclusive avec agent/prompt)

Templates de prompt : {etape} insère la réponse de l'étape, {etape:500}
la tronque à 500 caractères. Toute référence doit figurer dans depends_on.

Sémantique d'échec :
  - abort    : les étapes non lancées passent en "aborted", le run s'arrête.
  - continue : l'étape est "failed", ses dépendantes sont "skipped",
               le reste du graphe continue.
  - <étape>  : comme continue, et l'étape manual nommée est déclenchée.

Reprise : run_workflow(state_file=...) persiste l'état après chaque étape ;
relancer avec le même fichier ré-exécute uniquement les étapes non "done".

Le moteur est découplé du transport : `send(agent, prompt, from_agent,
timeout)` est injecté (orchestrator.send_and_wait en production).
"""

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait as futures_wait

from ids import is_valid_agent_id

_REF_RE = re.compile(r'\{([A-Za-z0-9_-]+)(?::(\d+))?\}')

_STEP_KEYS = {'name', 'agent', 'prompt', 'wait', 'depends_on', 'timeout',
              'from_agent', 'on_success', 'on_failure', 'manual'}


class WorkflowError(ValueError):
    """Définition de workflow invalide."""


def validate_workflow(wf):
    """Valide la définition et retourne {name: step} normalisé.

    Lève WorkflowError sur : champ manquant, nom dupliqué, ID agent
    invalide, depends_on/on_success/on_failure inconnu, référence de
    template hors depends_on, cycle dans le DAG.
    """
    if not isinstance(wf, dict) or not wf.get('name'):
        raise WorkflowError("workflow: champ 'name' requis")
    steps = wf.get('steps')
    if not isinstance(steps, list) or not steps:
        raise WorkflowError("workflow: liste 'steps' non vide requise")

    defaults = wf.get('defaults') or {}
    by_name = {}
    for s in steps:
        if not isinstance(s, dict) or not s.get('name'):
            raise WorkflowError("step: champ 'name' requis")
        name = s['name']
        if name in by_name:
            raise WorkflowError(f"step '{name}': nom dupliqué")
        unknown = set(s) - _STEP_KEYS
        if unknown:
            raise WorkflowError(f"step '{name}': champs inconnus {sorted(unknown)}")
        if 'wait' in s:
            if 'agent' in s or 'prompt' in s:
                raise WorkflowError(f"step '{name}': 'wait' est exclusif avec agent/prompt")
            if not isinstance(s['wait'], (int, float)) or s['wait'] < 0:
                raise WorkflowError(f"step '{name}': 'wait' doit être un nombre >= 0")
        else:
            if 'agent' not in s or 'prompt' not in s:
                raise WorkflowError(f"step '{name}': 'agent' et 'prompt' requis")
            if not is_valid_agent_id(s['agent']):
                raise WorkflowError(f"step '{name}': agent '{s['agent']}' invalide (NNN ou NNN-NNN)")
        deps = s.get('depends_on') or []
        if not isinstance(deps, list):
            raise WorkflowError(f"step '{name}': 'depends_on' doit être une liste")
        by_name[name] = {
            'name': name,
            'agent': s.get('agent'),
            'prompt': s.get('prompt'),
            'wait': s.get('wait'),
            'depends_on': deps,
            'timeout': s.get('timeout', defaults.get('timeout', 120)),
            'from_agent': s.get('from_agent', defaults.get('from_agent', 0)),
            'on_success': s.get('on_success'),
            'on_failure': s.get('on_failure', 'abort'),
            'manual': bool(s.get('manual', False)),
        }

    for step in by_name.values():
        name = step['name']
        for dep in step['depends_on']:
            if dep not in by_name:
                raise WorkflowError(f"step '{name}': depends_on '{dep}' inconnu")
        for field in ('on_success', 'on_failure'):
            target = step[field]
            if field == 'on_failure' and target in ('abort', 'continue'):
                continue
            if target is None:
                continue
            if target not in by_name:
                raise WorkflowError(f"step '{name}': {field} '{target}' inconnu")
            if not by_name[target]['manual']:
                raise WorkflowError(f"step '{name}': {field} '{target}' doit être manual: true")
        if step['prompt']:
            for ref, _trunc in _REF_RE.findall(step['prompt']):
                if ref in by_name and ref not in step['depends_on']:
                    raise WorkflowError(f"step '{name}': la référence {{{ref}}} doit être dans depends_on")

    # Détection de cycle (DFS sur depends_on)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in by_name}

    def visit(n, stack):
        color[n] = GRAY
        for dep in by_name[n]['depends_on']:
            if color[dep] == GRAY:
                raise WorkflowError(f"cycle détecté : {' -> '.join(stack + [n, dep])}")
            if color[dep] == WHITE:
                visit(dep, stack + [n])
        color[n] = BLACK

    for n in by_name:
        if color[n] == WHITE:
            visit(n, [])

    return by_name


def render_prompt(template, results):
    """Remplace {etape} / {etape:N} par la réponse (tronquée) de l'étape."""
    def sub(m):
        ref, trunc = m.group(1), m.group(2)
        entry = results.get(ref)
        if not entry or entry.get('status') != 'done':
            return m.group(0)
        response = entry.get('response', '')
        return response[:int(trunc)] if trunc else response
    return _REF_RE.sub(sub, template)


def _load_state(state_file, by_name):
    """Charge l'état d'un run précédent ; seules les étapes 'done' sont reprises."""
    results = {n: {'status': 'pending'} for n in by_name}
    triggered = set()
    if state_file and os.path.exists(state_file):
        with open(state_file) as f:
            saved = json.load(f)
        for name, entry in (saved.get('steps') or {}).items():
            if name in results and entry.get('status') == 'done':
                results[name] = entry
        triggered = {t for t in (saved.get('triggered') or []) if t in by_name}
    return results, triggered


def _save_state(state_file, wf_name, results, triggered):
    if not state_file:
        return
    os.makedirs(os.path.dirname(os.path.abspath(state_file)), exist_ok=True)
    with open(state_file, 'w') as f:
        json.dump({'workflow': wf_name, 'steps': results,
                   'triggered': sorted(triggered)}, f, indent=2)


def run_workflow(wf, send, state_file=None, max_workers=8, log=print):
    """Exécute le DAG ; retourne {name: {'status', 'response'|'error'}}.

    Statuts finaux : done | failed | skipped | aborted.
    """
    by_name = validate_workflow(wf)
    results, triggered = _load_state(state_file, by_name)
    aborted = False

    def runnable(name):
        step = by_name[name]
        if results[name]['status'] != 'pending':
            return False
        if step['manual'] and name not in triggered:
            return False
        return all(results[d]['status'] == 'done' for d in step['depends_on'])

    def blocked(name):
        """Une dépendance a définitivement échoué → étape skipped."""
        return any(results[d]['status'] in ('failed', 'skipped', 'aborted')
                   for d in by_name[name]['depends_on'])

    def execute(step):
        if step['wait'] is not None:
            time.sleep(step['wait'])
            return ''
        prompt = render_prompt(step['prompt'], results)
        return send(step['agent'], prompt,
                    from_agent=step['from_agent'], timeout=step['timeout'])

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        while True:
            # Propager les échecs : dépendantes d'une étape failed/skipped
            for name in by_name:
                if results[name]['status'] == 'pending' and blocked(name):
                    results[name] = {'status': 'skipped'}
                    log(f"[wf] {name}: skipped (dépendance en échec)")

            if not aborted:
                for name in by_name:
                    if runnable(name):
                        results[name] = {'status': 'running'}
                        log(f"[wf] {name}: lancement (agent {by_name[name]['agent'] or 'wait'})")
                        futures[pool.submit(execute, by_name[name])] = name

            if not futures:
                break

            done_set, _ = futures_wait(futures, return_when=FIRST_COMPLETED)
            for fut in done_set:
                name = futures.pop(fut)
                step = by_name[name]
                try:
                    response = fut.result()
                    results[name] = {'status': 'done', 'response': response}
                    log(f"[wf] {name}: done")
                    if step['on_success']:
                        triggered.add(step['on_success'])
                except Exception as exc:
                    results[name] = {'status': 'failed', 'error': str(exc)}
                    log(f"[wf] {name}: failed ({exc})")
                    policy = step['on_failure']
                    if policy == 'abort':
                        aborted = True
                    elif policy != 'continue':
                        triggered.add(policy)
                _save_state(state_file, wf['name'], results, triggered)

        if aborted:
            for name in by_name:
                if results[name]['status'] == 'pending':
                    results[name] = {'status': 'aborted'}
            _save_state(state_file, wf['name'], results, triggered)

    # Étapes manual jamais déclenchées : neutres (restées pending)
    return results
