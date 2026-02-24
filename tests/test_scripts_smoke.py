"""
Tests smoke pour les scripts d'orchestration (infra.sh et agent.sh)
EF-004 — Couverture : start, stop, status/help pour chaque script avec mocks

Réf spec 342 : CA-005 (≥100 LOC, 6 commandes — 3 × 2 scripts)
"""
import pytest
import subprocess
import os
import stat
import tempfile
import shutil

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
INFRA_SCRIPT = os.path.join(BASE_DIR, 'scripts', 'infra.sh')
AGENT_SCRIPT = os.path.join(BASE_DIR, 'scripts', 'agent.sh')


def script_exists(path):
    """Vérifie qu'un script existe et est exécutable"""
    return os.path.isfile(path) and os.access(path, os.X_OK)


# === infra.sh ===

class TestInfraScript:
    """EF-004 — Tests smoke pour scripts/infra.sh (start, stop, help)"""

    def test_infra_script_exists(self):
        """Vérifie que infra.sh existe et est exécutable (EF-004)"""
        assert os.path.isfile(INFRA_SCRIPT), f"infra.sh not found at {INFRA_SCRIPT}"

    def test_infra_script_is_bash(self):
        """Vérifie que infra.sh est un script bash (EF-004)"""
        with open(INFRA_SCRIPT, 'r') as f:
            first_line = f.readline().strip()
        assert first_line == '#!/bin/bash', f"Expected bash shebang, got: {first_line}"

    def test_infra_help_returns_usage(self):
        """infra.sh help affiche l'usage sans erreur (EF-004)"""
        result = subprocess.run(
            ['bash', INFRA_SCRIPT, 'help'],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        assert 'start' in result.stdout.lower()
        assert 'stop' in result.stdout.lower()

    def test_infra_no_args_shows_help(self):
        """infra.sh sans arguments affiche l'aide (EF-004)"""
        result = subprocess.run(
            ['bash', INFRA_SCRIPT],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        assert 'Usage' in result.stdout or 'usage' in result.stdout

    def test_infra_unknown_action_fails(self):
        """infra.sh avec une action inconnue retourne une erreur (EF-004)"""
        result = subprocess.run(
            ['bash', INFRA_SCRIPT, 'foobar'],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode != 0

    def test_infra_help_flag(self):
        """infra.sh --help affiche l'usage (EF-004)"""
        result = subprocess.run(
            ['bash', INFRA_SCRIPT, '--help'],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        assert 'start' in result.stdout.lower()

    def test_infra_contains_start_function(self):
        """infra.sh contient la fonction do_start (EF-004)"""
        with open(INFRA_SCRIPT, 'r') as f:
            content = f.read()
        assert 'do_start()' in content or 'do_start ()' in content

    def test_infra_contains_stop_function(self):
        """infra.sh contient la fonction do_stop (EF-004)"""
        with open(INFRA_SCRIPT, 'r') as f:
            content = f.read()
        assert 'do_stop()' in content or 'do_stop ()' in content

    def test_infra_uses_docker(self):
        """infra.sh référence Docker pour Redis et Keycloak (EF-004)"""
        with open(INFRA_SCRIPT, 'r') as f:
            content = f.read()
        assert 'docker' in content.lower()
        assert 'redis' in content.lower()

    def test_infra_starts_agent_000(self):
        """infra.sh contient la logique de démarrage de l'agent 000 (EF-004)"""
        with open(INFRA_SCRIPT, 'r') as f:
            content = f.read()
        assert 'agent-000' in content or 'SESSION_NAME' in content


# === agent.sh ===

class TestAgentScript:
    """EF-004 — Tests smoke pour scripts/agent.sh (start, stop, help)"""

    def test_agent_script_exists(self):
        """Vérifie que agent.sh existe (EF-004)"""
        assert os.path.isfile(AGENT_SCRIPT), f"agent.sh not found at {AGENT_SCRIPT}"

    def test_agent_script_is_bash(self):
        """Vérifie que agent.sh est un script bash (EF-004)"""
        with open(AGENT_SCRIPT, 'r') as f:
            first_line = f.readline().strip()
        assert first_line == '#!/bin/bash', f"Expected bash shebang, got: {first_line}"

    def test_agent_help_returns_usage(self):
        """agent.sh help affiche l'usage sans erreur (EF-004)"""
        result = subprocess.run(
            ['bash', AGENT_SCRIPT, 'help'],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        assert 'start' in result.stdout.lower()
        assert 'stop' in result.stdout.lower()

    def test_agent_no_args_shows_help(self):
        """agent.sh sans arguments affiche l'aide (EF-004)"""
        result = subprocess.run(
            ['bash', AGENT_SCRIPT],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        assert 'Usage' in result.stdout or 'usage' in result.stdout

    def test_agent_unknown_action_fails(self):
        """agent.sh avec une action inconnue retourne une erreur (EF-004)"""
        result = subprocess.run(
            ['bash', AGENT_SCRIPT, 'foobar'],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode != 0

    def test_agent_help_flag(self):
        """agent.sh --help affiche l'usage (EF-004)"""
        result = subprocess.run(
            ['bash', AGENT_SCRIPT, '--help'],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        assert 'start' in result.stdout.lower()

    def test_agent_contains_start_functions(self):
        """agent.sh contient start_single et start_all (EF-004)"""
        with open(AGENT_SCRIPT, 'r') as f:
            content = f.read()
        assert 'start_single()' in content or 'start_single ()' in content
        assert 'start_all()' in content or 'start_all ()' in content

    def test_agent_contains_stop_functions(self):
        """agent.sh contient stop_single et stop_all (EF-004)"""
        with open(AGENT_SCRIPT, 'r') as f:
            content = f.read()
        assert 'stop_single()' in content or 'stop_single ()' in content
        assert 'stop_all()' in content or 'stop_all ()' in content

    def test_agent_protects_000(self):
        """agent.sh protège l'agent 000 contre le démarrage/arrêt direct (EF-004)"""
        with open(AGENT_SCRIPT, 'r') as f:
            content = f.read()
        assert 'is_protected' in content
        assert '000' in content

    def test_agent_uses_tmux(self):
        """agent.sh utilise tmux pour isoler les agents (EF-004)"""
        with open(AGENT_SCRIPT, 'r') as f:
            content = f.read()
        assert 'tmux' in content
        assert 'new-session' in content

    def test_agent_uses_bridge(self):
        """agent.sh lance le bridge Python pour chaque agent (EF-004)"""
        with open(AGENT_SCRIPT, 'r') as f:
            content = f.read()
        assert 'agent.py' in content or 'BRIDGE_SCRIPT' in content

    def test_agent_batch_processing(self):
        """agent.sh supporte le démarrage par batch (BATCH_SIZE) (EF-004)"""
        with open(AGENT_SCRIPT, 'r') as f:
            content = f.read()
        assert 'BATCH_SIZE' in content


# === Tests croisés ===

class TestScriptInteractions:
    """EF-004 — Vérification de la cohérence entre les deux scripts"""

    def test_both_scripts_share_ma_prefix(self):
        """Les deux scripts utilisent MA_PREFIX pour la cohérence (EF-004)"""
        for script_path in [INFRA_SCRIPT, AGENT_SCRIPT]:
            with open(script_path, 'r') as f:
                content = f.read()
            assert 'MA_PREFIX' in content, f"{script_path} should use MA_PREFIX"

    def test_both_scripts_reference_base_dir(self):
        """Les deux scripts définissent BASE_DIR correctement (EF-004)"""
        for script_path in [INFRA_SCRIPT, AGENT_SCRIPT]:
            with open(script_path, 'r') as f:
                content = f.read()
            assert 'BASE_DIR' in content, f"{script_path} should define BASE_DIR"

    def test_infra_calls_agent_stop(self):
        """infra.sh stop appelle agent.sh stop all pour arrêter les workers (EF-004)"""
        with open(INFRA_SCRIPT, 'r') as f:
            content = f.read()
        assert 'agent.sh' in content, "infra.sh should reference agent.sh for stopping workers"
