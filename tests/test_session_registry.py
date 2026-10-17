from echo_os.sessions import SessionRegistry

SIGNS = ["Alpha", "Bravo", "Charlie"]


def make(tmp_path, **kwargs):
    return SessionRegistry(tmp_path / "sessions.json", call_signs=SIGNS, **kwargs)


def test_first_sessions_get_signs_in_order(tmp_path):
    registry = make(tmp_path)
    assert registry.touch("s1", cwd="/x/proj-a", now=1).call_sign == "Alpha"
    assert registry.touch("s2", cwd="/x/proj-b", now=2).call_sign == "Bravo"


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
