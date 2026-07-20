from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text()


def test_x45_places_2xx_between_1xx_and_output():
    source = read("web/frontend/src/components/sidebar/TriangleDiagram.jsx")
    master = source.index("const mid = tri.master")
    echo = source.index("tri.echo", master)
    output = source.index('className="tri-dir">OUTPUT', echo)
    assert master < echo < output
    assert "Contradictor" in source


def test_mono_pair_has_only_main_and_contradictor_roles():
    source = read("web/frontend/src/components/sidebar/MonoPairDiagram.jsx")
    assert "tri.worker" in source
    assert "tri.echo" in source
    assert 'role="Contradictor"' in source
    for absent in ("tri.master", "tri.tri_architect", "tri.curator",
                   "tri.coach", "tri.observer", "tri.indexer"):
        assert absent not in source


def test_global_observer_panel_is_removed():
    app = read("web/frontend/src/App.jsx")
    header = read("web/frontend/src/components/HeaderBar.jsx")
    assert "ObservationPanel" not in app
    assert "observers" not in header
