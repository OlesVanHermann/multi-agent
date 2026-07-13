"""
Tests du moteur de workflows déclaratifs YAML (F1).

Couverture : validation du schéma (champs requis, DAG, cycles, templates),
exécution (séquentiel, parallèle, templating), gestion d'échec
(abort/continue/handler), déclencheurs on_success, reprise via state_file,
et validité des workflows YAML livrés (équivalents seq/par/review/pipeline).
"""
import glob
import json
import os
import threading

import pytest
import yaml

from workflow_engine import (
    WorkflowError, validate_workflow, render_prompt, run_workflow,
)


def make_wf(steps, **kw):
    wf = {'name': 'test', 'steps': steps}
    wf.update(kw)
    return wf


def quiet(*a, **kw):
    pass


# === Validation ===

class TestValidation:

    def test_missing_name(self):
        with pytest.raises(WorkflowError, match="'name' requis"):
            validate_workflow({'steps': [{'name': 'a', 'agent': 300, 'prompt': 'x'}]})

    def test_missing_steps(self):
        with pytest.raises(WorkflowError, match="'steps'"):
            validate_workflow({'name': 'x'})

    def test_step_requires_agent_and_prompt(self):
        with pytest.raises(WorkflowError, match="'agent' et 'prompt' requis"):
            validate_workflow(make_wf([{'name': 'a', 'agent': 300}]))

    def test_invalid_agent_id(self):
        with pytest.raises(WorkflowError, match="invalide"):
            validate_workflow(make_wf([{'name': 'a', 'agent': '30', 'prompt': 'x'}]))

    def test_compound_agent_id_valid(self):
        by_name = validate_workflow(make_wf([{'name': 'a', 'agent': '341-141', 'prompt': 'x'}]))
        assert by_name['a']['agent'] == '341-141'

    def test_duplicate_step_name(self):
        with pytest.raises(WorkflowError, match="dupliqué"):
            validate_workflow(make_wf([
                {'name': 'a', 'agent': 300, 'prompt': 'x'},
                {'name': 'a', 'agent': 301, 'prompt': 'y'},
            ]))

    def test_unknown_dependency(self):
        with pytest.raises(WorkflowError, match="depends_on 'ghost' inconnu"):
            validate_workflow(make_wf([
                {'name': 'a', 'agent': 300, 'prompt': 'x', 'depends_on': ['ghost']},
            ]))

    def test_cycle_detected(self):
        with pytest.raises(WorkflowError, match="cycle"):
            validate_workflow(make_wf([
                {'name': 'a', 'agent': 300, 'prompt': 'x', 'depends_on': ['b']},
                {'name': 'b', 'agent': 301, 'prompt': 'y', 'depends_on': ['a']},
            ]))

    def test_template_ref_must_be_dependency(self):
        with pytest.raises(WorkflowError, match="doit être dans depends_on"):
            validate_workflow(make_wf([
                {'name': 'a', 'agent': 300, 'prompt': 'x'},
                {'name': 'b', 'agent': 301, 'prompt': 'voir {a}'},
            ]))

    def test_on_failure_target_must_be_manual(self):
        with pytest.raises(WorkflowError, match="manual"):
            validate_workflow(make_wf([
                {'name': 'a', 'agent': 300, 'prompt': 'x', 'on_failure': 'b'},
                {'name': 'b', 'agent': 301, 'prompt': 'y'},
            ]))

    def test_wait_exclusive_with_agent(self):
        with pytest.raises(WorkflowError, match="exclusif"):
            validate_workflow(make_wf([{'name': 'a', 'wait': 5, 'agent': 300, 'prompt': 'x'}]))

    def test_defaults_applied(self):
        by_name = validate_workflow(make_wf(
            [{'name': 'a', 'agent': 300, 'prompt': 'x'}],
            defaults={'from_agent': 100, 'timeout': 42}))
        assert by_name['a']['from_agent'] == 100
        assert by_name['a']['timeout'] == 42


# === Templating ===

class TestRenderPrompt:

    def test_full_and_truncated(self):
        results = {'a': {'status': 'done', 'response': 'ABCDEFGH'}}
        assert render_prompt('voir {a}', results) == 'voir ABCDEFGH'
        assert render_prompt('voir {a:3}', results) == 'voir ABC'

    def test_unknown_ref_left_intact(self):
        assert render_prompt('code {x}', {}) == 'code {x}'


# === Exécution ===

class TestExecution:

    def test_sequential_end_to_end(self):
        calls = []

        def send(agent, prompt, from_agent=0, timeout=120):
            calls.append((agent, prompt, from_agent, timeout))
            return f"resp-{agent}"

        wf = make_wf([
            {'name': 'analyse', 'agent': 200, 'prompt': 'analyse'},
            {'name': 'code', 'agent': 300, 'prompt': 'base: {analyse:4}',
             'depends_on': ['analyse']},
        ], defaults={'from_agent': 100})

        results = run_workflow(wf, send=send, log=quiet)
        assert results['analyse'] == {'status': 'done', 'response': 'resp-200'}
        assert results['code']['status'] == 'done'
        # ordre + templating (resp-200 tronqué à 4)
        assert calls[0][0] == 200
        assert calls[1][1] == 'base: resp'
        assert all(c[2] == 100 for c in calls)

    def test_parallel_independent_steps(self):
        barrier = threading.Barrier(2, timeout=5)

        def send(agent, prompt, from_agent=0, timeout=120):
            barrier.wait()  # ne passe que si les 2 étapes tournent en même temps
            return 'ok'

        wf = make_wf([
            {'name': 'a', 'agent': 300, 'prompt': 'x'},
            {'name': 'b', 'agent': 301, 'prompt': 'y'},
        ])
        results = run_workflow(wf, send=send, log=quiet)
        assert results['a']['status'] == 'done'
        assert results['b']['status'] == 'done'

    def test_wait_step(self):
        wf = make_wf([
            {'name': 'pause', 'wait': 0},
            {'name': 'a', 'agent': 300, 'prompt': 'x', 'depends_on': ['pause']},
        ])
        results = run_workflow(wf, send=lambda *a, **k: 'ok', log=quiet)
        assert results['pause']['status'] == 'done'
        assert results['a']['status'] == 'done'


# === Gestion d'échec ===

class TestFailureHandling:

    def test_failed_dependency_blocks_dependents(self):
        def send(agent, prompt, from_agent=0, timeout=120):
            if agent == 200:
                raise TimeoutError('no response')
            return 'ok'

        wf = make_wf([
            {'name': 'a', 'agent': 200, 'prompt': 'x', 'on_failure': 'continue'},
            {'name': 'b', 'agent': 300, 'prompt': 'y', 'depends_on': ['a']},
            {'name': 'c', 'agent': 301, 'prompt': 'z'},
        ])
        results = run_workflow(wf, send=send, log=quiet)
        assert results['a']['status'] == 'failed'
        assert results['b']['status'] == 'skipped'   # dépendance non satisfaite
        assert results['c']['status'] == 'done'      # indépendant, continue

    def test_abort_stops_pending_steps(self):
        import time as _time

        def send(agent, prompt, from_agent=0, timeout=120):
            if agent == 200:
                raise TimeoutError('no response')
            _time.sleep(0.2)  # b finit après l'échec de a → abort déjà actif
            return 'ok'

        wf = make_wf([
            {'name': 'a', 'agent': 200, 'prompt': 'x'},  # on_failure: abort (défaut)
            {'name': 'b', 'agent': 300, 'prompt': 'y'},
            {'name': 'c', 'agent': 301, 'prompt': 'z', 'depends_on': ['b']},
        ])
        results = run_workflow(wf, send=send, log=quiet)
        assert results['a']['status'] == 'failed'
        # c n'a jamais été lancé : abort l'empêche d'être soumis
        assert results['c']['status'] in ('aborted', 'skipped')

    def test_on_failure_triggers_handler(self):
        called = []

        def send(agent, prompt, from_agent=0, timeout=120):
            called.append(agent)
            if agent == 200:
                raise TimeoutError('boom')
            return 'ok'

        wf = make_wf([
            {'name': 'a', 'agent': 200, 'prompt': 'x', 'on_failure': 'cleanup'},
            {'name': 'cleanup', 'agent': 600, 'prompt': 'nettoie', 'manual': True},
        ])
        results = run_workflow(wf, send=send, log=quiet)
        assert results['a']['status'] == 'failed'
        assert results['cleanup']['status'] == 'done'
        assert 600 in called

    def test_on_success_triggers_step(self):
        wf = make_wf([
            {'name': 'a', 'agent': 300, 'prompt': 'x', 'on_success': 'notify'},
            {'name': 'notify', 'agent': 700, 'prompt': 'publie', 'manual': True},
        ])
        results = run_workflow(wf, send=lambda *a, **k: 'ok', log=quiet)
        assert results['a']['status'] == 'done'
        assert results['notify']['status'] == 'done'

    def test_manual_step_not_triggered_stays_pending(self):
        wf = make_wf([
            {'name': 'a', 'agent': 300, 'prompt': 'x'},
            {'name': 'cleanup', 'agent': 600, 'prompt': 'y', 'manual': True},
        ])
        results = run_workflow(wf, send=lambda *a, **k: 'ok', log=quiet)
        assert results['a']['status'] == 'done'
        assert results['cleanup']['status'] == 'pending'


# === Reprise (state_file) ===

class TestResume:

    def test_resume_skips_done_steps(self, tmp_path):
        state = str(tmp_path / 'state.json')
        wf = make_wf([
            {'name': 'a', 'agent': 200, 'prompt': 'x'},
            {'name': 'b', 'agent': 300, 'prompt': 'base {a}', 'depends_on': ['a'],
             'on_failure': 'continue'},
        ])

        # 1er run : a réussit, b échoue
        def send_fail_b(agent, prompt, from_agent=0, timeout=120):
            if agent == 300:
                raise TimeoutError('down')
            return 'resp-a'

        results = run_workflow(wf, send=send_fail_b, state_file=state, log=quiet)
        assert results['a']['status'] == 'done'
        assert results['b']['status'] == 'failed'
        assert json.load(open(state))['steps']['a']['status'] == 'done'

        # 2e run : a ne doit PAS être rejoué, b est rejoué avec le template
        # rendu depuis l'état repris
        replayed = []

        def send_ok(agent, prompt, from_agent=0, timeout=120):
            replayed.append((agent, prompt))
            assert agent != 200, "l'étape 'done' ne doit pas être rejouée"
            return 'resp-b'

        results = run_workflow(wf, send=send_ok, state_file=state, log=quiet)
        assert results['a'] == {'status': 'done', 'response': 'resp-a'}
        assert results['b']['status'] == 'done'
        assert replayed == [(300, 'base resp-a')]


# === Workflows YAML livrés ===

class TestShippedWorkflows:

    WORKFLOWS_DIR = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..',
        'scripts', 'agent-bridge', 'workflows')

    def _load(self, name):
        with open(os.path.join(self.WORKFLOWS_DIR, f'{name}.yaml')) as f:
            return yaml.safe_load(f)

    def test_all_shipped_workflows_are_valid(self):
        paths = glob.glob(os.path.join(self.WORKFLOWS_DIR, '*.yaml'))
        assert len(paths) >= 4
        for path in paths:
            with open(path) as f:
                validate_workflow(yaml.safe_load(f))

    def test_seq_equivalent_to_legacy(self):
        """seq.yaml reproduit workflow_sequential : 200 -> 300 -> 500, from 100"""
        by_name = validate_workflow(self._load('seq'))
        assert [by_name[n]['agent'] for n in ('analyse', 'code', 'test')] == [200, 300, 500]
        assert by_name['code']['depends_on'] == ['analyse']
        assert by_name['test']['depends_on'] == ['code']
        assert all(s['from_agent'] == 100 for s in by_name.values())
        assert '{analyse:500}' in by_name['code']['prompt']

    def test_par_equivalent_to_legacy(self):
        """par.yaml reproduit workflow_parallel : 300/301/302 sans dépendances"""
        by_name = validate_workflow(self._load('par'))
        assert sorted(s['agent'] for s in by_name.values()) == [300, 301, 302]
        assert all(s['depends_on'] == [] for s in by_name.values())

    def test_review_equivalent_to_legacy(self):
        """review.yaml reproduit workflow_review : 300 -> 301 -> 300"""
        by_name = validate_workflow(self._load('review'))
        assert [by_name[n]['agent'] for n in ('code', 'review', 'improve')] == [300, 301, 300]
        assert '{code}' in by_name['review']['prompt']
        assert '{review}' in by_name['improve']['prompt']

    def test_pipeline_equivalent_to_legacy(self):
        """pipeline.yaml : 200 -> 100 -> wait 30 -> 400 -> 500"""
        by_name = validate_workflow(self._load('pipeline'))
        assert by_name['spec']['agent'] == 200
        assert by_name['dispatch']['from_agent'] == 0
        assert by_name['attente-devs']['wait'] == 30
        assert by_name['test']['depends_on'] == ['merge']


# === V3/C1 : clé verify ===

class TestVerifyKey:

    def test_verify_accepted_and_normalized(self):
        by_name = validate_workflow(make_wf(
            [{'name': 'a', 'agent': 300, 'prompt': 'x', 'verify': 'pytest -q'}]))
        assert by_name['a']['verify'] == 'pytest -q'

    def test_verify_default_none(self):
        by_name = validate_workflow(make_wf(
            [{'name': 'a', 'agent': 300, 'prompt': 'x'}]))
        assert by_name['a']['verify'] is None

    def test_wait_exclusive_with_verify(self):
        with pytest.raises(WorkflowError, match="exclusif"):
            validate_workflow(make_wf(
                [{'name': 'a', 'wait': 5, 'verify': 'pytest -q'}]))

    def test_verify_step_passes_kwargs_to_send(self):
        calls = []

        def send(agent, prompt, from_agent=0, timeout=120, **kw):
            calls.append((agent, kw))
            return 'ok'

        wf = make_wf([
            {'name': 'libre', 'agent': 300, 'prompt': 'sans verify'},
            {'name': 'prouve', 'agent': 301, 'prompt': 'avec verify',
             'verify': 'pytest -q', 'depends_on': ['libre']},
        ])
        results = run_workflow(wf, send=send, log=quiet)
        assert results['prouve']['status'] == 'done'
        by_agent = dict(calls)
        assert by_agent[300] == {}  # étape sans verify : aucun kwarg V3
        assert by_agent[301] == {'verify_cmd': 'pytest -q', 'task_id': 'prouve'}

    def test_v2_send_signature_still_works_without_verify(self):
        """Invariant : un send() v2 (sans **kw) reste valide si aucun step
        ne porte verify — le moteur n'ajoute pas de kwargs."""
        def send_v2(agent, prompt, from_agent=0, timeout=120):
            return 'ok'

        wf = make_wf([{'name': 'a', 'agent': 300, 'prompt': 'x'}])
        results = run_workflow(wf, send=send_v2, log=quiet)
        assert results['a']['status'] == 'done'

    def test_verify_failed_send_error_triggers_on_failure(self):
        """RuntimeError du transport ([VERIFY_FAILED]) → politique on_failure."""
        def send(agent, prompt, from_agent=0, timeout=120, **kw):
            if kw.get('verify_cmd'):
                raise RuntimeError("[VERIFY_FAILED] BLOCKED|task=b|raison=budget_retries")
            return 'ok'

        wf = make_wf([
            {'name': 'a', 'agent': 300, 'prompt': 'x'},
            {'name': 'b', 'agent': 301, 'prompt': 'y', 'verify': 'exit 1',
             'depends_on': ['a'], 'on_failure': 'continue'},
            {'name': 'c', 'agent': 302, 'prompt': 'z', 'depends_on': ['b']},
        ])
        results = run_workflow(wf, send=send, log=quiet)
        assert results['a']['status'] == 'done'
        assert results['b']['status'] == 'failed'
        assert 'VERIFY_FAILED' in results['b']['error']
        assert results['c']['status'] == 'skipped'
