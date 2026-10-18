import subprocess

from echo_os.kb_status import KbAuthMonitor, parse_mcp_get


def test_parses_connected():
    assert parse_mcp_get("notes-kb:\n  Scope: User\n  Status: ✔ Connected\n  Type: http\n") == "connected"


def test_parses_needs_auth():
    assert parse_mcp_get("  Status: ! Needs authentication\n") == "needs-auth"


def test_parses_failed():
    assert parse_mcp_get("  Status: ✘ Failed to connect\n") == "failed"


def test_missing_server():
    assert parse_mcp_get('No MCP server named "notes-kb". Configured servers: x') == "missing"


def test_unrecognised_output_is_unknown():
    assert parse_mcp_get("something else") == "unknown"


def runner(stdout="", raises=None):
    calls = []

    def run(argv, *, env, cwd, timeout):
        calls.append(argv)
        if raises:
            raise raises
        return subprocess.CompletedProcess(argv, 0, stdout, "")
    run.calls = calls
    return run


def monitor(tmp_path, run, clock=lambda: 100.0):
    return KbAuthMonitor(binary="claude", server_name="notes-kb", workdir=tmp_path, child_env_flag="ECHO_OS_CHILD",
                         run_process=run, clock=clock)


def test_connected_but_tools_failed_is_a_failure_not_green():
    assert parse_mcp_get("notes-kb:\n  Status: ! Connected · tools fetch failed\n  Type: http\n") == "tools-failed"


def test_unusable_states_are_the_ones_a_lookup_cannot_succeed_in():
    from echo_os.kb_status import UNUSABLE_STATES
    assert UNUSABLE_STATES == {"needs-auth", "failed", "tools-failed"}


def test_starts_unknown_until_checked(tmp_path):
    assert monitor(tmp_path, runner()).snapshot()["state"] == "unknown"


def test_check_runs_mcp_get_and_records_when(tmp_path):
    run = runner("  Status: ✔ Connected\n")
    m = monitor(tmp_path, run)
    m.check()
    assert run.calls[0] == ["claude", "mcp", "get", "notes-kb"]
    assert m.snapshot() == {"state": "connected", "checked_at": 100.0, "source": "check"}


def test_check_failure_reads_as_unknown_not_a_crash(tmp_path):
    m = monitor(tmp_path, runner(raises=subprocess.TimeoutExpired("claude", 20)))
    m.check()
    assert m.snapshot()["state"] == "unknown"


def test_observations_from_kb_lookups_update_the_light(tmp_path):
    m = monitor(tmp_path, runner("  Status: ✔ Connected\n"))
    m.check()
    m.observe("needs-auth")
    assert m.snapshot() == {"state": "needs-auth", "checked_at": 100.0, "source": "kb lookup"}


def test_a_server_unknown_to_claude_code_keeps_the_status_lookups_saw(tmp_path):
    """Servers attached only through kb.json aren't registered in Claude Code, so `mcp get` says
    missing; the status the last lookup saw is the better answer."""
    m = monitor(tmp_path, runner('No MCP server named "notes-kb". Configured servers: x'))
    m.observe("connected")
    m.check()
    assert m.snapshot()["state"] == "connected"


def test_missing_with_no_lookup_yet_reads_as_missing(tmp_path):
    m = monitor(tmp_path, runner('No MCP server named "notes-kb". Configured servers: x'))
    m.check()
    assert m.snapshot()["state"] == "missing"
