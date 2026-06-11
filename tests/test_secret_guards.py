"""
D3 — Anti-fuite de secrets

check-secrets.sh bloque : secrets.cfg tracké, valeurs par défaut dans
setup/secrets.cfg. hub-release.sh l'exécute avant toute release ;
security.yml le rejoue en CI avec un scan gitleaks de l'historique.
"""
import os
import shutil
import subprocess

import yaml

BASE = os.path.join(os.path.dirname(__file__), '..')
SCRIPT = os.path.join(BASE, 'patch', 'check-secrets.sh')


def _read(rel):
    with open(os.path.join(BASE, rel), encoding="utf-8") as f:
        return f.read()


def _make_repo(tmp_path):
    """Repo git minimal avec le script sous patch/ (BASE = racine du repo)."""
    (tmp_path / "patch").mkdir()
    (tmp_path / "setup").mkdir()
    shutil.copy(SCRIPT, tmp_path / "patch" / "check-secrets.sh")
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    return tmp_path


def _run(repo):
    return subprocess.run(["bash", "patch/check-secrets.sh"], cwd=repo,
                          capture_output=True, text=True)


class TestCheckSecretsScript:
    def test_clean_repo_passes(self, tmp_path):
        repo = _make_repo(tmp_path)
        r = _run(repo)
        assert r.returncode == 0, r.stdout + r.stderr

    def test_default_values_blocked(self, tmp_path):
        repo = _make_repo(tmp_path)
        (repo / "setup" / "secrets.cfg").write_text(
            "KEYCLOAK_ADMIN_PASSWORD=changeme\nHEALTH_TOKEN=abc123strong\n")
        r = _run(repo)
        assert r.returncode == 1
        assert "Valeurs par défaut" in r.stdout

    def test_empty_value_blocked(self, tmp_path):
        repo = _make_repo(tmp_path)
        (repo / "setup" / "secrets.cfg").write_text(
            "KEYCLOAK_ADMIN_PASSWORD=Str0ng!pass\nHEALTH_TOKEN=\n")
        r = _run(repo)
        assert r.returncode == 1

    def test_strong_values_pass(self, tmp_path):
        repo = _make_repo(tmp_path)
        (repo / "setup" / "secrets.cfg").write_text(
            "KEYCLOAK_ADMIN_PASSWORD=Str0ng!pass\nHEALTH_TOKEN=tok_8f3a2b\n")
        r = _run(repo)
        assert r.returncode == 0, r.stdout + r.stderr

    def test_tracked_secrets_cfg_blocked(self, tmp_path):
        repo = _make_repo(tmp_path)
        (repo / "setup" / "secrets.cfg").write_text(
            "KEYCLOAK_ADMIN_PASSWORD=Str0ng!pass\nHEALTH_TOKEN=tok_8f3a2b\n")
        subprocess.run(["git", "-C", str(repo), "add", "setup/secrets.cfg"],
                       check=True)
        r = _run(repo)
        assert r.returncode == 1
        assert "tracké par git" in r.stdout

    def test_real_repo_currently_clean(self):
        r = subprocess.run(["bash", "patch/check-secrets.sh"], cwd=BASE,
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr


class TestReleaseGuard:
    def test_release_runs_secret_check_before_tests(self):
        src = _read("patch/hub-release.sh")
        assert "./patch/check-secrets.sh" in src
        assert src.index("check-secrets.sh") < src.index("pytest")
        assert "Secret check FAILED" in src


class TestCiWorkflow:
    def test_workflow_valid_yaml_with_gitleaks(self):
        wf = yaml.safe_load(_read(".github/workflows/security.yml"))
        jobs = wf["jobs"]
        assert "gitleaks" in jobs
        steps = jobs["gitleaks"]["steps"]
        assert any("gitleaks/gitleaks-action" in s.get("uses", "") for s in steps)
        # fetch-depth: 0 → scan de tout l'historique
        assert any(s.get("with", {}).get("fetch-depth") == 0 for s in steps)

    def test_workflow_reruns_check_secrets(self):
        src = _read(".github/workflows/security.yml")
        assert "./patch/check-secrets.sh" in src

    def test_workflow_triggers_on_push_and_pr(self):
        wf = yaml.safe_load(_read(".github/workflows/security.yml"))
        triggers = wf.get("on", wf.get(True))  # yaml 1.1 : "on" → True
        assert "push" in triggers and "pull_request" in triggers
