"""Contrat de statistiques temporelles des actions."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text()


def test_agent_contract_reports_action_and_total_durations():
    agent = read("prompts/AGENT.md")
    template = read("templates/x45/prompts/AGENT.md")
    claude = read("CLAUDE.md")
    for text in (agent, template, claude):
        assert "durée" in text.lower()
        assert "total" in text.lower()
        assert "NON MESURÉ" in text


def test_install_and_upgrade_document_durable_timing_log():
    install = read("setup/HOW_TO_SETUP.md")
    upgrade = read("patch/HOW_TO_UPGRADE.md")
    for text in (install, upgrade):
        assert "logs/action-timings.tsv" in text
        assert "attente" in text
    assert "duration_seconds" in install
    assert "dry-run" in upgrade


def test_upgrade_script_measures_phases_and_persists_only_real_run():
    source = read("patch/upgrade.sh")
    for phase in (
        "telechargement", "integrite", "inventaire", "sauvegarde",
        "synchronisation", "migrations", "dependances", "total",
    ):
        assert f'"{phase}"' in source
    assert "UPGRADE_STARTED=$SECONDS" in source
    assert "timing_summary false" in source
    assert "timing_summary true" in source
    assert "logs/action-timings.tsv" in source
    assert "logs/action-timings" in source
    assert "%Y%m%dT%H%M%S%6NZ" in source
    assert "-upgrade.tsv" in source


def test_timestamped_immutable_copy_convention_is_documented():
    for path in (
        "CLAUDE.md", "prompts/AGENT.md", "templates/x45/prompts/AGENT.md",
        "setup/HOW_TO_SETUP.md", "patch/HOW_TO_UPGRADE.md",
    ):
        text = read(path)
        assert "YYYYMMDDTHHMMSSffffffZ" in text
        assert "prompt" in text.lower()
    assert "Ne jamais horodater un fichier de" in read("CLAUDE.md")
    assert "N'horodate jamais un fichier de prompt" in read("prompts/AGENT.md")


def test_plan_identity_is_timestamped_once_and_stable_across_transitions():
    documentation = read("docs/PLAN-LIFECYCLE.md")
    agent = read("prompts/AGENT.md")
    for text in (documentation, agent):
        assert "plan-TODO" in text
        assert "plan-DOING" in text
        assert "plan-DONE" in text
        assert "created_at" in text
        assert "started_at" in text
        assert "completed_at" in text
        assert "logs/plan-lifecycle.tsv" in text
    assert "conserve ce nom" in agent
    normalized = " ".join(documentation.split())
    assert "ne s'applique jamais aux fichiers de prompts" in normalized
