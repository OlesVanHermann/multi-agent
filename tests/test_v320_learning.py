import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "agent-bridge"))
sys.path.insert(0, str(ROOT / "bench"))

import learning
import workflow_engine


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ablation = _load("v320_ablation", ROOT / "bench" / "ablation.py")
scaffold_mod = _load("v320_scaffold", ROOT / "scripts" / "scaffold-observers.py")
models_mod = _load("v320_models", ROOT / "scripts" / "configure-x45-models.py")
gate_mod = _load("v320_gate", ROOT / "bench" / "methodology_gate.py")
mono_pair_mod = _load("v320_mono_pair", ROOT / "scripts" / "scaffold-mono-pair.py")


def test_delta_prunes_only_proven_harmful_rule(tmp_path):
    path = tmp_path / "methodology.md"
    learning.update_delta(path, "R-001", "c1", body="Vérifier les sections")
    learning.update_delta(path, "R-001", "c2", effect="harmful")
    result = learning.update_delta(path, "R-001", "c3", effect="harmful")
    assert result == {"kept": 0, "pruned": 1}
    assert "R-001" not in path.read_text()
    assert list((tmp_path / ".archive").iterdir())


def test_skill_requires_two_independent_triangles(tmp_path):
    local = tmp_path / "local.md"
    local.write_text("skill")
    global_skill = tmp_path / "skills" / "shared.md"
    assert learning.promote_skill(local, global_skill, "341", 2, 0) is False
    assert not global_skill.exists()
    assert learning.promote_skill(local, global_skill, "342", 1, 0) is True
    assert global_skill.read_text() == "skill"


def test_ablation_attribution():
    arms = {name: {"green": value} for name, value in
            {"A": False, "B": True, "C": False, "D": False}.items()}
    assert ablation.attribute(arms) == "curator"
    for arm in arms.values():
        arm["green"] = False
    assert ablation.attribute(arms) == "contract"


def test_topology_variant_rewires_disabled_curator():
    wf = {"name": "x", "variants": {"no-curator": {
              "disable": ["curate"], "depends_on": {"dev": []}}},
          "steps": [
              {"name": "curate", "agent": "300-700", "prompt": "c"},
              {"name": "dev", "agent": "300-300", "prompt": "d",
               "depends_on": ["curate"]}]}
    selected = workflow_engine.select_variant(wf, "no-curator")
    assert list(workflow_engine.validate_workflow(selected)) == ["dev"]


def test_scaffold_is_parameterized_for_new_install(tmp_path):
    shutil = __import__("shutil")
    shutil.copytree(ROOT / "templates", tmp_path / "templates")
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    for name in ("gpt-5-6-sol.model", "fable-5.model", "login1a.login"):
        (prompts / name).write_text(name)
    (prompts / "AGENT.md").write_text("loader")
    target, workflow = scaffold_mod.scaffold(
        tmp_path, "427", "427-project", "login1a", "217")
    assert (target / "427-217-system.md").is_file()
    assert not (target / "427-842-methodology.md").exists()
    assert (target / "427-217.model").is_symlink()
    wf = __import__("yaml").safe_load(workflow.read_text())
    assert "427" in wf["name"]
    assert {step["agent"] for step in wf["steps"]} == {
        "427-727", "427-427", "427-527", "427-827"}
    assert "dual-observer" not in wf["variants"]
    workflow_engine.validate_workflow(workflow_engine.select_variant(wf, "baseline"))


def test_model_assignment_is_parameterized(tmp_path):
    prompts = tmp_path / "prompts"
    target = prompts / "427-project"
    target.mkdir(parents=True)
    assignments = {}
    for role, (suffix, model, login, effort) in models_mod.ROLE_DEFAULTS.items():
        (prompts / f"{model}.model").write_text(model)
        (prompts / f"{login}.login").write_text(login)
        assignments[role] = (suffix, model, login, effort)
    models_mod.configure(tmp_path, "427", "427-project", assignments)
    assert (target / "427-300.model").is_symlink()
    assert (target / "427-100.effort").read_text() == "H\n"
    assert all(effort == "H" for _suffix, _model, _login, effort
               in models_mod.ROLE_DEFAULTS.values())


def test_role_suffixes_follow_triangle_number():
    assert models_mod.suffix_for_triangle("100", "301") == "101"
    assert models_mod.suffix_for_triangle("800", "302") == "802"


def test_x45_z21_role_model_matrix():
    assert models_mod.ROLE_DEFAULTS == {
        "master": ("100", "fable-5", "login3a", "H"),
        "contradictor": ("200", "gpt-5-6-sol", "login3a", "H"),
        "developer": ("300", "gpt-5-6-sol", "login1a", "H"),
        "observer": ("500", "fable-5", "login2a", "H"),
        "curator": ("700", "fable-5", "login4a", "H"),
        "coach": ("800", "gpt-5-6-sol", "login2a", "H"),
        "architect": ("900", "fable-5", "login4a", "H"),
    }


def test_topology_assignments_use_existing_role_suffixes(tmp_path):
    directory = tmp_path / "161-project"
    directory.mkdir()
    for suffix in ("161", "261", "361", "561", "761", "861", "961"):
        (directory / f"161-{suffix}-system.md").write_text("role\n")
    assignments = models_mod.topology_assignments(directory, "161")
    by_suffix = {value[0]: value[1:3] for value in assignments.values()}
    assert by_suffix == {
        "161": ("fable-5", "login3a"),
        "261": ("gpt-5-6-sol", "login3a"),
        "361": ("gpt-5-6-sol", "login1a"),
        "561": ("fable-5", "login2a"),
        "761": ("fable-5", "login4a"),
        "861": ("gpt-5-6-sol", "login2a"),
        "961": ("fable-5", "login4a"),
    }


def test_shipped_x45_z21_model_matrix_is_converged():
    assert models_mod.configure_all(ROOT, check=True) == []


def test_upgrade_applies_role_model_matrix():
    upgrade = (ROOT / "patch" / "upgrade.sh").read_text()
    assert 'configure-x45-models.py' in upgrade
    assert '--all' in upgrade


def test_methodology_gate_archives_non_significant_candidate(tmp_path, monkeypatch):
    results = tmp_path / "results"
    results.mkdir()
    harness = {"sealed_git": True, "sealed_net": True}
    for label in ("ref", "cand"):
        rows = [{"task": f"t{i}", "success": True, "cycles_to_green": 1,
                 "wall_s": 1, "harness": harness} for i in range(3)]
        (results / f"{label}.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows))
    monkeypatch.setattr(gate_mod.aggregate, "RESULTS", str(results))
    verdict, paired = gate_mod.decision("cand", "ref")
    assert verdict == "archived"
    assert paired["metrics"]["success_rate"]["ci95"] == [0, 0]


def test_mono_is_compound_main_plus_contradictor(tmp_path):
    shutil = __import__("shutil")
    shutil.copytree(ROOT / "templates", tmp_path / "templates")
    prompts = tmp_path / "prompts"
    mono = prompts / "345-example"
    mono.mkdir(parents=True)
    (mono / "345-example.md").write_text("principal")
    (mono / "345-example.model").write_text("fable-5")
    (mono / "345-example.login").write_text("login1a")
    (prompts / "fable-5.model").write_text("claude-fable-5")
    (prompts / "login1a.login").write_text("login1a")
    (prompts / "gpt-5-6-sol.model").write_text("gpt-5.6-sol")
    main, contradictor = mono_pair_mod.scaffold(
        tmp_path, "345", "145", "245", "345-example", "gpt-5-6-sol", "login1a")
    assert (main, contradictor) == ("345-145", "345-245")
    assert (mono / "345-145-system.md").read_text() == "principal"
    assert (mono / "345-145-memory.md").is_file()
    assert (mono / "345-145-methodology.md").is_file()
    assert (mono / "345-145.md").is_symlink()
    assert (mono / "345-145.model").read_text() == "claude-fable-5"
    assert (mono / "345-145.login").read_text() == "login1a"
    assert "Contradictor" in (mono / "345-245-system.md").read_text()
    assert (mono / "345-245-memory.md").is_file()
    assert (mono / "345-245-methodology.md").is_file()
    assert (mono / "345-245.md").is_symlink()
    assert (mono / "345-245.model").read_text() == "gpt-5.6-sol"
    assert (mono / "345-245.login").read_text() == "login1a"
    assert not (mono / "345-example.md").exists()
    assert json.loads((mono / "mono-pair.json").read_text())["main"] == main


def test_mono_suffixes_are_derived_from_group():
    assert mono_pair_mod.default_suffixes("150") == ("150", "250")
    assert mono_pair_mod.default_suffixes("300") == ("100", "200")
    assert mono_pair_mod.default_suffixes("345") == ("145", "245")


def test_creators_require_local_observers_and_mono_pair():
    x45 = (ROOT / "prompts/160-create-x45/160-160-system.md").read_text()
    z21 = (ROOT / "prompts/170-create-z21/170-170-system.md").read_text()
    mono = (ROOT / "prompts/150-create-mono/150-150-system.md").read_text()
    assert "scaffold-observers.py" in x45 and "NNN-2XX" in x45
    assert "scaffold-observers.py" in z21 and "NNN-2XX" in z21
    assert "scaffold-mono-pair.py" in mono
    assert "principal `3XX-1XX`" in mono
    assert "Contradictor `3XX-2XX`" in mono
    assert "fable-5" in mono and "gpt-5-6-sol" in mono
    assert "Master `NNN-1XX` = `fable-5.model`" in x45
    assert "Contradictor `NNN-2XX` = `gpt-5-6-sol.model`" in x45
    assert "Master `NNN-1XX` = `fable-5.model`" in z21
    assert "Contradictor `NNN-2XX` = `gpt-5-6-sol.model`" in z21


def test_installed_topologies_have_two_or_seven_agents():
    for directory in ROOT.joinpath("prompts").iterdir():
        type_link = directory / "agent.type"
        if not directory.is_dir() or not type_link.is_symlink():
            continue
        prefix = directory.name[:3]
        kind = type_link.resolve().stem.replace("agent_", "")
        systems = list(directory.glob(f"{prefix}-*-system.md"))
        if prefix == "000":
            continue
        if kind == "mono":
            assert len(systems) == 2, directory
        elif kind in ("x45", "z21"):
            suffixes = [path.name.split("-")[1] for path in systems]
            assert len(systems) == 7, directory
            assert sum(suffix.startswith("2") for suffix in suffixes) == 1
            assert sum(suffix.startswith("8") for suffix in suffixes) == 1
