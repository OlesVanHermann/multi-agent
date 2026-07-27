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
    assert payload["schema"] == "multi-agent.contradictor.snapshot.v3"
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
    assert "agent_prompt_files" in payload["evidence"]
    assert "user_requests" in payload["analysis_view"]
    assert "physical_evidence" in payload["evidence"]
    assert payload["analysis_view"]["unattributed_request_candidates"]
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
        "Demande utilisateur initiale : développer X.\n"
        "Corrections ou précisions ultérieures : aucune.\n"
        "Résultat attendu : X fonctionnel.\nExécution du prompt : NON\n"
        "Développement réalisé : NON\nValidation réalisée : NON\n"
        "Résultat effectivement livré : NON\n"
        "Échanges déterminants : dispatch sans artefact.\n"
        "Écart entre demande et résultat : X absent.\n"
        "Cause de l'écart : développement arrêté.\nPreuves : aucun artefact.\n"
        "Plan de développement ou correction : développer X.\n"
        "Agents à mobiliser : 345-345.\nOrdre de relance : 345-345 puis 345-545.\n"
        "Critères d'acceptation : tests verts.\n"
        "Résultat final attendu : X livré.\n"
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


def test_analysis_view_separates_user_requests_from_agent_exchanges():
    inbox = [
        {"id": "1-0", "fields": {
            "stream_agent": "345-145", "from_agent": "cli",
            "requester": "cli", "event": "USER_REQUEST",
            "prompt": "Développe l'import CSV"}},
        {"id": "2-0", "fields": {
            "stream_agent": "345-145", "from_agent": "345-345",
            "requester": "cli", "event": "STATUS",
            "prompt": "Le développement est en cours"}},
        {"id": "3-0", "fields": {
            "stream_agent": "345-145", "from_agent": "cli",
            "requester": "cli", "event": "USER_REQUEST",
            "prompt": "Ajoute aussi les fichiers TSV"}},
    ]
    streams = {
        "inbox": {"available": True, "error": "", "entries": inbox},
        "outbox": {"available": True, "error": "", "entries": []},
        "wal": {"available": True, "error": "", "entries": []},
    }
    view = MODULE.analysis_view(
        "345-145", ["345-145", "345-245", "345-345"], [], "", streams)
    assert [item["request_kind"] for item in view["user_requests"]] == [
        "INITIAL", "AMENDMENT"]
    assert view["user_requests"][0]["prompt"] == "Développe l'import CSV"
    assert view["user_requests"][1]["prompt"] == "Ajoute aussi les fichiers TSV"
    assert view["inter_agent_exchanges"][0]["from_agent"] == "345-345"
    assert view["execution_assessment"]["prompt_executed"] == "TO_ASSESS"


def test_analysis_view_uses_structured_arbitrage_and_expected_event():
    inbox = [
        {"id": "1-0", "fields": {
            "stream_agent": "345-145",
            "from_agent": "345-945",
            "event": "ARBITRAGE",
            "task_id": "task-1",
            "cycle": "r1",
            "correlation_id": "corr-1",
            "expected_event": "ARBITRAGE",
            "prompt": "texte sans marqueur legacy",
        }}
    ]
    wal = [
        {"id": "2-0", "fields": {
            "event": "task_assigned",
            "agent_id": "345-945",
            "from_agent": "345-145",
            "task_id": "task-1",
            "cycle": "r1",
            "correlation_id": "corr-1",
            "expected_event": "ARBITRAGE",
        }}
    ]
    streams = {
        "inbox": {"available": True, "error": "", "entries": inbox},
        "outbox": {"available": True, "error": "", "entries": []},
        "wal": {"available": True, "error": "", "entries": wal},
    }
    view = MODULE.analysis_view(
        "345-145", ["345-145", "345-945"], [], "", streams)
    assert view["terminal_events"][0]["event"] == "ARBITRAGE"
    assert view["terminal_events"][0]["correlation_id"] == "corr-1"
    assert view["dispatch_expectations"][0]["expected_event"] == "ARBITRAGE"


def test_send_archives_message_queued_for_offline_target(tmp_path, monkeypatch):
    make_triangle(tmp_path)
    monkeypatch.setattr(MODULE, "BASE", tmp_path)
    output = tmp_path / "pool-requests" / "knowledge" / "contradictor" / "345-245"
    output.mkdir(parents=True)
    (output / "conclusion.md").write_text(
        "Cible : 345-145\nVerdict : ÉTABLI\n"
        "Demande utilisateur initiale : développer X.\n"
        "Corrections ou précisions ultérieures : aucune.\n"
        "Résultat attendu : X fonctionnel.\nExécution du prompt : NON\n"
        "Développement réalisé : NON\nValidation réalisée : NON\n"
        "Résultat effectivement livré : NON\nÉchanges déterminants : aucun.\n"
        "Écart entre demande et résultat : X absent.\n"
        "Cause de l'écart : arrêt.\nPreuves : aucune.\n"
        "Plan de développement ou correction : développer X.\n"
        "Agents à mobiliser : 345-345.\nOrdre de relance : Dev puis Observer.\n"
        "Critères d'acceptation : tests verts.\nRésultat final attendu : X livré.\n"
    )

    def fake_run(*args, **kwargs):
        return type("Result", (), {"returncode": 1, "stdout": "",
                                    "stderr": "ko: agent not running — msg 1-0 in orphan queue"})()

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    MODULE.send("345")
    proof = json.loads(next((output / "sent").glob("*.json")).read_text())
    assert proof["delivery"] == "queued"
