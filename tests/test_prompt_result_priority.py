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
        assert "autorité décisionnelle finale" in text
        assert "dispatcher l'implémentation du code à un `3XX`" in text
        assert "Master dispatche en parallèle `7XX`" in text


def test_all_installed_system_prompts_preserve_user_authority():
    files = sorted((ROOT / "prompts").glob("*/*-system.md"))
    assert files
    missing = [str(path.relative_to(ROOT)) for path in files
               if REBALANCE.USER_AUTHORITY_MARKER not in
               path.read_text(errors="replace")]
    assert missing == []


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


def test_migration_adds_dev_test_and_parallel_post_validation(tmp_path):
    directory = tmp_path / "prompts" / "321-demo"
    directory.mkdir(parents=True)
    paths = {
        role: directory / f"321-{suffix}-system.md"
        for role, suffix in {
            "master": "121", "developer": "321", "tester": "521",
            "curator": "721", "coach": "821", "architect": "921",
        }.items()
    }
    for role, path in paths.items():
        path.write_text(f"# 321 — {role.title()}\n")

    REBALANCE.migrate(tmp_path, backup=False)

    assert "dispatche l'implémentation à un `3XX`" in paths["master"].read_text()
    assert "dispatche `7XX`, `8XX` et `9XX` en parallèle" in paths["master"].read_text()
    assert "nouvelle version testable au `5XX`" in paths["developer"].read_text()
    assert "version exacte livrée par le `3XX`" in paths["tester"].read_text()
    assert "ne conçois, n'écris ni n'exécute les tests" in paths["developer"].read_text()
    assert "seul responsable de toutes les phases de test" in paths["tester"].read_text()
    assert "Travaille en parallèle des `8XX`" in paths["curator"].read_text()
    assert "Travaille en parallèle des `7XX`" in paths["coach"].read_text()
    assert "Le Master attend leurs trois terminaux" in paths["architect"].read_text()
    assert all(REBALANCE.USER_AUTHORITY_MARKER in path.read_text()
               for path in paths.values())
    assert REBALANCE.migrate(tmp_path, backup=False) == []


def test_upgrade_adds_periodic_optimizer_and_suspended_task(tmp_path):
    directory = tmp_path / "prompts" / "348-demo"
    directory.mkdir(parents=True)
    master = directory / "348-148-system.md"
    contradictor = directory / "348-248-system.md"
    methodology = directory / "348-248-methodology.md"
    master.write_text("# Master\n")
    contradictor.write_text("# Contradictor\n")
    methodology.write_text(
        f"# Methodology\n\n{REBALANCE.CONTRADICTOR_METHOD_MARKER}\n\n"
        f"{REBALANCE.CONTRADICTOR_FALLBACK_MARKER}\n"
    )
    crontab = tmp_path / "crontab"
    crontab.mkdir()

    REBALANCE.migrate(tmp_path, backup=False)

    assert REBALANCE.PERIODIC_OPTIMIZER_MARKER in contradictor.read_text()
    assert REBALANCE.PERIODIC_OPTIMIZER_MARKER in methodology.read_text()
    task = crontab / "348-248_360.prompt.suspended"
    assert task.is_file()
    assert not (crontab / "348-248_360.prompt").exists()
    assert not (crontab / "348-148_120.prompt.suspended").exists()
    assert REBALANCE.migrate(tmp_path, backup=False) == []


def test_migration_replaces_v3212_communication_contract(tmp_path):
    directory = tmp_path / "prompts" / "345-demo"
    directory.mkdir(parents=True)
    prompt = directory / "345-345-system.md"
    prompt.write_text(
        "# 345-345 — Developer\n\n"
        "## Priorité au résultat\n\nContrat existant.\n\n"
        "## Contrat de communication utile — v3.2.12\n\n"
        "MASTER_REPORT ne réveille jamais.\n"
    )

    assert REBALANCE.migrate(tmp_path, backup=False) == [prompt]
    text = prompt.read_text()
    assert "Contrat de communication utile — v3.2.19" in text
    assert "Contrat de communication utile — v3.2.12" not in text
    assert "DECISION_REQUIRED" in text
    assert REBALANCE.migrate(tmp_path, backup=False) == []


def test_migration_expands_contradictor_scope_but_keeps_master_as_recipient(tmp_path):
    directory = tmp_path / "prompts" / "345-demo"
    directory.mkdir(parents=True)
    contradictor = directory / "345-245-system.md"
    contradictor.write_text(
        "# 345-245 — Contradictor\n\n## Priorité au résultat\n\nAncien contrat.\n"
    )
    assert REBALANCE.migrate(tmp_path, backup=False) == [contradictor]
    text = contradictor.read_text()
    assert "tous les agents `NNN-YXX`" in text
    assert "demande adressée par l'utilisateur" in text
    assert "plan de développement ou correction" in text
    assert "seul destinataire autorisé" in text
    assert REBALANCE.migrate(tmp_path, backup=False) == []


def test_migration_updates_existing_contradictor_methodology(tmp_path):
    directory = tmp_path / "prompts" / "345-demo"
    directory.mkdir(parents=True)
    methodology = directory / "345-245-methodology.md"
    methodology.write_text("# Méthodologie Contradictor\n\nAncien ordre.\n")
    changed = REBALANCE.migrate(tmp_path, backup=True)
    assert methodology in changed
    text = methodology.read_text()
    assert "Méthode d'audit utilisateur — v3.2.7" in text
    assert "USER_REQUEST" in text
    assert REBALANCE.migrate(tmp_path, backup=True) == []
    backups = list(
        (tmp_path / "removed" / "rebalance-prompts").rglob(
            "345-245-methodology.md"))
    assert len(backups) == 1


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
    path = ROOT / "docs" / "HOW_TO_WRITE_AND_REWRITE_PROMPTS.md"
    text = path.read_text()
    assert "70 % résultat métier" in text
    assert "Obligations des créateurs 150, 160 et 170" in text
    assert "Intégration automatique dans `upgrade.sh`" in text
    assert "Promotion mx9 vers la release publique" in text
