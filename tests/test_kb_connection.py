import json

import pytest

from echo_os.agents.kb_relevance.connection import KbConfigError, KbConnection, load_connection

VALID = {
    "server_name": "notes",
    "mcp_server": {"type": "http", "url": "https://kb.example.com/mcp"},
    "tools": ["search_notes", "get_note"],
    "about": "Notes on my projects and clients.",
    "instructions": "Prefer exact project-name matches.",
}


def write(tmp_path, data):
    path = tmp_path / "kb.json"
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    return path


def test_no_file_means_no_knowledge_base(tmp_path):
    assert load_connection(tmp_path / "kb.json") is None


def test_loads_the_server_and_scopes_tools_to_it(tmp_path):
    connection = load_connection(write(tmp_path, VALID))
    assert connection.server_name == "notes"
    assert connection.mcp_server == {"type": "http", "url": "https://kb.example.com/mcp"}
    assert connection.allowed_tools == ["mcp__notes__search_notes", "mcp__notes__get_note"]
    assert (connection.about, connection.instructions) == ("Notes on my projects and clients.", "Prefer exact project-name matches.")


def test_about_and_instructions_are_optional(tmp_path):
    data = {key: VALID[key] for key in ("server_name", "mcp_server", "tools")}
    connection = load_connection(write(tmp_path, data))
    assert (connection.about, connection.instructions) == ("", "")


def test_stdio_servers_are_passed_through_as_is(tmp_path):
    stdio = {"command": "npx", "args": ["-y", "some-notes-mcp", "~/notes"]}
    assert load_connection(write(tmp_path, {**VALID, "mcp_server": stdio})).mcp_server == stdio


def test_broken_json_names_the_file(tmp_path):
    with pytest.raises(KbConfigError, match="kb.json"):
        load_connection(write(tmp_path, "{nope"))


@pytest.mark.parametrize("broken", [
    {**VALID, "server_name": ""},
    {**VALID, "server_name": "has spaces"},
    {**VALID, "mcp_server": "https://kb.example.com"},
    {**VALID, "tools": []},
    {**VALID, "tools": "search_notes"},
    {key: value for key, value in VALID.items() if key != "tools"},
    ["not", "an", "object"],
])
def test_invalid_connections_are_rejected(tmp_path, broken):
    with pytest.raises(KbConfigError):
        load_connection(write(tmp_path, broken))


def test_connection_is_a_plain_value():
    connection = KbConnection(server_name="notes", mcp_server={"command": "x"}, tools=("search",))
    assert connection.allowed_tools == ["mcp__notes__search"]


def test_app_reads_kb_json_from_settings(tmp_path, monkeypatch):
    from echo_os import app, settings
    monkeypatch.setattr(settings, "KB_CONFIG_PATH", write(tmp_path, VALID))
    monkeypatch.setattr(settings, "KB_AGENT_ENABLED", True)
    assert app.kb_connection_from_settings().server_name == "notes"


def test_a_broken_kb_json_turns_the_kb_off_instead_of_crashing(tmp_path, monkeypatch, caplog):
    from echo_os import app, settings
    monkeypatch.setattr(settings, "KB_CONFIG_PATH", write(tmp_path, "{nope"))
    monkeypatch.setattr(settings, "KB_AGENT_ENABLED", True)
    assert app.kb_connection_from_settings() is None
    assert "kb.json" in caplog.text


def test_the_kb_switch_overrides_kb_json(tmp_path, monkeypatch):
    from echo_os import app, settings
    monkeypatch.setattr(settings, "KB_CONFIG_PATH", write(tmp_path, VALID))
    monkeypatch.setattr(settings, "KB_AGENT_ENABLED", False)
    assert app.kb_connection_from_settings() is None
