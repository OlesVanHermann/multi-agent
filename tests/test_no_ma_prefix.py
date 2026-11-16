"""v3.1.17 — l'adressage runtime est canonique, sans MA_PREFIX."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOTS = ("scripts", "web/backend", "bench", "framework")
ALLOWED = {
    ROOT / "patch" / "migrate-agent-addresses.sh",  # migration historique
}


def test_runtime_sources_do_not_use_ma_prefix():
    offenders = []
    for relative in RUNTIME_ROOTS:
        for path in (ROOT / relative).rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".sh"} or path in ALLOWED:
                continue
            if "MA_PREFIX" in path.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_upgrade_runs_address_migration_when_redis_is_available():
    source = (ROOT / "patch" / "upgrade.sh").read_text()
    assert 'migrate-agent-addresses.sh' in source
    assert 'bash "$ADDRESS_MIGRATION" --apply' in source
