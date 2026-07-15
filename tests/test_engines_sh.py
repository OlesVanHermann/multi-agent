"""E1 — Couche moteur CLI côté shell (scripts/engines.sh).

engines.sh est la source unique de vérité pour : moteurs supportés, variable
d'authentification, drapeau de bypass, compatibilité modèle↔moteur et
construction de la commande de lancement. Une régression ici démarre un agent
avec le mauvais binaire, le mauvais profil, ou un modèle que le TUI ignore
silencieusement.
"""
import os
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
ENGINES_SH = os.path.join(BASE_DIR, 'scripts', 'engines.sh')
AGENT_SH = os.path.join(BASE_DIR, 'scripts', 'agent.sh')
INFRA_SH = os.path.join(BASE_DIR, 'scripts', 'infra.sh')


def sh(snippet, check_rc=False):
    """Exécute un snippet bash après avoir sourcé engines.sh."""
    r = subprocess.run(
        ['bash', '-c', f'source "{ENGINES_SH}"\n{snippet}'],
        capture_output=True, text=True, timeout=15,
    )
    if check_rc:
        assert r.returncode == 0, r.stderr
    return r


class TestEnginesSourcing:
    def test_engines_sh_exists(self):
        assert os.path.isfile(ENGINES_SH)

    def test_sources_cleanly(self):
        r = sh('echo "${ENGINES[*]}"', check_rc=True)
        assert r.stdout.strip() == 'claude codex'

    def test_default_engine_is_claude(self):
        """Rétro-compat : sans modèle GPT, une installation reste sur Claude."""
        r = sh('echo "$ENGINE_DEFAULT"', check_rc=True)
        assert r.stdout.strip() == 'claude'

    def test_agent_sh_sources_engines(self):
        assert 'engines.sh' in open(AGENT_SH).read()

    def test_infra_sh_sources_engines(self):
        assert 'engines.sh' in open(INFRA_SH).read()


class TestEngineIsValid:
    @pytest.mark.parametrize('cli', ['claude', 'codex'])
    def test_accepts_supported(self, cli):
        assert sh(f'engine_is_valid {cli}').returncode == 0

    @pytest.mark.parametrize('cli', ['gemini', 'bash', 'claude2', '', 'CLAUDE'])
    def test_rejects_unsupported(self, cli):
        assert sh(f'engine_is_valid "{cli}"').returncode != 0


class TestConfigEnv:
    def test_claude_uses_claude_config_dir(self):
        assert sh('engine_config_env claude', check_rc=True).stdout.strip() == 'CLAUDE_CONFIG_DIR'

    def test_codex_uses_codex_home(self):
        assert sh('engine_config_env codex', check_rc=True).stdout.strip() == 'CODEX_HOME'


class TestBypassFlag:
    def test_claude_flag_unchanged(self):
        """Le drapeau historique ne doit pas bouger — README + isolation."""
        out = sh('engine_bypass_flag claude', check_rc=True).stdout.strip()
        assert out == '--dangerously-skip-permissions'

    def test_codex_flag(self):
        out = sh('engine_bypass_flag codex', check_rc=True).stdout.strip()
        assert out == '--dangerously-bypass-approvals-and-sandbox'


class TestModelCompatibility:
    """Garde-fou central : un modèle OpenAI envoyé à Claude Code est IGNORÉ
    par le TUI, sans erreur. L'agent tourne alors sur le mauvais modèle."""

    @pytest.mark.parametrize('cli,model', [
        ('claude', 'claude-opus-4-8'),
        ('claude', 'claude-sonnet-4-5-20250929'),
        ('codex', 'gpt-5.6-sol'),
        ('codex', 'gpt-5.6-terra'),
    ])
    def test_compatible_pairs(self, cli, model):
        assert sh(f'engine_model_is_compatible {cli} {model}').returncode == 0

    @pytest.mark.parametrize('cli,model', [
        ('claude', 'gpt-5.6-sol'),
        ('codex', 'claude-opus-4-8'),
        ('codex', 'sonnet-5'),
    ])
    def test_incompatible_pairs_rejected(self, cli, model):
        assert sh(f'engine_model_is_compatible {cli} {model}').returncode != 0

    def test_empty_model_always_ok(self):
        """Pas de modèle imposé → le CLI garde son défaut : combinaison valide."""
        assert sh('engine_model_is_compatible codex ""').returncode == 0
        assert sh('engine_model_is_compatible claude ""').returncode == 0


class TestModelViaSlash:
    def test_claude_uses_slash_command(self):
        """Claude Code n'a pas d'option de lancement fiable → /model dans le TUI."""
        assert sh('engine_model_via_slash claude').returncode == 0

    def test_codex_uses_slash_like_claude(self):
        assert sh('engine_model_via_slash codex').returncode == 0


class TestNeutralLoginSlots:
    def test_slot_maps_to_claude_profile(self):
        assert sh('engine_effective_profile claude login2b', check_rc=True).stdout.strip() == 'claude2b'

    def test_slot_maps_to_codex_profile(self):
        assert sh('engine_effective_profile codex login2b', check_rc=True).stdout.strip() == 'codex2b'


class TestEffortFlag:
    @pytest.mark.parametrize('level,expected', [
        ('L', 'low'), ('M', 'medium'), ('H', 'high'),
    ])
    def test_codex_maps_effort(self, level, expected):
        out = sh(f'engine_effort_flag codex {level}', check_rc=True).stdout.strip()
        assert out == f'-c model_reasoning_effort={expected}'

    def test_claude_ignores_effort(self):
        """Claude reçoit l'effort par slash-command, pas par ce flag Codex."""
        assert sh('engine_effort_flag claude H', check_rc=True).stdout.strip() == ''

    def test_empty_effort_emits_nothing(self):
        assert sh('engine_effort_flag codex ""', check_rc=True).stdout.strip() == ''


class TestInteractiveEffortCommand:
    @pytest.mark.parametrize('level,name', [('L', 'low'), ('M', 'medium'), ('H', 'high')])
    def test_claude_uses_effort(self, level, name):
        out = sh(f'engine_effort_slash claude {level}', check_rc=True).stdout.strip()
        assert out == f'/effort {name}'

    @pytest.mark.parametrize('level,name', [('L', 'low'), ('M', 'medium'), ('H', 'high')])
    def test_codex_uses_reasoning(self, level, name):
        out = sh(f'engine_effort_slash codex {level}', check_rc=True).stdout.strip()
        assert out == f'/reasoning {name}'

    def test_unknown_level_is_rejected(self):
        assert sh('engine_effort_slash codex X').returncode != 0

    def test_startup_applies_effort_before_bridge(self):
        source = open(os.path.join(BASE_DIR, 'scripts', 'agent.sh')).read()
        assert 'apply_cli_effort "$SESSION_NAME" "$CLI" "$EFFORT"' in source
        assert 'apply_cli_effort "$SESSION" "$CLI" "$EFFORT"' in source


class TestLaunchCmd:
    def test_claude_command_is_byte_identical_to_v3(self):
        """RÉGRESSION : la commande claude doit rester CELLE de v3.0.13."""
        out = sh(
            'engine_launch_cmd claude /opt/ma/login claude1a claude-opus-4-8',
            check_rc=True,
        ).stdout.strip()
        assert out == (
            'CLAUDE_CONFIG_DIR=/opt/ma/login/claude1a claude '
            '--dangerously-skip-permissions'
        )
        # Le modèle N'EST PAS dans la commande : il passe par /model (slash).
        assert 'opus' not in out

    def test_codex_command_carries_model_and_billing_locks(self):
        """La commande codex porte les verrous de facturation (cf.
        tests/test_codex_billing.py) : sans eux, une OPENAI_API_KEY résiduelle
        ferait basculer en facturation au token, sans le dire."""
        out = sh(
            'engine_launch_cmd codex /opt/ma/login codex1a gpt-5.6-sol',
            check_rc=True,
        ).stdout.strip()
        assert out == (
            'env -u OPENAI_API_KEY -u CODEX_API_KEY '
            'CODEX_HOME=/opt/ma/login/codex1a codex '
            '--dangerously-bypass-approvals-and-sandbox '
            '-c forced_login_method=chatgpt'
        )

    def test_codex_command_with_effort(self):
        out = sh(
            'engine_launch_cmd codex /opt/ma/login codex1a gpt-5.6-sol H',
            check_rc=True,
        ).stdout.strip()
        assert '--model' not in out

    def test_no_login_means_no_env_prefix(self):
        out = sh('engine_launch_cmd claude /opt/ma/login "" ""', check_rc=True).stdout.strip()
        assert out == 'claude --dangerously-skip-permissions'

    def test_rejects_incompatible_model(self):
        r = sh('engine_launch_cmd claude /opt/ma/login claude1a gpt-5.6-sol')
        assert r.returncode != 0
        assert r.stdout.strip() == ''

    def test_rejects_unknown_engine(self):
        r = sh('engine_launch_cmd gemini /opt/ma/login x claude-opus-4-8')
        assert r.returncode != 0

    @pytest.mark.parametrize('login', ['../../etc', 'a;rm -rf /', 'a b', '$(id)'])
    def test_rejects_injected_login(self, login):
        """Le profil finit dans une commande tmux send-keys : pas d'injection."""
        r = sh(f'engine_launch_cmd claude /opt/ma/login "{login}" ""')
        assert r.returncode != 0, f"login accepté à tort : {login!r}"

    @pytest.mark.parametrize('model', ['claude-x; id', 'claude-x$(id)', 'claude x'])
    def test_rejects_injected_model(self, model):
        r = sh(f'engine_launch_cmd claude /opt/ma/login claude1a "{model}"')
        assert r.returncode != 0, f"modèle accepté à tort : {model!r}"


class TestNoHardcodedClaudeLaunch:
    """Aucun script ne doit plus construire « claude --dangerously-skip-… »
    en dur : la commande vient d'engine_launch_cmd, sinon un agent codex
    lancerait quand même claude."""

    @pytest.mark.parametrize('script', ['scripts/agent.sh', 'scripts/infra.sh'])
    def test_no_inline_claude_bypass_flag(self, script):
        content = open(os.path.join(BASE_DIR, script)).read()
        assert 'claude --dangerously-skip-permissions' not in content, (
            f"{script} construit encore la commande claude en dur"
        )

    @pytest.mark.parametrize('script', ['scripts/agent.sh', 'scripts/infra.sh'])
    def test_uses_engine_launch_cmd(self, script):
        content = open(os.path.join(BASE_DIR, script)).read()
        assert 'engine_launch_cmd' in content or 'build_launch_cmd' in content

    def test_agent_sh_exports_agent_cli_to_bridge(self):
        """Le bridge choisit ses marqueurs via AGENT_CLI — s'il ne le reçoit
        pas, un agent codex serait parsé avec les marqueurs de Claude Code."""
        content = open(AGENT_SH).read()
        assert content.count("AGENT_CLI=") >= 2, (
            "AGENT_CLI doit être exporté dans start_single ET start_all"
        )

    def test_infra_sh_exports_agent_cli_to_bridge(self):
        assert 'AGENT_CLI=' in open(INFRA_SH).read()
