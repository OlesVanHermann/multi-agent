"""E1 — Garde-fou global : aucun couplage `claude` en dur hors de la couche moteur.

Le bug d'origine du repo n'était pas un bug de logique : c'était une hypothèse
implicite — « le CLI, c'est claude » — recopiée dans huit fichiers. Chaque copie
est un endroit où le moteur codex casse silencieusement.

Ce module interdit la réintroduction de cette hypothèse. Il échoue dès qu'un
fichier hors couche moteur mentionne :

    - le binaire `claude` dans une commande de lancement
    - la variable CLAUDE_CONFIG_DIR
    - le drapeau --dangerously-skip-permissions
    - une regex de profil figée sur `claude`

La seule source autorisée est :

    scripts/engines.sh                       (shell)
    scripts/agent-bridge/engines.py          (Python)
    scripts/agent-bridge/markers.claude.yaml (marqueurs UI)
    + les miroirs explicitement déclarés ci-dessous

Un miroir est toléré uniquement s'il est verrouillé par un test de cohérence
(cf. TestEngineTablesAgree) : dupliquer la table sans la tester, c'est reproduire
le bug.
"""
import os
import re
import subprocess

import pytest


def _find_project_root(start, markers=('CLAUDE.md', '.git')):
    current = os.path.realpath(start)
    while current != os.path.dirname(current):
        if any(os.path.exists(os.path.join(current, m)) for m in markers):
            return current
        current = os.path.dirname(current)
    raise FileNotFoundError(f"Marqueur {markers} introuvable depuis {start}")


BASE_DIR = _find_project_root(os.path.dirname(os.path.realpath(__file__)))

# La SEULE couche autorisée à nommer un moteur ou ses chaînes d'UI.
# Aucun « miroir » n'y figure : depuis que routers/config.py et
# crontab-scheduler.py IMPORTENT engines.py au lieu de recopier ses tables,
# la duplication a disparu — et avec elle, le risque de dérive.
ENGINE_LAYER = {
    'scripts/engines.sh',
    'scripts/agent-bridge/engines.py',
    'scripts/agent-bridge/capture-markers.sh',
    'scripts/agent-bridge/markers.claude.yaml',
    'scripts/agent-bridge/markers.codex.yaml',
    'scripts/agent-bridge/markers.yaml',          # symlink
}

# Répertoires scannés (le code exécutable, pas la doc ni les exemples)
SCAN_DIRS = ['scripts', 'web/backend', 'setup']
SCAN_EXT = ('.py', '.sh')

# ── Motifs interdits hors couche moteur ────────────────────────────────────
#
# Deux familles, et c'est la SECONDE qui a produit le bug d'origine :
#
#   1. Le binaire / la variable d'auth / le drapeau de bypass — visibles,
#      faciles à repérer à la relecture.
#   2. Les CHAÎNES D'UI du TUI ('esc to interrupt', 'bypass permissions', '❯'…).
#      Invisibles, recopiées dans trois parsings de pane distincts qui ont
#      dérivé. Un agent codex parsé avec les marqueurs de Claude Code n'affiche
#      aucune erreur : il apparaît juste éternellement occupé, ou mort.
#
FORBIDDEN = {
    # Famille 1 — lancement
    'launch_claude': re.compile(r'\bclaude\s+--dangerously-skip-permissions'),
    'config_dir_env': re.compile(r'CLAUDE_CONFIG_DIR\s*=\s*[^\s]'),
    'claude_profile_regex': re.compile(r"\^claude\\d"),
    'process_name_test': re.compile(r'pane_cmd["\']?\s*==\s*["\']claude'),
    # Famille 2 — chaînes d'UI (doivent venir de markers.<cli>.yaml)
    'ui_status_line': re.compile(r'bypass permissions'),
    'ui_busy': re.compile(r'esc to interrupt'),
    'ui_select': re.compile(r'Enter to select'),
    'ui_plan_mode': re.compile(r'plan mode on'),
    'ui_compaction': re.compile(r'[Cc]onversation compacted|compacting conversation'),
    'ui_autocompact': re.compile(r'until auto-compact'),
    'ui_context_limit': re.compile(r'Context limit reached'),
    'ui_login_expired': re.compile(r'sign in to claude|select login method'),
}


def _iter_sources():
    for d in SCAN_DIRS:
        root = os.path.join(BASE_DIR, d)
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                if not fn.endswith(SCAN_EXT):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, BASE_DIR)
                yield rel, full


def _code_lines(rel, full):
    """Lignes de CODE (commentaires exclus) — documenter un marqueur est permis.

    .py : tokenize (littéraux de chaîne uniquement), comme A1/test_markers_externalized.
    .sh : lignes hors commentaires (# en début de ligne).
    """
    if rel.endswith('.py'):
        import tokenize
        out = []
        with open(full, 'rb') as f:
            try:
                for tok in tokenize.tokenize(f.readline):
                    if tok.type == tokenize.STRING:
                        out.append((tok.start[0], tok.string))
            except (tokenize.TokenError, IndentationError, SyntaxError):
                pass
        return out
    with open(full, encoding='utf-8', errors='replace') as f:
        return [(i, l) for i, l in enumerate(f.read().split('\n'), 1)
                if not l.lstrip().startswith('#')]


@pytest.mark.parametrize('name,pattern', sorted(FORBIDDEN.items()))
def test_no_hardcoded_claude_outside_engine_layer(name, pattern):
    offenders = []
    for rel, full in _iter_sources():
        if rel.replace(os.sep, '/') in ENGINE_LAYER:
            continue
        for lineno, line in _code_lines(rel, full):
            if pattern.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()[:90]}")
    assert not offenders, (
        f"couplage moteur en dur ({name}) hors de la couche moteur :\n  "
        + "\n  ".join(offenders)
        + "\n\nLancement → scripts/engines.sh (engine_launch_cmd, engine_config_env…).\n"
          "Chaîne d'UI → markers.<cli>.yaml + engines.load_markers() / build_pane_eval()."
    )


def test_engine_layer_files_exist():
    """Une entrée obsolète d'ENGINE_LAYER masquerait un vrai couplage."""
    for rel in ENGINE_LAYER:
        assert os.path.exists(os.path.join(BASE_DIR, rel)), f"ENGINE_LAYER: {rel} absent"


class TestEngineTablesAgree:
    """Les tables Python doivent coïncider avec engines.sh, ET les consommateurs
    doivent les IMPORTER (identité d'objet), pas les recopier."""

    def test_backend_imports_rather_than_mirrors(self):
        pytest.importorskip('fastapi')
        import sys
        sys.path.insert(0, os.path.join(BASE_DIR, 'web', 'backend'))
        sys.path.insert(0, os.path.join(BASE_DIR, 'scripts', 'agent-bridge'))
        import engines
        from multi_agent.routers import config as m
        assert m.ENGINE_CONFIG_ENV is engines.ENGINE_CONFIG_ENV
        assert m.ENGINE_BYPASS_FLAG is engines.ENGINE_BYPASS_FLAG
        assert m.ENGINE_MODEL_PREFIX is engines.ENGINE_MODEL_PREFIX
        assert m.ENGINES is engines.ENGINES

    def test_crontab_imports_rather_than_mirrors(self):
        import importlib.util
        import sys
        sys.path.insert(0, os.path.join(BASE_DIR, 'scripts', 'agent-bridge'))
        import engines
        spec = importlib.util.spec_from_file_location(
            'crontab_sched2', os.path.join(BASE_DIR, 'scripts', 'crontab-scheduler.py'))
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            pytest.skip('crontab-scheduler : dépendances non installées')
        assert mod.ENGINE_CONFIG_ENV is engines.ENGINE_CONFIG_ENV
        assert mod.ENGINE_BYPASS_FLAG is engines.ENGINE_BYPASS_FLAG

    @pytest.fixture(scope='class')
    def sh_table(self):
        script = os.path.join(BASE_DIR, 'scripts', 'engines.sh')
        table = {}
        for cli in ('claude', 'codex'):
            r = subprocess.run(
                ['bash', '-c',
                 f'source "{script}"; engine_config_env {cli}; echo; '
                 f'engine_bypass_flag {cli}; echo; engine_model_prefix {cli}'],
                capture_output=True, text=True, timeout=15)
            env, flag, prefix = r.stdout.strip().split('\n')
            table[cli] = (env, flag, prefix)
        return table

    def test_backend_router_mirror(self, sh_table):
        pytest.importorskip('fastapi')
        import sys
        sys.path.insert(0, os.path.join(BASE_DIR, 'web', 'backend'))
        from multi_agent.routers import config as m
        for cli, (env, flag, prefix) in sh_table.items():
            assert m.ENGINE_CONFIG_ENV[cli] == env
            assert m.ENGINE_BYPASS_FLAG[cli] == flag
            assert m.ENGINE_MODEL_PREFIX[cli] == prefix

    def test_crontab_mirror(self, sh_table):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'crontab_sched', os.path.join(BASE_DIR, 'scripts', 'crontab-scheduler.py'))
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            pytest.skip('crontab-scheduler : dépendances non installées')
        for cli, (env, flag, _prefix) in sh_table.items():
            assert mod.ENGINE_CONFIG_ENV[cli] == env
            assert mod.ENGINE_BYPASS_FLAG[cli] == flag


class TestAgentsMd:
    """Codex lit AGENTS.md, pas CLAUDE.md.
    [Documenté: developers.openai.com/codex — AGENTS.md]"""

    def test_agents_md_exists(self):
        assert os.path.exists(os.path.join(BASE_DIR, 'AGENTS.md'))

    def test_agents_md_points_to_claude_md(self):
        p = os.path.join(BASE_DIR, 'AGENTS.md')
        assert os.path.islink(p), "AGENTS.md doit être un symlink (une seule source)"
        assert os.path.basename(os.readlink(p)) == 'CLAUDE.md'

    def test_under_codex_project_doc_cap(self):
        """project_doc_max_bytes vaut 32 KiB par défaut : au-delà, Codex tronque.
        [Documenté: developers.openai.com/codex/config-reference]"""
        size = os.path.getsize(os.path.join(BASE_DIR, 'CLAUDE.md'))
        assert size < 32 * 1024, (
            f"CLAUDE.md fait {size} o : au-delà de 32 KiB, Codex tronque AGENTS.md"
        )
