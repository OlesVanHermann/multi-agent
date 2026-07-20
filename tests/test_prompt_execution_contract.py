"""Contrat de prompts : priorité opérateur et exécution événementielle."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_agent_executes_direct_cli_commands_without_redis_reply():
    agent = read("prompts/AGENT.md")
    assert "Commande directe de l'utilisateur (`FROM=cli`)" in agent
    assert "Réponds directement dans le TUI" in agent
    assert "N'exécute jamais `send.sh cli`, `done.sh cli`" in agent
    assert "hors mission" in agent


def test_memory_is_context_not_a_permanent_whitelist():
    agent = read("prompts/AGENT.md")
    rules = read("prompts/RULES.md")
    template = read("templates/x45/prompts/AGENT.md")
    assert "jamais une whitelist permanente" in agent
    assert "pas comme des whitelists permanentes" in rules
    assert "snapshot de contexte, jamais une whitelist permanente" in template


def test_rules_have_no_periodic_progress_or_single_file_constraint():
    rules = read("prompts/RULES.md")
    assert "1 LIVRABLE LOGIQUE" in rules
    assert "exactement un fichier" not in rules
    assert "PROGRESS` uniquement lors d'un événement métier réel" in rules
    assert "toutes les 30 minutes" not in rules


def test_generators_emit_event_driven_non_blocking_contract():
    x45 = read("prompts/160-create-x45/160-160-system.md")
    z21 = read("prompts/170-create-z21/170-170-system.md")
    mono = read("prompts/150-create-mono/150-150-system.md")
    for generated in (x45, z21):
        assert "snapshot, pas whitelist" in generated
        assert "aucun timeout/re-dispatch" in generated
    assert "Pour `FROM=cli`, répondre uniquement dans le TUI" in mono
    assert "done.sh \"$FROM\" DONE" in mono
