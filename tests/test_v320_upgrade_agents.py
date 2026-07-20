import importlib.util
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATOR_PATH = ROOT / "patch" / "migrate-v320-agents.py"
SPEC = importlib.util.spec_from_file_location("migrate_v320_agents", MIGRATOR_PATH)
MIGRATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATOR)


def make_base(tmp_path):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts" / "scaffold-mono-pair.py", tmp_path / "scripts")
    shutil.copy2(ROOT / "scripts" / "scaffold-observers.py", tmp_path / "scripts")
    source = ROOT / "templates" / "x45"
    shutil.copytree(source, tmp_path / "templates" / "x45")
    for name in ("fable-5.model", "gpt-5-6-sol.model", "login1a.login", "codex3a.login"):
        (tmp_path / "prompts" / name).write_text(name + "\n")
    for name in ("agent_mono.type", "agent_x45.type", "agent_z21.type"):
        (tmp_path / "prompts" / name).touch()
    return tmp_path


def test_migrates_legacy_mono_to_pair_idempotently(tmp_path):
    base = make_base(tmp_path)
    directory = base / "prompts" / "321-demo"
    directory.mkdir()
    (directory / "agent.type").symlink_to("../agent_mono.type")
    (directory / "321-demo.md").write_text("# 321 legacy principal\n")
    (directory / "321-demo.model").symlink_to("../fable-5.model")
    (directory / "321-demo.login").symlink_to("../login1a.login")

    actions, manual = MIGRATOR.plan(base)
    assert manual == []
    assert [item[0] for item in actions] == ["mono"]
    MIGRATOR.apply(base, actions)

    assert (directory / "321-121-system.md").is_file()
    assert (directory / "321-221-system.md").is_file()
    assert (directory / "mono-pair.json").is_file()
    assert MIGRATOR.plan(base) == ([], [])


def test_adds_contradictor_to_existing_x45_idempotently(tmp_path):
    base = make_base(tmp_path)
    directory = base / "prompts" / "427-project"
    directory.mkdir()
    (directory / "agent.type").symlink_to("../agent_x45.type")
    (directory / "427-127-system.md").write_text("# Master\n")
    (directory / "427-427-system.md").write_text("# Developer\n")

    actions, manual = MIGRATOR.plan(base)
    assert manual == []
    assert actions == [("x45", "427", "427-project", "127", "227")]
    MIGRATOR.apply(base, actions)

    assert (directory / "427-227-system.md").is_file()
    assert "427-127" in (directory / "427-227-system.md").read_text()
    assert MIGRATOR.plan(base) == ([], [])


def test_ambiguous_triangle_is_manual_and_not_migrated(tmp_path):
    base = make_base(tmp_path)
    directory = base / "prompts" / "428-project"
    directory.mkdir()
    (directory / "agent.type").symlink_to("../agent_z21.type")
    (directory / "428-128-system.md").write_text("# Master A\n")
    (directory / "428-129-system.md").write_text("# Master B\n")
    (directory / "428-428-system.md").write_text("# Developer\n")

    actions, manual = MIGRATOR.plan(base)
    assert actions == []
    assert len(manual) == 1
    assert "2 Master" in manual[0]


def test_isolated_unmarked_developer_is_not_treated_as_triangle(tmp_path):
    base = make_base(tmp_path)
    directory = base / "prompts" / "300-dev-streaming"
    directory.mkdir()
    (directory / "300-300-system.md").write_text("# Developer isolé\n")
    assert MIGRATOR.plan(base) == ([], [])


def test_released_prompt_topologies_are_already_migrated():
    """Un clone neuf v3.2 ne doit dépendre d'aucune passe d'upgrade."""
    assert MIGRATOR.plan(ROOT) == ([], [])
