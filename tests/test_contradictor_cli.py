import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "contradictor_cli", ROOT / "scripts" / "agent-bridge" / "contradictor.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def make_triangle(tmp_path):
    directory = tmp_path / "prompts" / "345-demo"
    directory.mkdir(parents=True)
    for agent_id in ("345-145", "345-245", "345-345", "345-545",
                     "345-745", "345-845", "345-945"):
        for kind in ("system", "memory", "methodology"):
            (directory / f"{agent_id}-{kind}.md").write_text(f"{agent_id} {kind}\n")
    (directory / "345-145.history").write_text("request\naction\n")
    return directory


def test_collect_resolves_roles_and_writes_canonical_snapshot(tmp_path, monkeypatch):
    make_triangle(tmp_path)
    monkeypatch.setattr(MODULE, "BASE", tmp_path)
    monkeypatch.setattr(MODULE, "run", lambda *args, **kwargs: {
        "returncode": 0, "stdout": "bounded", "stderr": ""
    })
    MODULE.collect("345")
    root = tmp_path / "pool-requests" / "knowledge" / "contradictor" / "345-245"
    payload = json.loads((root / "snapshot.json").read_text())
    assert payload["target"] == "345-145"
    assert payload["contradictor"] == "345-245"
    assert payload["schema"] == "multi-agent.contradictor.snapshot.v2"
    assert payload["analysis_scope"] == [
        "345-145", "345-245", "345-345", "345-545",
        "345-745", "345-845", "345-945",
    ]
    assert payload["delivery_target"] == "345-145"
    assert set(payload["evidence"]["panes"]) == set(payload["analysis_scope"])
    assert set(payload["evidence"]["histories"]) == set(payload["analysis_scope"])
    assert set(payload["analysis_view"]["activity_by_agent"]) == set(
        payload["analysis_scope"]
    )
    assert (root / "state.json").is_file()


def test_collect_archives_previous_snapshot(tmp_path, monkeypatch):
    make_triangle(tmp_path)
    monkeypatch.setattr(MODULE, "BASE", tmp_path)
    monkeypatch.setattr(MODULE, "run", lambda *args, **kwargs: {
        "returncode": 0, "stdout": "bounded", "stderr": ""
    })
    MODULE.collect("345")
    MODULE.collect("345")
    archive = tmp_path / "pool-requests" / "knowledge" / "contradictor" / "345-245" / "snapshots"
    assert len(list(archive.glob("*-snapshot.json"))) == 2
    state = json.loads((archive.parent / "state.json").read_text())
    assert (tmp_path / state["snapshot"]).is_file()


def test_send_transmits_exact_conclusion_and_archives_proof(tmp_path, monkeypatch):
    make_triangle(tmp_path)
    monkeypatch.setattr(MODULE, "BASE", tmp_path)
    output = tmp_path / "pool-requests" / "knowledge" / "contradictor" / "345-245"
    output.mkdir(parents=True)
    conclusion = (
        "CONCLUSION CONTRADICTOR\nCible : 345-145\nVerdict : ÉTABLI\n"
        "Synthèse du triangle : développement arrêté après le dispatch.\n"
        "Constat : écart.\nCorrection demandée : avancer.\n"
        "Relance du développement : redispatcher 345-345.\n"
        "Résultat attendu : progression.\n"
    )
    (output / "conclusion.md").write_text(conclusion)
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["input"] = kwargs["input"]
        return type("Result", (), {"returncode": 0, "stdout": "ok: 345-145 1-0", "stderr": ""})()

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    MODULE.send("345")
    assert captured["command"][-1] == "345-145"
    assert captured["input"] == conclusion
    sent = list((output / "sent").glob("*-conclusion.md"))
    assert len(sent) == 1
    assert sent[0].read_text() == conclusion


def test_redis_entries_parses_json(monkeypatch):
    payload = '[["1-0",["event","task_assigned","agent_id","345-145"]]]'
    monkeypatch.setattr(MODULE, "run", lambda *args, **kwargs: {
        "returncode": 0, "stdout": payload, "stderr": ""
    })
    result = MODULE.redis_entries("A:wal")
    assert result["available"] is True
    assert result["entries"][0]["fields"]["agent_id"] == "345-145"


def test_analysis_view_detects_duplicate_and_memory_conflict():
    entries = [
        {"id": "1-0", "fields": {"event": "task_assigned", "agent_id": "345-745",
                                    "from_agent": "345-145", "task_id": "task-1", "cycle": "1"}},
        {"id": "2-0", "fields": {"event": "task_assigned", "agent_id": "345-745",
                                    "from_agent": "345-145", "task_id": "task-1", "cycle": "1"}},
    ]
    streams = {name: {"available": True, "error": "", "entries": entries if name == "wal" else []}
               for name in ("inbox", "outbox", "wal")}
    tasks = [{"id": "task-1", "path": "plans/demo/plan-DOING/A/task-1"}]
    view = MODULE.analysis_view(
        "345-145", ["345-145", "345-245", "345-745"],
        tasks, "- Tache active : aucune", streams
    )
    assert view["active_task"]["id"] == "task-1"
    assert view["duplicate_dispatches"][0]["count"] == 2
    assert view["memory_conflicts"][0]["type"] == "active_task_vs_memory"


def test_send_archives_message_queued_for_offline_target(tmp_path, monkeypatch):
    make_triangle(tmp_path)
    monkeypatch.setattr(MODULE, "BASE", tmp_path)
    output = tmp_path / "pool-requests" / "knowledge" / "contradictor" / "345-245"
    output.mkdir(parents=True)
    (output / "conclusion.md").write_text(
        "Cible : 345-145\nVerdict : ÉTABLI\n"
        "Synthèse du triangle : développement arrêté.\nConstat : écart.\n"
        "Correction demandée : avancer.\n"
        "Relance du développement : redispatcher 345-345.\n"
        "Résultat attendu : progression.\n"
    )

    def fake_run(*args, **kwargs):
        return type("Result", (), {"returncode": 1, "stdout": "",
                                    "stderr": "ko: agent not running — msg 1-0 in orphan queue"})()

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    MODULE.send("345")
    proof = json.loads(next((output / "sent").glob("*.json")).read_text())
    assert proof["delivery"] == "queued"
