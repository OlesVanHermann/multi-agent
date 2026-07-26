#!/usr/bin/env python3
"""Audit/correction sûre de la persistance des profils Codex multi-comptes.

Le rapport ne contient jamais de token, de hash de credentials ni
d'identifiant de compte.
"""

import argparse
import json
import os
import pwd
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


PROFILE_RE = re.compile(r"^codex[1-4][ab]$")
CONFIG_VALUES = {
    "forced_login_method": '"chatgpt"',
    "cli_auth_credentials_store": '"file"',
}


def utc_now():
    return datetime.now(timezone.utc)


def timestamp():
    return utc_now().strftime("%Y%m%dT%H%M%S%fZ")


def referenced_profiles(base):
    result = set()
    for path in (base / "prompts").glob("*/*.login"):
        try:
            value = path.resolve().stem if path.is_symlink() else path.read_text().strip()
        except OSError:
            continue
        value = Path(value).stem
        if PROFILE_RE.fullmatch(value):
            result.add(value)
    return result


def active_profiles(base):
    result = referenced_profiles(base)
    login = base / "login"
    if login.is_dir():
        result.update(
            path.parent.name for path in login.glob("codex[1-4][ab]/auth.json")
            if PROFILE_RE.fullmatch(path.parent.name)
        )
    return sorted(result)


def nested_values(value, wanted):
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower().replace("-", "_")
            if normalized in wanted:
                found.append(child)
            found.extend(nested_values(child, wanted))
    elif isinstance(value, list):
        for child in value:
            found.extend(nested_values(child, wanted))
    return found


def auth_metadata(path):
    metadata = {
        "exists": path.is_file(),
        "auth_mode": "unknown",
        "has_refresh_token": False,
        "last_refresh": None,
    }
    if not path.is_file():
        return metadata
    try:
        content = json.loads(path.read_text())
    except (OSError, ValueError):
        metadata["auth_mode"] = "invalid-json"
        return metadata
    refresh = nested_values(content, {"refresh_token", "refreshtoken"})
    metadata["has_refresh_token"] = any(
        isinstance(value, str) and bool(value) for value in refresh)
    modes = nested_values(
        content, {"auth_mode", "authmode", "login_method", "loginmethod"})
    mode_text = " ".join(str(value).lower() for value in modes)
    if "chatgpt" in mode_text or metadata["has_refresh_token"]:
        metadata["auth_mode"] = "chatgpt"
    elif "api" in mode_text:
        metadata["auth_mode"] = "api-key"
    refresh_dates = nested_values(
        content, {"last_refresh", "lastrefresh", "last_refresh_at"})
    if refresh_dates:
        value = refresh_dates[-1]
        if isinstance(value, (str, int, float)):
            metadata["last_refresh"] = str(value)[:64]
    return metadata


def file_metadata(path):
    if not path.exists():
        return {"exists": False, "owner": None, "permissions": None}
    stat = path.stat()
    try:
        owner = pwd.getpwuid(stat.st_uid).pw_name
    except KeyError:
        owner = str(stat.st_uid)
    return {
        "exists": True,
        "owner": owner,
        "permissions": f"{stat.st_mode & 0o777:03o}",
    }


def config_flags(path):
    text = path.read_text(errors="replace") if path.is_file() else ""
    return {
        key: bool(re.search(
            rf"(?m)^\s*{re.escape(key)}\s*=\s*{re.escape(value)}\s*(?:#.*)?$",
            text,
        ))
        for key, value in CONFIG_VALUES.items()
    }


def update_config(path):
    text = path.read_text(errors="replace") if path.is_file() else ""
    changed = False
    for key, value in CONFIG_VALUES.items():
        pattern = re.compile(rf"(?m)^\s*{re.escape(key)}\s*=.*$")
        replacement = f"{key} = {value}"
        if pattern.search(text):
            updated = pattern.sub(replacement, text)
            changed |= updated != text
            text = updated
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += replacement + "\n"
            changed = True
    if changed or not path.exists():
        temporary = path.with_name(f".{path.name}.{timestamp()}.tmp")
        temporary.write_text(text)
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    return changed


def login_status(base, profile):
    env = os.environ.copy()
    env["CODEX_HOME"] = str(base / "login" / profile)
    env.pop("OPENAI_API_KEY", None)
    env.pop("CODEX_API_KEY", None)
    try:
        result = subprocess.run(
            ["codex", "login", "status"], cwd=base, env=env, text=True,
            capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    output = f"{result.stdout}\n{result.stderr}"
    if "Logged in using ChatGPT" in output:
        return "Logged in using ChatGPT"
    if result.returncode == 0:
        return "logged-in-other-method"
    return "not-logged-in"


def codex_version(base):
    try:
        result = subprocess.run(
            ["codex", "--version"], cwd=base, text=True, capture_output=True,
            timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    line = (result.stdout or result.stderr).strip().splitlines()
    return line[0][:120] if line else "unavailable"


def duplicate_credentials(base, profiles):
    contents = {}
    for profile in profiles:
        path = base / "login" / profile / "auth.json"
        if path.is_file():
            try:
                contents[profile] = path.read_bytes()
            except OSError:
                pass
    duplicates = []
    names = sorted(contents)
    for index, first in enumerate(names):
        for second in names[index + 1:]:
            if contents[first] == contents[second]:
                duplicates.append([first, second])
    return duplicates


def append_timing(base, timings, report, no_log):
    if no_log:
        return None
    log = base / "logs" / "action-timings.tsv"
    archive = base / "logs" / "codex-session-audit"
    log.parent.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)
    if not log.exists():
        log.write_text(
            "timestamp\taction\tphase\tduration_seconds\tstatus\tdetails\n")
    with log.open("a") as stream:
        for phase, duration in timings.items():
            stream.write(
                f"{utc_now().isoformat()}\tcodex-session-audit\t{phase}\t"
                f"{duration:.6f}\tOK\t{len(report['profiles'])} profils\n")
    destination = archive / f"{timestamp()}-codex-session-audit.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    os.chmod(destination, 0o600)
    return destination


def audit(base, apply=False, no_log=False):
    total_start = time.monotonic()
    profiles = active_profiles(base)
    inspection_start = time.monotonic()
    initial = {}
    for profile in profiles:
        directory = base / "login" / profile
        initial[profile] = {
            "directory": file_metadata(directory),
            "config": file_metadata(directory / "config.toml"),
            "auth": file_metadata(directory / "auth.json"),
            "auth_metadata": auth_metadata(directory / "auth.json"),
            "config_flags": config_flags(directory / "config.toml"),
        }
    inspection_duration = time.monotonic() - inspection_start

    correction_start = time.monotonic()
    corrected = []
    if apply:
        for profile in profiles:
            directory = base / "login" / profile
            directory.mkdir(parents=True, exist_ok=True)
            os.chmod(directory, 0o700)
            if update_config(directory / "config.toml"):
                corrected.append(profile)
            os.chmod(directory / "config.toml", 0o600)
            auth = directory / "auth.json"
            if auth.is_file():
                os.chmod(auth, 0o600)
    correction_duration = time.monotonic() - correction_start

    checks_start = time.monotonic()
    final = {}
    for profile in profiles:
        directory = base / "login" / profile
        final[profile] = {
            "directory": file_metadata(directory),
            "config": file_metadata(directory / "config.toml"),
            "auth": file_metadata(directory / "auth.json"),
            "auth_metadata": auth_metadata(directory / "auth.json"),
            "config_flags": config_flags(directory / "config.toml"),
            "login_status": login_status(base, profile),
            "codex_home": str(directory),
        }
    duplicates = duplicate_credentials(base, profiles)
    checks_duration = time.monotonic() - checks_start
    timings = {
        "inspection": inspection_duration,
        "corrections": correction_duration,
        "checks": checks_duration,
        "total": time.monotonic() - total_start,
    }
    report = {
        "schema": "multi-agent.codex-session-audit.v1",
        "created_at": utc_now().isoformat(),
        "mode": "apply" if apply else "check",
        "profiles": profiles,
        "corrected_profiles": corrected,
        "before": initial,
        "after": final,
        "duplicate_credentials": duplicates,
        "codex_version": codex_version(base),
        "timings_seconds": timings,
        "secrets_exposed": False,
        "services_restarted": False,
    }
    destination = append_timing(base, timings, report, no_log)
    if destination:
        report["report_path"] = str(destination.relative_to(base))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--no-log", action="store_true")
    args = parser.parse_args()
    report = audit(args.base.resolve(), args.apply, args.no_log)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["duplicate_credentials"]:
        print("\nRéauthentification humaine requise pour les profils dupliqués :")
        for pair in report["duplicate_credentials"]:
            for profile in pair:
                print(
                    f'CODEX_HOME="$PWD/login/{profile}" '
                    "codex login --device-auth"
                )


if __name__ == "__main__":
    main()
