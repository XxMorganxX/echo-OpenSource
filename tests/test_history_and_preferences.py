from echo_os.echo.history import EchoHistory
from echo_os.echo.preferences import Preferences


def test_recent_returns_newest_first_and_limits(tmp_path):
    history = EchoHistory(tmp_path / "e.jsonl")
    for i in range(5):
        history.append({"id": str(i)})
    assert [e["id"] for e in history.recent(3)] == ["4", "3", "2"]


def test_get_finds_by_id_and_skips_corrupt_lines(tmp_path):
    path = tmp_path / "e.jsonl"
    path.write_text('{"id": "a"}\nnot json\n{"id": "b"}\n')
    history = EchoHistory(path)
    assert history.get("b") == {"id": "b"}
    assert history.get("zzz") is None


def test_missing_history_is_empty(tmp_path):
    assert EchoHistory(tmp_path / "none.jsonl").recent(5) == []


def test_mute_persists(tmp_path):
    Preferences(tmp_path / "p.json").set_muted(True)
    assert Preferences(tmp_path / "p.json").muted is True


def test_preferences_default_unmuted_on_corrupt_file(tmp_path):
    (tmp_path / "p.json").write_text("{bad")
    assert Preferences(tmp_path / "p.json").muted is False


def test_popup_anchor_persists(tmp_path):
    Preferences(tmp_path / "p.json").set_popup_anchor({"x": 10, "edge": 20, "grows": "down"})
    assert Preferences(tmp_path / "p.json").popup_anchor == {"x": 10, "edge": 20, "grows": "down"}


def test_muting_keeps_the_popup_anchor_and_vice_versa(tmp_path):
    prefs = Preferences(tmp_path / "p.json")
    prefs.set_popup_anchor({"x": 10, "edge": 20, "grows": "down"})
    prefs.set_muted(True)
    reloaded = Preferences(tmp_path / "p.json")
    assert reloaded.muted is True and reloaded.popup_anchor == {"x": 10, "edge": 20, "grows": "down"}


def test_clearing_the_popup_anchor(tmp_path):
    prefs = Preferences(tmp_path / "p.json")
    prefs.set_popup_anchor({"x": 10, "edge": 20, "grows": "down"})
    prefs.set_popup_anchor(None)
    assert Preferences(tmp_path / "p.json").popup_anchor is None
