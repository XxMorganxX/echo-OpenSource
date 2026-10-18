from echo_os.sessions import SessionRegistry

SIGNS = ["Alpha", "Bravo", "Charlie"]


def make(tmp_path, **kwargs):
    return SessionRegistry(tmp_path / "sessions.json", call_signs=SIGNS, **kwargs)


def test_sessions_in_one_directory_get_signs_in_order(tmp_path):
    registry = make(tmp_path)
    assert registry.touch("s1", cwd="/x/proj-a", now=1).call_sign == "Alpha"
    assert registry.touch("s2", cwd="/x/proj-a", now=2).call_sign == "Bravo"


def test_each_directory_counts_its_own_signs(tmp_path):
    registry = make(tmp_path)
    assert registry.touch("s1", cwd="/x/echo-OS", now=1).call_sign == "Alpha"
    assert registry.touch("s2", cwd="/x/web-app", now=2).call_sign == "Alpha"
    assert registry.touch("s3", cwd="/x/web-app", now=3).call_sign == "Bravo"


def test_ending_a_session_frees_its_sign_only_in_its_directory(tmp_path):
    registry = make(tmp_path)
    registry.touch("s1", cwd="/x/a", now=1)
    registry.touch("s2", cwd="/x/a", now=1)
    registry.touch("s3", cwd="/x/b", now=1)
    registry.end("s1")
    assert registry.touch("s4", cwd="/x/b", now=2).call_sign == "Bravo"
    assert registry.touch("s5", cwd="/x/a", now=2).call_sign == "Alpha"


def test_moving_to_a_directory_where_the_sign_is_taken_picks_a_free_one(tmp_path):
    registry = make(tmp_path)
    registry.touch("s1", cwd="/x/a", now=1)
    registry.touch("s2", cwd="/x/b", now=1)
    assert registry.touch("s2", cwd="/x/a", now=2).call_sign == "Bravo"


def test_a_session_revived_without_a_directory_keeps_its_old_one(tmp_path):
    registry = make(tmp_path)
    registry.touch("s1", cwd="/x/a", now=1)
    registry.end("s1")
    revived = registry.touch("s1", cwd="", now=2)
    assert (revived.cwd, revived.project, revived.call_sign) == ("/x/a", "a", "Alpha")


def test_active_sessions_are_listed_by_project_then_sign(tmp_path):
    registry = make(tmp_path)
    registry.touch("s1", cwd="/x/b", now=1)
    registry.touch("s2", cwd="/x/a", now=1)
    registry.touch("s3", cwd="/x/a", now=1)
    assert [(s.project, s.call_sign) for s in registry.active()] == [("a", "Alpha"), ("a", "Bravo"), ("b", "Alpha")]


def test_touching_a_known_session_keeps_its_sign(tmp_path):
    registry = make(tmp_path)
    registry.touch("s1", cwd="/x/a", now=1)
    assert registry.touch("s1", cwd="/x/a", now=5).call_sign == "Alpha"


def test_ended_sessions_free_their_sign_for_the_lowest_slot(tmp_path):
    registry = make(tmp_path)
    for sid in ("s1", "s2", "s3"):
        registry.touch(sid, cwd="/x", now=1)
    registry.end("s1")
    assert registry.touch("s4", cwd="/x", now=2).call_sign == "Alpha"


def test_resumed_session_gets_its_old_sign_back_when_free(tmp_path):
    registry = make(tmp_path)
    registry.touch("s1", cwd="/x", now=1)
    registry.touch("s2", cwd="/x", now=1)
    registry.end("s2")
    assert registry.touch("s2", cwd="/x", now=2).call_sign == "Bravo"


def test_overflow_adds_a_number(tmp_path):
    registry = make(tmp_path)
    for sid in ("s1", "s2", "s3"):
        registry.touch(sid, cwd="/x", now=1)
    assert registry.touch("s4", cwd="/x", now=1).call_sign == "Alpha 2"


def test_project_is_the_cwd_folder_name(tmp_path):
    assert make(tmp_path).touch("s1", cwd="/Users/me/Development/echo-OS", now=1).project == "echo-OS"


def test_status_follows_prompt_and_stop(tmp_path):
    registry = make(tmp_path)
    registry.touch("s1", cwd="/x", now=1)
    registry.mark_working("s1", now=2)
    assert registry.get("s1").status == "working"
    registry.mark_idle("s1", now=3)
    assert registry.get("s1").status == "idle"


def test_names_survive_a_restart(tmp_path):
    registry = make(tmp_path)
    registry.touch("s1", cwd="/x", now=1)
    registry.touch("s2", cwd="/x", now=1)
    reloaded = make(tmp_path)
    assert reloaded.get("s2").call_sign == "Bravo"
    assert reloaded.touch("s3", cwd="/x", now=2).call_sign == "Charlie"


def test_corrupt_state_file_starts_empty(tmp_path):
    (tmp_path / "sessions.json").write_text("{nope")
    assert make(tmp_path).active() == []


def test_sweep_ends_sessions_whose_process_died(tmp_path):
    registry = make(tmp_path, idle_expiry_seconds=1000)
    registry.touch("s1", cwd="/x", pid=111, now=1)
    registry.touch("s2", cwd="/x", pid=222, now=1)
    registry.sweep(now=2, is_alive=lambda pid: pid == 222)
    assert [s.session_id for s in registry.active()] == ["s2"]


def test_sweep_expires_quiet_sessions_without_a_pid(tmp_path):
    registry = make(tmp_path, idle_expiry_seconds=100)
    registry.touch("s1", cwd="/x", now=1)
    registry.touch("s2", cwd="/x", now=90)
    registry.sweep(now=150, is_alive=lambda pid: True)
    assert [s.session_id for s in registry.active()] == ["s2"]


def test_active_lists_sessions_in_call_sign_order(tmp_path):
    registry = make(tmp_path)
    for sid in ("s1", "s2", "s3"):
        registry.touch(sid, cwd="/x", now=1)
    registry.end("s1")
    registry.touch("s4", cwd="/x", now=2)
    assert [s.call_sign for s in registry.active()] == ["Alpha", "Bravo", "Charlie"]


def test_last_headline_is_recorded(tmp_path):
    registry = make(tmp_path)
    registry.touch("s1", cwd="/x", now=1)
    registry.set_last_headline("s1", "Done.", now=5)
    assert registry.get("s1").last_headline == "Done."


def test_sessions_in_the_same_directory_share_a_color(tmp_path):
    registry = make(tmp_path)
    first = registry.touch("s1", cwd="/x/proj-a", now=1)
    second = registry.touch("s2", cwd="/x/proj-a", now=2)
    assert first.color == second.color is not None


def test_live_directories_never_share_a_color(tmp_path):
    registry = make(tmp_path, color_count=2)
    # With two slots, two directories must take both, whatever their hashes prefer.
    colors = {registry.touch(f"s{i}", cwd=f"/x/proj-{i}", now=i).color for i in range(2)}
    assert colors == {0, 1}


def test_a_directory_gets_its_color_back_in_a_later_session(tmp_path):
    registry = make(tmp_path)
    color = registry.touch("s1", cwd="/x/proj-a", now=1).color
    registry.end("s1")
    assert registry.touch("s2", cwd="/x/proj-a", now=50).color == color


def test_more_directories_than_colors_still_get_a_color(tmp_path):
    registry = make(tmp_path, color_count=2)
    for i in range(3):
        registry.touch(f"s{i}", cwd=f"/x/proj-{i}", now=i)
    assert registry.get("s2").color in (0, 1)


def test_colors_survive_a_restart(tmp_path):
    registry = make(tmp_path)
    color = registry.touch("s1", cwd="/x/proj-a", now=1).color
    assert make(tmp_path).get("s1").color == color


def test_sessions_saved_before_colors_existed_get_one(tmp_path):
    import json
    (tmp_path / "sessions.json").write_text(json.dumps([{
        "session_id": "s1", "call_sign": "Alpha", "project": "a", "cwd": "/x/a", "pid": None, "status": "idle",
        "started_at": 1, "last_event_at": 1, "last_headline": ""}]))
    assert make(tmp_path).get("s1").color is not None


def test_moving_to_another_directory_changes_the_color(tmp_path):
    registry = make(tmp_path, color_count=2)
    registry.touch("s1", cwd="/x/a", now=1)
    registry.touch("s2", cwd="/x/b", now=1)
    moved = registry.touch("s2", cwd="/x/a", now=2)
    assert moved.color == registry.get("s1").color
