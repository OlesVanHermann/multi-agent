import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REBALANCE_PATH = ROOT / "patch" / "rebalance-agent-prompts.py"
REBALANCE_SPEC = importlib.util.spec_from_file_location("rebalance", REBALANCE_PATH)
REBALANCE = importlib.util.module_from_spec(REBALANCE_SPEC)
REBALANCE_SPEC.loader.exec_module(REBALANCE)


def test_all_installed_system_prompts_are_result_first():
    files = sorted((ROOT / "prompts").glob("*/*-system.md"))
    assert files
    missing = [str(path.relative_to(ROOT)) for path in files
               if "## Priorité au résultat" not in path.read_text(errors="replace")]
    assert missing == []


def test_common_loader_prioritizes_outcome_and_silent_process():
    text = (ROOT / "prompts" / "AGENT.md").read_text()
    assert "La finalité métier domine les moyens" in text
    assert "Applique silencieusement les règles mécaniques" in text
    assert "résultat obtenu, puis ses preuves" in text


def test_creators_require_result_first_contract():
    paths = (
        ROOT / "prompts" / "150-create-mono" / "150-150-system.md",
        ROOT / "prompts" / "160-create-x45" / "160-160-system.md",
        ROOT / "prompts" / "170-create-z21" / "170-170-system.md",
    )
    for path in paths:
        text = path.read_text()
        assert "résultat-first" in text.lower()
        assert "résultat, preuves, limites" in text.lower()
        assert "hard gates et critères obligatoires" in text.lower()
        assert "score mou" in text.lower()


def test_loader_defines_evidence_driven_delivery_verdicts():
    text = (ROOT / "prompts" / "AGENT.md").read_text()
    for verdict in ("BLOCK_DEV", "READY_FOR_INTEGRATION",
                    "BLOCK_INTEGRATION", "ACCEPT_WITH_IMPROVEMENTS"):
        assert verdict in text
    assert "score qualitatif" in text
    assert "ne peut jamais, seul" in text


def test_migration_ignores_archives_and_document_templates():
    candidates = {item.relative_to(ROOT) for item in REBALANCE.candidates(ROOT)}
    assert not any("removed" in item.parts for item in candidates)
    assert not any(item.parts[:2] == ("templates", "knowledge") for item in candidates)
    assert Path("templates/prompts/3XX-developer.md.template") in candidates


def test_migration_is_idempotent_and_upgrades_creators(tmp_path):
    creator = tmp_path / "prompts" / "150-create-mono"
    creator.mkdir(parents=True)
    prompt = creator / "150-150-system.md"
    prompt.write_text("# Créateur mono\n\n## Mission\nCréer.\n")
    first = REBALANCE.migrate(tmp_path, backup=True)
    assert first == [prompt]
    text = prompt.read_text()
    assert "## Priorité au résultat" in text
    assert "## Contrat de création résultat-first" in text
    assert REBALANCE.migrate(tmp_path, backup=True) == []
    backups = list((tmp_path / "removed" / "rebalance-prompts").rglob("150-150-system.md"))
    assert len(backups) == 1


def test_migration_adds_role_specific_delivery_contracts(tmp_path):
    directory = tmp_path / "prompts" / "321-demo"
    directory.mkdir(parents=True)
    master = directory / "321-121-system.md"
    observer = directory / "321-521-system.md"
    coach = directory / "321-821-system.md"
    master.write_text("# 321-121 — Master\n")
    observer.write_text("# 321-521 — Observer\n")
    coach.write_text("# 321-821 — Coach\n")
    REBALANCE.migrate(tmp_path, backup=False)
    assert "READY_FOR_INTEGRATION" in master.read_text()
    assert "DEV_BLOCKERS" in observer.read_text()
    assert "ne bloque jamais" in coach.read_text()
    assert REBALANCE.migrate(tmp_path, backup=False) == []


def test_creators_do_not_route_cycles_from_soft_score_thresholds():
    paths = (
        ROOT / "prompts" / "160-create-x45" / "160-160-system.md",
        ROOT / "prompts" / "170-create-z21" / "170-170-system.md",
        ROOT / "prompts" / "170-create-z21" / "170-templates-satellites.md",
    )
    forbidden = ("Score < 98 →", "Score >= 98 x", "Score < 80 → retour")
    for path in paths:
        text = path.read_text()
        assert not any(item in text for item in forbidden), path


def test_upgrade_runs_prompt_migration_and_supports_dry_run():
    text = (ROOT / "patch" / "upgrade.sh").read_text()
    assert 'rebalance-agent-prompts.py' in text
    assert '--check' in text
    assert 'prompt-result-migration.log' in text
    assert 'MA_SKIP_PROMPT_REBALANCE' in text


def test_normative_prompt_rewrite_document_exists():
    path = ROOT / "docs" / "HOW TO WRITE AND REWRITE PROMPTS.md"
    text = path.read_text()
    assert "70 % résultat métier" in text
    assert "Obligations des créateurs 150, 160 et 170" in text
    assert "Intégration automatique dans `upgrade.sh`" in text
    assert "Promotion mx9 vers la release publique" in text
