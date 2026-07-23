"""Régressions : un upload ne doit jamais être soumis deux fois au TUI."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TERMINAL = ROOT / "web/frontend/src/components/Terminal.jsx"
AGENTS = ROOT / "web/backend/multi_agent/routers/agents.py"


def test_uploaded_path_is_deferred_until_atomic_submit():
    source = TERMINAL.read_text(encoding="utf-8")
    upload = source[source.index("const handleUpload"):source.index("const toggleHistory")]

    assert "deferSyncUntilSubmitRef.current = true" in upload
    assert "setTimeout(() => doSyncToTmux" not in upload


def test_all_web_typing_stays_local_until_atomic_submit():
    source = TERMINAL.read_text(encoding="utf-8")
    change = source[source.index("const handleInputChange"):source.index("// Send raw tmux keys")]

    assert "doSyncToTmux" not in change
    assert "setTimeout" not in change
    assert "deferSyncUntilSubmitRef = useRef(true)" in source


def test_web_submit_sends_exactly_one_enter_without_pane_retry():
    source = AGENTS.read_text(encoding="utf-8")
    submit = source[source.index("if data.submit:"):source.index("else:", source.index("if data.submit:"))]

    assert submit.count('"Enter"') == 1
    assert "capture-pane" not in submit
