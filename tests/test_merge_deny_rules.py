"""Tests de patch/merge-deny-rules.py — fusion des permissions.deny (migration V3).

Le helper est appelé par patch/upgrade.sh pour reporter les règles deny de la
release (référence checksummée) dans les profils login/claude*/settings.json
des machines projet, sans toucher au reste du fichier.
"""
import importlib.util
import json
import os
import subprocess
import sys

import pytest

HELPER = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "patch", "merge-deny-rules.py")
)

spec = importlib.util.spec_from_file_location("merge_deny_rules", HELPER)
mdr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mdr)

REF_DENY = [
    "Read(./bench/oracle/**)",
    "Write(./bench/oracle/**)",
    "Edit(./bench/oracle/**)",
]


@pytest.fixture
def reference(tmp_path):
    path = tmp_path / "reference.json"
    path.write_text(
        json.dumps({"permissions": {"deny": REF_DENY}}), encoding="utf-8"
    )
    return path


def write_json(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


class TestMerge:
    def test_ajoute_les_regles_manquantes(self, tmp_path, reference):
        target = write_json(
            tmp_path,
            "settings.json",
            {
                "model": "claude-opus-4-6",
                "theme": "dark",
                "permissions": {"deny": ["Read(./setup/secrets.cfg)"]},
            },
        )
        assert mdr.main([str(reference), str(target)]) == 0
        data = json.loads(target.read_text(encoding="utf-8"))
        # Union : règles locales conservées en tête, référence ajoutée
        assert data["permissions"]["deny"] == ["Read(./setup/secrets.cfg)"] + REF_DENY
        # Les autres clés ne bougent pas
        assert data["model"] == "claude-opus-4-6"
        assert data["theme"] == "dark"

    def test_idempotent(self, tmp_path, reference):
        target = write_json(
            tmp_path, "settings.json", {"permissions": {"deny": list(REF_DENY)}}
        )
        assert mdr.main([str(reference), str(target)]) == 0
        premiere = target.read_text(encoding="utf-8")
        assert mdr.main([str(reference), str(target)]) == 0
        assert target.read_text(encoding="utf-8") == premiere

    def test_cible_sans_permissions(self, tmp_path, reference):
        target = write_json(tmp_path, "settings.json", {"model": "x"})
        assert mdr.main([str(reference), str(target)]) == 0
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["permissions"]["deny"] == REF_DENY
        assert data["model"] == "x"

    def test_plusieurs_cibles(self, tmp_path, reference):
        t1 = write_json(tmp_path, "a.json", {"permissions": {"deny": []}})
        t2 = write_json(tmp_path, "b.json", {"permissions": {"deny": [REF_DENY[0]]}})
        assert mdr.main([str(reference), str(t1), str(t2)]) == 0
        assert json.loads(t1.read_text(encoding="utf-8"))["permissions"]["deny"] == REF_DENY
        assert json.loads(t2.read_text(encoding="utf-8"))["permissions"]["deny"] == REF_DENY


class TestCheck:
    def test_check_ne_modifie_rien(self, tmp_path, reference):
        target = write_json(tmp_path, "settings.json", {"permissions": {"deny": []}})
        avant = target.read_text(encoding="utf-8")
        assert mdr.main(["--check", str(reference), str(target)]) == 0
        assert target.read_text(encoding="utf-8") == avant


class TestRobustesse:
    def test_cible_json_invalide_skippee(self, tmp_path, reference):
        target = tmp_path / "casse.json"
        target.write_text("{pas du json", encoding="utf-8")
        assert mdr.main([str(reference), str(target)]) == 0
        assert target.read_text(encoding="utf-8") == "{pas du json"

    def test_deny_non_liste_skippe(self, tmp_path, reference):
        target = write_json(
            tmp_path, "settings.json", {"permissions": {"deny": "tout"}}
        )
        assert mdr.main([str(reference), str(target)]) == 0
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["permissions"]["deny"] == "tout"

    def test_reference_illisible(self, tmp_path):
        target = write_json(tmp_path, "settings.json", {"permissions": {"deny": []}})
        rc = mdr.main([str(tmp_path / "absente.json"), str(target)])
        assert rc == 2

    def test_reference_sans_deny(self, tmp_path):
        ref = write_json(tmp_path, "reference.json", {"permissions": {}})
        target = write_json(tmp_path, "settings.json", {"permissions": {"deny": []}})
        assert mdr.main([str(ref), str(target)]) == 2


class TestCli:
    def test_usage_sans_arguments(self):
        proc = subprocess.run(
            [sys.executable, HELPER], capture_output=True, text=True
        )
        assert proc.returncode == 2
        assert "Usage" in proc.stderr

    def test_cli_fusionne(self, tmp_path, reference):
        target = write_json(tmp_path, "settings.json", {"permissions": {"deny": []}})
        proc = subprocess.run(
            [sys.executable, HELPER, str(reference), str(target)],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["permissions"]["deny"] == REF_DENY


class TestReglesReelles:
    """La référence du repo doit rester une source valide pour la fusion."""

    def test_settings_du_repo_utilisable(self, tmp_path):
        repo_ref = os.path.join(
            os.path.dirname(__file__), "..", "login", "claude1a", "settings.json"
        )
        deny = mdr.load_deny(repo_ref)
        # Les 5 règles V3 (protection oracle) font partie de la référence
        for rule in [
            "Read(./bench/oracle/**)",
            "Write(./bench/oracle/**)",
            "Edit(./bench/oracle/**)",
            "Write(./pool-requests/tests/**)",
            "Edit(./pool-requests/tests/**)",
        ]:
            assert rule in deny
