import importlib.util
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "codex_session_audit", ROOT / "scripts" / "audit-codex-sessions.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def profile(base, name, token, refresh):
    directory = base / "login" / name
    directory.mkdir(parents=True)
    (directory / "auth.json").write_text(json.dumps({
        "tokens": {
            "access_token": token,
            "refresh_token": refresh,
        },
        "auth_mode": "chatgpt",
        "last_refresh": "2026-07-26T12:00:00Z",
        "account_id": f"secret-{name}",
    }))
    return directory


def test_apply_preserves_config_and_never_exposes_credentials(tmp_path, monkeypatch):
    directory = profile(tmp_path, "codex1a", "access-secret", "refresh-secret")
    config = directory / "config.toml"
    config.write_text('model = "gpt-test"\nforced_login_method = "api"\n')
    monkeypatch.setattr(MODULE, "login_status",
                        lambda base, name: "Logged in using ChatGPT")
    monkeypatch.setattr(MODULE, "codex_version", lambda base: "codex-cli test")

    report = MODULE.audit(tmp_path, apply=True, no_log=True)

    text = config.read_text()
    assert 'model = "gpt-test"' in text
    assert 'forced_login_method = "chatgpt"' in text
    assert 'cli_auth_credentials_store = "file"' in text
    assert f"{directory.stat().st_mode & 0o777:03o}" == "700"
    assert f"{config.stat().st_mode & 0o777:03o}" == "600"
    assert f"{(directory / 'auth.json').stat().st_mode & 0o777:03o}" == "600"
    encoded = json.dumps(report)
    assert "access-secret" not in encoded
    assert "refresh-secret" not in encoded
    assert "secret-codex1a" not in encoded
    assert report["after"]["codex1a"]["auth_metadata"]["has_refresh_token"] is True


def test_detects_identical_credentials_without_hash_or_content(tmp_path, monkeypatch):
    first = profile(tmp_path, "codex1a", "same", "same-refresh")
    second = profile(tmp_path, "codex3a", "other", "other-refresh")
    (second / "auth.json").write_bytes((first / "auth.json").read_bytes())
    monkeypatch.setattr(MODULE, "login_status",
                        lambda base, name: "Logged in using ChatGPT")
    monkeypatch.setattr(MODULE, "codex_version", lambda base: "codex-cli test")

    report = MODULE.audit(tmp_path, apply=False, no_log=True)

    assert report["duplicate_credentials"] == [["codex1a", "codex3a"]]
    encoded = json.dumps(report)
    assert "same-refresh" not in encoded
    assert "sha256" not in encoded.lower()


def test_active_profiles_include_references_and_existing_auth(tmp_path):
    profile(tmp_path, "codex4a", "a", "r")
    prompt_dir = tmp_path / "prompts" / "345-demo"
    prompt_dir.mkdir(parents=True)
    root_login = tmp_path / "prompts" / "codex3a.login"
    root_login.write_text("codex3a\n")
    (prompt_dir / "345-145.login").symlink_to(Path("..") / "codex3a.login")

    assert MODULE.active_profiles(tmp_path) == ["codex3a", "codex4a"]


def test_upgrade_invokes_safe_apply():
    source = (ROOT / "patch" / "upgrade.sh").read_text()
    assert "audit-codex-sessions.py" in source
    assert '"$CODEX_SESSION_AUDIT" --base "$(pwd)" --apply' in source
    assert "login --device-auth" not in source
