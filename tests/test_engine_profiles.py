"""E1 — Profils de login multi-moteurs.

Le répertoire login/<profil>/ n'a pas la même structure selon le moteur :
Claude Code y attend un CLAUDE_CONFIG_DIR, Codex un CODEX_HOME. Plutôt qu'une
4ᵉ dimension de configuration, le PRÉFIXE du nom de profil porte le moteur :

    claude1a → claude   |   codex2b → codex

Trois chemins de code faisaient l'hypothèse « tout profil est un profil Claude »
et cassaient donc le moteur codex :

    web/backend/multi_agent/routers/config.py   (keepalive : 3 regex + cmd en dur)
    scripts/crontab-scheduler.py                (sweep keepalive : idem)
    setup/login_create.sh                       (création + auth)

Ces tests verrouillent la généralisation ET l'impossibilité de croiser un profil
d'un moteur avec un autre moteur (auth silencieusement cassée).
"""
import importlib.util
import os
import re
import subprocess
import sys

import pytest


def _find_project_root(start, markers=('CLAUDE.md', '.git')):
    current = os.path.realpath(start)
    while current != os.path.dirname(current):
        if any(os.path.exists(os.path.join(current, m)) for m in markers):
            return current
        current = os.path.dirname(current)
    raise FileNotFoundError(f"Marqueur {markers} introuvable depuis {start}")


BASE_DIR = _find_project_root(os.path.dirname(os.path.realpath(__file__)))
ENGINES_SH = os.path.join(BASE_DIR, 'scripts', 'engines.sh')
LOGIN_CREATE = os.path.join(BASE_DIR, 'setup', 'login_create.sh')
CRONTAB = os.path.join(BASE_DIR, 'scripts', 'crontab-scheduler.py')
sys.path.insert(0, os.path.join(BASE_DIR, 'scripts', 'agent-bridge'))
sys.path.insert(0, os.path.join(BASE_DIR, 'web', 'backend'))

import engines  # noqa: E402


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def sh(snippet):
    return subprocess.run(
        ['bash', '-c', f'source "{ENGINES_SH}"\n{snippet}'],
        capture_output=True, text=True, timeout=15,
    )


# ── Dérivation moteur ← profil : les 3 implémentations doivent coïncider ──

CASES_OK = [
    ('claude1a', 'claude'),
    ('claude4b', 'claude'),
    ('codex1a', 'codex'),
    ('codex9z', 'codex'),
]
CASES_KO = ['gemini1a', 'x1a', '', 'claude', 'CLAUDE1A']


class TestProfileEnginePython:
    @pytest.mark.parametrize('profile,expected', CASES_OK)
    def test_engine_of(self, profile, expected):
        assert engines.profile_engine(profile) == expected

    @pytest.mark.parametrize('profile', ['gemini1a', 'x1a', '', 'nope'])
    def test_unknown_returns_none(self, profile):
        assert engines.profile_engine(profile) is None

    def test_never_defaults_to_claude(self):
        """Retourner `claude` par défaut ferait lancer Claude Code sur un
        répertoire de profil inconnu — il faut None, et un refus explicite."""
        assert engines.profile_engine('gemini1a') is None


class TestProfileValidityPython:
    @pytest.mark.parametrize('profile,_e', CASES_OK)
    def test_valid(self, profile, _e):
        assert engines.is_valid_profile(profile)

    @pytest.mark.parametrize('profile', CASES_KO + ['claude10a', 'claude1ab', 'claude1A'])
    def test_invalid(self, profile):
        assert not engines.is_valid_profile(profile)


class TestProfileEngineShell:
    @pytest.mark.parametrize('profile,expected', CASES_OK)
    def test_engine_from_profile(self, profile, expected):
        r = sh(f'engine_from_profile {profile}')
        assert r.returncode == 0
        assert r.stdout.strip() == expected

    @pytest.mark.parametrize('profile', ['gemini1a', 'x1a', ''])
    def test_unknown_profile_fails(self, profile):
        assert sh(f'engine_from_profile "{profile}"').returncode != 0

    @pytest.mark.parametrize('profile,_e', CASES_OK)
    def test_profile_is_valid(self, profile, _e):
        assert sh(f'engine_profile_is_valid {profile}').returncode == 0

    @pytest.mark.parametrize('profile', ['claude10a', 'claude1ab', 'gemini1a'])
    def test_profile_invalid(self, profile):
        assert sh(f'engine_profile_is_valid {profile}').returncode != 0


class TestImplementationsAgree:
    """engines.py, engines.sh et les deux miroirs Python doivent produire le
    MÊME moteur pour un profil donné — sinon un agent est lancé avec le bon
    binaire mais le mauvais répertoire d'auth (ou l'inverse)."""

    @pytest.mark.parametrize('profile,expected', CASES_OK)
    def test_python_shell_and_backend_agree(self, profile, expected):
        pytest.importorskip('fastapi')
        from multi_agent.routers import config as cfgmod
        assert engines.profile_engine(profile) == expected
        assert sh(f'engine_from_profile {profile}').stdout.strip() == expected
        assert cfgmod._profile_engine(profile) == expected

    def test_crontab_mirror_agrees(self):
        spec = importlib.util.spec_from_file_location('crontab_sched', CRONTAB)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            pytest.skip('crontab-scheduler a des dépendances non installées')
        for profile, expected in CASES_OK:
            assert mod._profile_engine(profile) == expected
        assert mod.ENGINES == engines.ENGINES

    def test_profile_regexes_agree(self):
        pytest.importorskip('fastapi')
        from multi_agent.routers import config as cfgmod
        for profile, _ in CASES_OK:
            assert cfgmod.PROFILE_RE.match(profile)
            assert re.match(engines.PROFILE_RE, profile)
        for profile in ['gemini1a', 'claude10a']:
            assert not cfgmod.PROFILE_RE.match(profile)
            assert not re.match(engines.PROFILE_RE, profile)


# ── Le keepalive backend doit voir les profils codex ──

class TestKeepaliveBackend:
    @pytest.fixture(autouse=True)
    def _mod(self):
        pytest.importorskip('fastapi')
        from multi_agent.routers import config as cfgmod
        self.m = cfgmod

    def test_no_hardcoded_claude_profile_regex(self):
        src = open(os.path.join(BASE_DIR, 'web', 'backend', 'multi_agent',
                                'routers', 'config.py')).read()
        assert r"^claude\d[a-b]$" not in src, (
            "regex de profil figée sur claude : les profils codex sont invisibles"
        )
        assert 'startswith("claude")' not in src

    def test_no_hardcoded_claude_launch(self):
        src = open(os.path.join(BASE_DIR, 'web', 'backend', 'multi_agent',
                                'routers', 'config.py')).read()
        assert 'claude --dangerously-skip-permissions' not in src

    def test_engine_tables_mirror_shell(self):
        for cli in self.m.ENGINES:
            env = sh(f'engine_config_env {cli}').stdout.strip()
            flag = sh(f'engine_bypass_flag {cli}').stdout.strip()
            assert self.m.ENGINE_CONFIG_ENV[cli] == env
            assert self.m.ENGINE_BYPASS_FLAG[cli] == flag

    @pytest.mark.anyio
    async def test_keepalive_lists_codex_profiles(self, tmp_path, monkeypatch):
        for name in ('claude1a', 'codex1a', 'notaprofile'):
            (tmp_path / 'login' / name).mkdir(parents=True)
        monkeypatch.setattr(self.m.cfg, 'PROFILES_DIR', tmp_path / 'login')
        monkeypatch.setattr(self.m.cfg, 'KEEPALIVE_DIR', tmp_path / 'keepalive')
        res = await self.m.get_keepalive()
        names = {e['profile'] for e in res['entries']}
        assert names == {'claude1a', 'codex1a'}
        by = {e['profile']: e['engine'] for e in res['entries']}
        assert by == {'claude1a': 'claude', 'codex1a': 'codex'}


# ── crontab-scheduler ──

class TestCrontabScheduler:
    def test_no_hardcoded_claude_profile_regex(self):
        src = open(CRONTAB).read()
        assert r"^claude\d[ab]$" not in src

    def test_no_hardcoded_claude_launch(self):
        src = open(CRONTAB).read()
        assert 'claude --dangerously-skip-permissions' not in src
        assert 'ENGINE_BYPASS_FLAG' in src


# ── setup/login_create.sh ──

class TestLoginCreate:
    @pytest.fixture(scope='class')
    def src(self):
        return open(LOGIN_CREATE, encoding='utf-8').read()

    def test_sources_engines(self, src):
        assert 'engines.sh' in src

    def test_no_hardcoded_claude_config_dir(self, src):
        """L'alias et l'auth étaient figés sur CLAUDE_CONFIG_DIR + claude."""
        assert 'CLAUDE_CONFIG_DIR=${PROFILES_DIR}' not in src
        assert 'CLAUDE_CONFIG_DIR="$PROFILES_DIR/$PROFILE" claude' not in src

    def test_derives_engine_from_profile(self, src):
        assert 'engine_from_profile' in src

    def test_uses_codex_login_for_codex_profiles(self, src):
        assert 'codex login' in src

    def test_rejects_unknown_prefix(self, src):
        assert 'moteur indéterminable' in src

    def test_script_syntax_valid(self):
        r = subprocess.run(['bash', '-n', LOGIN_CREATE],
                           capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, r.stderr


# ── Refus de croiser profil et moteur au démarrage d'un agent ──

class TestAgentStartupProfileGuard:
    """agent.sh doit refuser `cli=claude` + `login=codex1a` : sinon
    CLAUDE_CONFIG_DIR pointe un répertoire Codex → auth cassée, sans message."""

    def test_agent_sh_checks_profile_engine(self):
        src = open(os.path.join(BASE_DIR, 'scripts', 'agent.sh')).read()
        assert 'engine_from_profile' in src
        assert 'engine_effective_profile' in src
