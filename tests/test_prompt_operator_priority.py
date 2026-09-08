from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOADERS = (
    ROOT / "prompts" / "AGENT.md",
    ROOT / "templates" / "x45" / "prompts" / "AGENT.md",
    ROOT / "examples" / "3-x45-simple" / "prompts" / "AGENT.md",
    ROOT / "examples" / "4-x45-complet" / "prompts" / "AGENT.md",
)


def test_x45_loaders_prioritize_direct_user_execution():
    for path in LOADERS:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        assert "mandat" in lowered and "utilisateur" in lowered, path
        assert "from=cli" in lowered, path
        assert "not_run" in lowered, path


def test_x45_loaders_do_not_make_memory_an_exhaustive_authority():
    forbidden = (
        "tu utilises uniquement les informations de ton memory.md",
        "tu utilises uniquement les informations de memory.md",
        "tu ne fais que ce qui est décrit dans ton system.md",
        "tu ne fais que ce qui est décrit dans system.md",
        "n'exécute pas de tâches hors de ton system.md",
        "n'exécute pas de tâches hors de system.md",
    )
    for path in LOADERS:
        lowered = path.read_text(encoding="utf-8").lower()
        for phrase in forbidden:
            assert phrase not in lowered, f"{path}: {phrase}"
