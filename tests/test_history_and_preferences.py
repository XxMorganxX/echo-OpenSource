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


DAY = 24 * 3600


def aged_history(tmp_path, now=10 * DAY):
    history = EchoHistory(tmp_path / "e.jsonl", max_age_seconds=3 * DAY, clock=lambda: now)
    history.append({"id": "old", "created_at": now - 4 * DAY})
    history.append({"id": "new", "created_at": now - 2 * DAY})
    return history


def test_echoes_older_than_the_max_age_are_not_listed(tmp_path):
    assert [e["id"] for e in aged_history(tmp_path).recent(10)] == ["new"]


def test_echoes_older_than_the_max_age_cannot_be_replayed(tmp_path):
    history = aged_history(tmp_path)
    assert history.get("old") is None and history.get("new") is not None


def test_old_echoes_are_dropped_from_the_file_on_the_next_append(tmp_path):
    history = aged_history(tmp_path)
    history.append({"id": "newest", "created_at": 10 * DAY})
    lines = (tmp_path / "e.jsonl").read_text().splitlines()
    assert [line for line in lines if '"old"' in line] == [] and len(lines) == 2


def test_echoes_expire_as_time_passes_without_new_appends(tmp_path):
    now = [10 * DAY]
    history = EchoHistory(tmp_path / "e.jsonl", max_age_seconds=3 * DAY, clock=lambda: now[0])
    history.append({"id": "a", "created_at": now[0]})
    now[0] += 3 * DAY + 1
    assert history.recent(10) == []
