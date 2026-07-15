"""E1 — Marqueurs UI par moteur (engines.py + markers.<cli>.yaml).

Le bridge déduit l'état d'un agent (busy / ready / compaction / erreur) en
lisant le pane tmux. Ces chaînes sont propres au TUI de chaque CLI. Deux
invariants à tenir :

1. Le moteur `claude` reste STRICTEMENT identique à v3.0.13 (markers.yaml est
   un lien symbolique vers markers.claude.yaml).
2. Un moteur dont les marqueurs ne sont pas relevés sur un TUI réel doit
   ÉCHOUER AU DÉMARRAGE — jamais dégrader silencieusement la détection, ce qui
   produirait des agents figés ou des réponses tronquées sans erreur.
"""
import importlib
import os
import sys

import pytest

yaml = pytest.importorskip("yaml")


def _find_project_root(start, markers=('CLAUDE.md', '.git')):
    current = os.path.realpath(start)
    while current != os.path.dirname(current):
        if any(os.path.exists(os.path.join(current, m)) for m in markers):
            return current
        current = os.path.dirname(current)
    raise FileNotFoundError(f"Marqueur {markers} introuvable depuis {start}")


BASE_DIR = _find_project_root(os.path.dirname(os.path.realpath(__file__)))
BRIDGE_DIR = os.path.join(BASE_DIR, 'scripts', 'agent-bridge')
sys.path.insert(0, BRIDGE_DIR)

import engines  # noqa: E402

MARKERS_LEGACY = os.path.join(BRIDGE_DIR, 'markers.yaml')
MARKERS_CLAUDE = os.path.join(BRIDGE_DIR, 'markers.claude.yaml')
MARKERS_CODEX = os.path.join(BRIDGE_DIR, 'markers.codex.yaml')


def load(path):
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)


class TestBackwardCompat:
    """Le chemin `claude` ne doit pas bouger d'un octet."""

    def test_markers_yaml_still_resolves(self):
        assert os.path.isfile(MARKERS_LEGACY), "markers.yaml a disparu"

    def test_markers_yaml_is_symlink_to_claude(self):
        assert os.path.islink(MARKERS_LEGACY)
        assert os.path.realpath(MARKERS_LEGACY) == os.path.realpath(MARKERS_CLAUDE)

    def test_legacy_and_claude_markers_identical(self):
        assert load(MARKERS_LEGACY) == load(MARKERS_CLAUDE)

    def test_claude_ui_strings_unchanged(self):
        m = load(MARKERS_CLAUDE)
        assert m['status_line'] == 'bypass permissions'
        assert m['busy_markers'] == ['esc to interrupt']
        assert m['prompt_markers'][0] == '❯'
        assert m['compaction']['done'] == 'Conversation compacted'

    def test_no_agent_cli_means_claude(self, monkeypatch):
        """Installation existante : aucun AGENT_CLI dans l'environnement."""
        monkeypatch.delenv('AGENT_CLI', raising=False)
        assert engines.current_engine() == 'claude'
        assert engines.load_markers() == load(MARKERS_CLAUDE)

    def test_empty_agent_cli_means_claude(self, monkeypatch):
        monkeypatch.setenv('AGENT_CLI', '')
        assert engines.current_engine() == 'claude'


class TestEngineSelection:
    def test_agent_cli_selects_markers_file(self, monkeypatch):
        monkeypatch.setenv('AGENT_CLI', 'codex')
        assert engines.markers_path().name == 'markers.codex.yaml'

    def test_unknown_engine_raises(self, monkeypatch):
        monkeypatch.setenv('AGENT_CLI', 'gemini')
        with pytest.raises(RuntimeError, match='Moteur inconnu'):
            engines.current_engine()

    def test_engines_list_mirrors_shell(self):
        """engines.py et engines.sh doivent lister les MÊMES moteurs."""
        sh = open(os.path.join(BASE_DIR, 'scripts', 'engines.sh')).read()
        for e in engines.ENGINES:
            assert e in sh, f"moteur {e} absent d'engines.sh"
        assert f'ENGINE_DEFAULT="{engines.ENGINE_DEFAULT}"' in sh


class TestMarkersContract:
    @pytest.mark.parametrize('path', [MARKERS_CLAUDE, MARKERS_CODEX])
    def test_all_required_keys_present(self, path):
        m = load(path)
        missing = [k for k in engines.REQUIRED_KEYS if k not in m]
        assert not missing, f"{os.path.basename(path)} : clés manquantes {missing}"

    def test_both_engines_declare_same_keys(self):
        """Un moteur ne peut pas « oublier » une dimension d'état."""
        assert set(load(MARKERS_CLAUDE)) == set(load(MARKERS_CODEX))

    def test_process_names_are_engine_specific(self):
        assert 'claude' in load(MARKERS_CLAUDE)['process_names']
        assert 'codex' in load(MARKERS_CODEX)['process_names']

    def test_claude_markers_have_no_sentinel(self):
        m = load(MARKERS_CLAUDE)
        flat = list(engines._walk_values(m))
        assert engines.TODO_SENTINEL not in flat


class TestFailFastOnUnverifiedMarkers:
    """Le fail-fast est le garde-fou central : tant que les marqueurs d'un moteur
    n'ont pas été RELEVÉS sur une source réelle, il ne démarre pas.

    Les marqueurs `codex` sont maintenant relevés (source openai/codex — cf.
    TestCodexMarkersAreCaptured). Le MÉCANISME reste testé ici, sur un fichier
    synthétique : c'est lui qui protège le prochain moteur ajouté.
    """

    @pytest.fixture
    def fake_engine(self, tmp_path, monkeypatch):
        """Un moteur 'claude' factice, dont on corrompt les marqueurs à volonté."""
        base = load(MARKERS_CLAUDE)
        monkeypatch.setattr(engines, '_DIR', tmp_path)

        def write(markers):
            (tmp_path / 'markers.claude.yaml').write_text(
                yaml.safe_dump(markers, allow_unicode=True), encoding='utf-8')
            return markers

        return base, write

    def test_sentinel_at_top_level_raises(self, fake_engine):
        base, write = fake_engine
        base['status_line'] = engines.TODO_SENTINEL
        write(base)
        with pytest.raises(RuntimeError) as exc:
            engines.load_markers('claude')
        msg = str(exc.value)
        assert 'status_line' in msg
        assert 'capture-markers.sh claude' in msg, "le message doit dire QUOI faire"

    def test_sentinel_nested_in_list_is_caught(self, fake_engine):
        base, write = fake_engine
        base['api_error_patterns'] = ['API Error: 401', engines.TODO_SENTINEL]
        write(base)
        with pytest.raises(RuntimeError, match='non renseignés'):
            engines.load_markers('claude')

    def test_sentinel_nested_in_dict_is_caught(self, fake_engine):
        base, write = fake_engine
        base['compaction']['done'] = engines.TODO_SENTINEL
        write(base)
        with pytest.raises(RuntimeError, match='compaction'):
            engines.load_markers('claude')

    def test_missing_key_raises(self, tmp_path, monkeypatch):
        (tmp_path / 'markers.claude.yaml').write_text(
            "process_names: ['claude']\nprompt_markers: ['x']\n", encoding='utf-8')
        monkeypatch.setattr(engines, '_DIR', tmp_path)
        with pytest.raises(RuntimeError, match='Clés manquantes'):
            engines.load_markers('claude')

    def test_missing_markers_file_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(engines, '_DIR', tmp_path)
        with pytest.raises(RuntimeError, match='introuvable'):
            engines.load_markers('claude')

    def test_invalid_busy_scope_raises(self, fake_engine):
        base, write = fake_engine
        base['busy_scope'] = 'somewhere'
        write(base)
        with pytest.raises(RuntimeError, match='busy_scope invalide'):
            engines.load_markers('claude')

    def test_invalid_bashes_scope_raises(self, fake_engine):
        base, write = fake_engine
        base['bashes_scope'] = 'nope'
        write(base)
        with pytest.raises(RuntimeError, match='bashes_scope invalide'):
            engines.load_markers('claude')


class TestNaSentinel:
    """__NON_APPLICABLE__ ≠ __A_RENSEIGNER__.

    « Pas encore relevé » est une DETTE : le moteur ne démarre pas.
    « N'existe pas dans ce TUI » est un FAIT : le marqueur devient inerte.

    Les confondre serait grave dans les deux sens : soit on bloque un moteur
    parfaitement utilisable, soit on laisse passer un marqueur inventé.
    """

    def test_na_is_allowed_and_never_matches(self):
        m = engines.load_markers('codex')
        assert m['survey'] == engines.NEVER_MATCH
        assert engines.NEVER_MATCH not in "n'importe quel pane tmux"

    def test_na_is_not_the_empty_string(self):
        """Une chaîne vide matcherait TOUS les panes — le pire résultat possible."""
        assert engines.NEVER_MATCH != ''
        assert len(engines.NEVER_MATCH) > 3

    def test_na_survives_argv(self):
        """Le motif doit être transportable dans argv : pas d'octet nul."""
        import subprocess
        assert '\x00' not in engines.NEVER_MATCH
        r = subprocess.run(['bash', '-c', 'printf "%s" "$1"', '_', engines.NEVER_MATCH],
                           capture_output=True, text=True)
        assert r.returncode == 0

    def test_todo_and_na_are_distinct(self):
        assert engines.TODO_SENTINEL != engines.NA_SENTINEL

    def test_na_does_not_block_loading(self):
        engines.load_markers('codex')  # ne lève pas, malgré 3 [NA]


class TestCodexMarkersAreCaptured:
    """Les marqueurs codex sont relevés sur le source openai/codex."""

    def test_no_todo_sentinel_remains(self):
        flat = list(engines._walk_values(load(MARKERS_CODEX)))
        assert engines.TODO_SENTINEL not in flat

    def test_codex_loads(self):
        m = engines.load_markers('codex')
        assert m['busy_markers'] == ['to interrupt']
        # « · » : séparateur du footer permanent « <model> <effort> · <dir> » —
        # 'context left' n'apparaît pas sur session fraîche (vérifié 0.144.4),
        # ce qui déclenchait la sonde de vie (api_error) à tort.
        assert m['status_line'] == ' · '

    def test_codex_busy_scope_differs_from_claude(self):
        """LA différence structurelle. Si elle disparaît, un agent codex serait
        vu libre en permanence (son composer reste affiché pendant le travail)."""
        assert engines.load_markers('codex')['busy_scope'] == 'pane'
        assert engines.load_markers('claude')['busy_scope'] == 'status_line'


class TestPaneStateUsesEngineProcessNames:
    """_parse_pane_state ne doit plus coder ('claude','node') en dur, sinon
    tout agent codex apparaît mort au dashboard."""

    def _agent(self):
        import agent
        return importlib.reload(agent)

    def test_claude_process_alive(self, monkeypatch):
        monkeypatch.delenv('AGENT_CLI', raising=False)
        agent = self._agent()
        st = agent._parse_pane_state("bypass permissions\n❯ \n", "claude", "300")
        assert st['claude_alive'] is True

    def test_unknown_process_is_dead(self, monkeypatch):
        monkeypatch.delenv('AGENT_CLI', raising=False)
        agent = self._agent()
        st = agent._parse_pane_state("bypass permissions\n❯ \n", "bash", "300")
        assert st['claude_alive'] is False

    def test_codex_process_alive_with_codex_names(self, monkeypatch):
        """Injection explicite des process_names : le moteur codex reconnaît
        son binaire même si le bridge tourne avec les marqueurs de claude."""
        monkeypatch.delenv('AGENT_CLI', raising=False)
        agent = self._agent()
        st = agent._parse_pane_state(
            "› \n", "codex", "300", process_names=['codex', 'node'])
        assert st['claude_alive'] is True

    def test_codex_process_dead_under_claude_names(self, monkeypatch):
        """Preuve du bug évité : sans la clé process_names, codex = mort."""
        monkeypatch.delenv('AGENT_CLI', raising=False)
        agent = self._agent()
        st = agent._parse_pane_state(
            "› \n", "codex", "300", process_names=['claude', 'node'])
        assert st['claude_alive'] is False

    def test_default_process_names_come_from_markers(self, monkeypatch):
        monkeypatch.delenv('AGENT_CLI', raising=False)
        agent = self._agent()
        assert agent.PROCESS_NAMES == load(MARKERS_CLAUDE)['process_names']


# ── ready_markers : « le CLI a fini de booter » (≠ « la réponse est finie ») ──

class TestReadyMarkers:
    def test_claude_ready_markers_preserve_v3_behaviour(self):
        """wait_claude_ready v3.0.13 : grep -qE '❯|Try "'. Le passage par
        ready_markers doit reproduire ce motif à l'identique — pas l'approcher."""
        assert load(MARKERS_CLAUDE)['ready_markers'] == ['❯', 'Try "']

    def test_ready_markers_is_a_list(self):
        for path in (MARKERS_CLAUDE, MARKERS_CODEX):
            assert isinstance(load(path)['ready_markers'], list)

    def test_ready_markers_distinct_from_prompt_markers(self):
        """Confondre les deux ferait conclure « prêt » sur un pane de shell."""
        m = load(MARKERS_CLAUDE)
        assert m['ready_markers'] != m['prompt_markers']

    def test_codex_ready_markers_are_captured(self):
        """Bannière « >_ OpenAI Codex (v…) » + composer « › » — relevés sur
        session réelle 0.144.4. Les anciens marqueurs des snapshots
        (« Ask Codex to do anything », « for shortcuts ») n'apparaissent plus :
        wait_cli_ready ne matchait jamais et tuait l'agent à 30 s."""
        rm = load(MARKERS_CODEX)['ready_markers']
        assert 'OpenAI Codex (v' in rm
        assert '› ' in rm
        assert engines.TODO_SENTINEL not in rm

    def test_agent_sh_reads_ready_markers_not_prompt_markers(self):
        src = open(os.path.join(BASE_DIR, 'scripts', 'agent.sh')).read()
        assert 'ready_markers' in src
        assert 'prompt_markers' not in src, (
            "agent.sh doit lire ready_markers (boot terminé), pas prompt_markers "
            "(fin de réponse) : un pane de shell affiche '$' et serait vu 'prêt'"
        )

    def test_agent_sh_has_no_python_heredoc(self):
        """v1 forkait python3 avec un heredoc à chaque tour de scrutation."""
        src = open(os.path.join(BASE_DIR, 'scripts', 'agent.sh')).read()
        assert "<<'PY'" not in src
        assert 'engine_marker_get' in src


# ── API CLI d'engines.py (utilisée par engines.sh — pas de parsing YAML en bash)

class TestEnginesCliInterface:
    def _run(self, *args):
        import subprocess
        return subprocess.run(
            [sys.executable, os.path.join(BRIDGE_DIR, 'engines.py'), *args],
            capture_output=True, text=True, timeout=15)

    def test_list(self):
        r = self._run('list')
        assert r.returncode == 0
        assert r.stdout.split() == list(engines.ENGINES)

    def test_get_ready_markers_claude(self):
        r = self._run('get', 'ready_markers', '--cli', 'claude')
        assert r.returncode == 0
        assert r.stdout.splitlines() == ['❯', 'Try "']

    def test_get_codex_busy_markers(self):
        r = self._run('get', 'busy_markers', '--cli', 'codex')
        assert r.returncode == 0
        assert r.stdout.strip() == 'to interrupt'

    def test_raw_bypasses_validation_for_diagnosis(self):
        """--raw doit rendre la valeur BRUTE (sentinelle NA non substituée) :
        c'est le mode diagnostic, il ne doit rien masquer."""
        r = self._run('get', 'survey', '--cli', 'codex', '--raw')
        assert r.returncode == 0
        assert engines.NA_SENTINEL in r.stdout

    def test_unknown_key(self):
        assert self._run('get', 'nope', '--cli', 'claude').returncode == 1

    def test_engine_of(self):
        r = self._run('engine-of', 'codex2b')
        assert r.returncode == 0 and r.stdout.strip() == 'codex'

    def test_engine_of_unknown(self):
        assert self._run('engine-of', 'gemini1a').returncode == 1

    def test_unknown_engine_is_rejected_by_argparse(self):
        assert self._run('get', 'ready_markers', '--cli', 'gemini').returncode != 0


# ── Inférence depuis .model : Python et shell doivent rester identiques ──

class TestAgentEngineCascade:
    """Une divergence entre agent_engine() (Python, dashboard/debug) et
    resolve_engine() (shell, lancement) ferait parser un pane codex avec les
    marqueurs de Claude Code : agent vu figé ou mort, sans erreur."""

    @pytest.fixture
    def prompts(self, tmp_path):
        d = tmp_path / 'prompts'
        d.mkdir()
        (d / 'default.model').write_text('claude-opus-4-8\n')
        return d

    def test_default(self, prompts):
        assert engines.agent_engine(prompts, '300') == 'claude'

    def test_no_model_file_at_all(self, tmp_path):
        d = tmp_path / 'prompts'
        d.mkdir()
        assert engines.agent_engine(d, '300') == engines.ENGINE_DEFAULT

    def test_flat_override(self, prompts):
        (prompts / '301.model').write_text('gpt-5.6-sol\n')
        assert engines.agent_engine(prompts, '301') == 'codex'
        assert engines.agent_engine(prompts, '300') == 'claude'

    def test_x45_subdir_override(self, prompts):
        sub = prompts / '345-analyse'
        sub.mkdir()
        (sub / '345-500.model').write_text('gpt-5.6-sol\n')
        assert engines.agent_engine(prompts, '345-500') == 'codex'

    def test_parent_override_applies_to_satellites(self, prompts):
        (prompts / '345.model').write_text('gpt-5.6-sol\n')
        assert engines.agent_engine(prompts, '345-500') == 'codex'

    def test_satellite_override_wins_over_parent(self, prompts):
        sub = prompts / '345-analyse'
        sub.mkdir()
        (prompts / '345.model').write_text('gpt-5.6-sol\n')
        (sub / '345-500.model').write_text('claude-opus-4-8\n')
        assert engines.agent_engine(prompts, '345-500') == 'claude'

    def test_unknown_model_family_falls_back_to_claude(self, prompts):
        (prompts / '302.model').write_text('other-model\n')
        assert engines.agent_engine(prompts, '302') == 'claude'

    def test_matches_shell_resolve_engine(self, prompts):
        """Différentiel Python ↔ shell sur les mêmes prompts/."""
        import subprocess
        (prompts / '301.model').write_text('gpt-5.6-sol\n')
        sub = prompts / '345-analyse'
        sub.mkdir()
        (sub / '345-500.model').write_text('gpt-5.6-sol\n')

        agent_sh = os.path.join(BASE_DIR, 'scripts', 'agent.sh')
        head = open(agent_sh).read().split('# ── Remote ──')[0].replace('set -e\n', '')
        for aid in ('300', '301', '345-500'):
            script = f'PROMPTS_DIR="{prompts}"\n{head}\nPROMPTS_DIR="{prompts}"\nresolve_engine {aid}'
            r = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                               timeout=15, cwd=os.path.join(BASE_DIR, 'scripts'))
            assert r.stdout.strip() == engines.agent_engine(prompts, aid), (
                f"divergence shell/Python sur {aid} : "
                f"sh={r.stdout.strip()!r} py={engines.agent_engine(prompts, aid)!r}"
            )


class TestModelMatchesEngine:
    @pytest.mark.parametrize('model,cli,ok', [
        ('claude-opus-4-8', 'claude', True),
        ('gpt-5.6-sol', 'codex', True),
        ('gpt-5.6-sol', 'claude', False),
        ('claude-opus-4-8', 'codex', False),
        ('', 'claude', False),
        ('llama-3', 'codex', False),
    ])
    def test_pairs(self, model, cli, ok):
        assert engines.model_matches_engine(model, cli) is ok


class TestLoginExpiredMarkers:
    def test_claude_markers_preserved(self):
        m = load(MARKERS_CLAUDE)['login_expired_markers']
        assert 'sign in to claude' in m
        assert 'session has expired' in m

    def test_codex_markers_are_captured(self):
        """Écran d'onboarding d'auth de Codex.
        [Source: tui/src/onboarding/auth.rs:444,460]"""
        m = load(MARKERS_CODEX)['login_expired_markers']
        assert 'sign in with chatgpt' in m
        assert 'run codex login' in m

    def test_markers_are_lowercase(self):
        """Le sweep compare en minuscules (low = text.lower())."""
        for cli in ('claude', 'codex'):
            for marker in load(engines.markers_path(cli))['login_expired_markers']:
                assert marker == marker.lower(), f"{cli}: {marker!r} n'est pas en minuscules"
