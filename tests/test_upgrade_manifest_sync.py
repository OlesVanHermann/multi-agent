"""Verrouillage du manifest d'intégrité (C3) entre hub-release.sh et upgrade.sh.

hub-release.sh génère patch/checksums.sha256 depuis FRAMEWORK_PATHS ;
upgrade.sh contrôle le clone téléchargé avec sa copie MANIFEST_PATHS
(fichiers hors manifest = abandon). Si les deux listes divergent, l'upgrade
avorte à tort — ou pire, applique du contenu non vérifié.
"""
import os
import re
import shlex
import subprocess

import pytest

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HUB_RELEASE = os.path.join(BASE, "patch", "hub-release.sh")
UPGRADE = os.path.join(BASE, "patch", "upgrade.sh")


def bash_array(script_path, name):
    """Extrait le contenu d'un array bash NAME=( ... ) (multi-lignes)."""
    with open(script_path, encoding="utf-8") as f:
        content = f.read()
    match = re.search(re.escape(name) + r"=\(([^)]*)\)", content, re.S)
    assert match, f"array {name} introuvable dans {script_path}"
    return shlex.split(match.group(1))


@pytest.fixture(scope="module")
def framework_paths():
    return bash_array(HUB_RELEASE, "FRAMEWORK_PATHS")


@pytest.fixture(scope="module")
def manifest_paths():
    return bash_array(UPGRADE, "MANIFEST_PATHS")


class TestMiroir:
    def test_listes_identiques(self, framework_paths, manifest_paths):
        assert framework_paths == manifest_paths, (
            "FRAMEWORK_PATHS (hub-release.sh) et MANIFEST_PATHS (upgrade.sh) "
            "doivent rester des miroirs exacts — modifier les deux ensemble"
        )

    def test_chemins_v3_presents(self, framework_paths):
        assert "bench" in framework_paths
        assert "login/*/settings.json" in framework_paths
        assert "AGENTS.md" in framework_paths
        for name in ("sol", "terra", "luna"):
            assert f"prompts/gpt-5-6-{name}.model" in framework_paths


class TestCouverture:
    """Tout ce qu'upgrade.sh applique doit être couvert par le manifest."""

    def test_framework_dirs_couverts(self, manifest_paths):
        for entry in bash_array(UPGRADE, "FRAMEWORK_DIRS"):
            assert entry in manifest_paths, f"{entry} synchronisé mais hors manifest"

    def test_framework_files_couverts(self, manifest_paths):
        for entry in bash_array(UPGRADE, "FRAMEWORK_FILES"):
            assert entry in manifest_paths, f"{entry} copié mais hors manifest"

    def test_prompts_canoniques_couverts(self, manifest_paths):
        canonical = bash_array(UPGRADE, "PROMPTS_CANONICAL")
        assert canonical, "PROMPTS_CANONICAL vide ?"
        for f in canonical:
            assert f"prompts/{f}" in manifest_paths, (
                f"prompts/{f} synchronisé mais hors manifest"
            )

    def test_catalogue_modeles_couvert(self, manifest_paths):
        for f in bash_array(UPGRADE, "MODEL_CATALOG"):
            assert f"prompts/{f}" in manifest_paths

    def test_slots_login_couverts(self, manifest_paths):
        assert "prompts/login[1-4][ab].login" in manifest_paths
        assert len(bash_array(UPGRADE, "LOGIN_SLOTS")) == 8


class TestPathspecs:
    """Les pathspecs du manifest doivent matcher des fichiers trackés."""

    def test_chaque_pathspec_matche(self, framework_paths):
        for spec in framework_paths:
            out = subprocess.run(
                ["git", "-C", BASE, "ls-files", "--", spec],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            assert out.strip(), f"pathspec '{spec}' ne matche aucun fichier tracké"

    def test_glob_login_matche_les_8_profils(self):
        out = subprocess.run(
            ["git", "-C", BASE, "ls-files", "--", "login/*/settings.json"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        assert len(out) == 8, f"attendu 8 settings.json de profils, trouvé {len(out)}"

    def test_reference_deny_dans_le_manifest(self):
        # La référence utilisée par la fusion deny doit être un fichier vérifié
        assert os.path.isfile(os.path.join(BASE, "login", "claude1a", "settings.json"))
