import json

from echo_os.hook_install import install_hooks, uninstall_hooks

CMD = "ECHO_OS_PORT=8431 '/repo/hooks/echo-hook.sh'"
EVENTS = ["SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"]
OTHER_STOP = {"matcher": "", "hooks": [{"type": "command", "command": "terminal-notifier -message hi"}]}


def write(path, data):
    path.write_text(json.dumps(data))
    return path


def ours(settings, event):
    return [h for group in settings["hooks"].get(event, []) for h in group["hooks"] if "echo-hook.sh" in h["command"]]


def test_install_adds_one_entry_per_event_and_keeps_existing_hooks(tmp_path):
    path = write(tmp_path / "settings.json", {"model": "opus", "hooks": {"Stop": [OTHER_STOP]}})
    install_hooks(path, command=CMD, events=EVENTS)
    settings = json.loads(path.read_text())
    assert settings["model"] == "opus"
    assert OTHER_STOP in settings["hooks"]["Stop"]
    for event in EVENTS:
        assert [h["command"] for h in ours(settings, event)] == [CMD]


def test_install_is_idempotent_and_replaces_a_stale_command(tmp_path):
    path = write(tmp_path / "settings.json", {})
    install_hooks(path, command="ECHO_OS_PORT=1 '/old/hooks/echo-hook.sh'", events=EVENTS)
    install_hooks(path, command=CMD, events=EVENTS)
    install_hooks(path, command=CMD, events=EVENTS)
    settings = json.loads(path.read_text())
    for event in EVENTS:
        assert [h["command"] for h in ours(settings, event)] == [CMD]


def test_install_backs_up_the_original_once(tmp_path):
    path = write(tmp_path / "settings.json", {"model": "opus"})
    install_hooks(path, command=CMD, events=EVENTS)
    install_hooks(path, command=CMD, events=EVENTS)
    assert json.loads((tmp_path / "settings.json.echo-os.bak").read_text()) == {"model": "opus"}


def test_install_creates_a_missing_settings_file(tmp_path):
    path = tmp_path / "settings.json"
    install_hooks(path, command=CMD, events=EVENTS)
    assert ours(json.loads(path.read_text()), "Stop")


def test_uninstall_removes_only_echo_hooks_and_empty_events(tmp_path):
    path = write(tmp_path / "settings.json", {"hooks": {"Stop": [OTHER_STOP]}})
    install_hooks(path, command=CMD, events=EVENTS)
    uninstall_hooks(path)
    settings = json.loads(path.read_text())
    assert settings["hooks"] == {"Stop": [OTHER_STOP]}


def test_invalid_settings_json_is_left_untouched(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{broken")
    try:
        install_hooks(path, command=CMD, events=EVENTS)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
    assert path.read_text() == "{broken"
