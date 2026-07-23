"""Régressions : un upload ne doit jamais être soumis deux fois au TUI."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TERMINAL = ROOT / "web/frontend/src/components/Terminal.jsx"
AGENTS = ROOT / "web/backend/multi_agent/routers/agents.py"


def test_uploaded_path_uses_the_same_interactive_sync():
    source = TERMINAL.read_text(encoding="utf-8")
    upload = source[source.index("const handleUpload"):source.index("const toggleHistory")]

    assert "setTimeout(() => doSyncToTmux" in upload


def test_web_typing_is_mirrored_interactively():
    source = TERMINAL.read_text(encoding="utf-8")
    change = source[source.index("const handleInputChange"):source.index("// Send raw tmux keys")]

    assert "doSyncToTmux" in change
    assert "setTimeout" in change


def test_synced_submit_validates_without_repasting():
    frontend = TERMINAL.read_text(encoding="utf-8")
    backend = AGENTS.read_text(encoding="utf-8")

    assert "already_synced: alreadySynced" in frontend
    start = backend.index("if data.already_synced:")
    synced = backend[start:backend.index("# Soumission atomique", start)]
    assert synced.count('"Enter"') == 1
    assert "paste-buffer" not in synced


def test_atomic_fallback_has_no_pane_retry():
    source = AGENTS.read_text(encoding="utf-8")
    start = source.index("# Soumission atomique")
    fallback = source[start:source.index("_log_prompt_history", start)]

    assert fallback.count('"Enter"') == 1
    assert "capture-pane" not in fallback
