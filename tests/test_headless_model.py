import json
import subprocess

import pytest

from echo_os.agents.shared.headless_model import (
    ClaudeCodeHeadless,
    HeadlessModelError,
    ModelRequest,
)


class FakeProcess:
    def __init__(self, stdout="", returncode=0, raises=None):
        self.stdout, self.returncode, self.raises = stdout, returncode, raises
        self.calls = []

    def __call__(self, argv, *, env, cwd, timeout):
        self.calls.append({"argv": argv, "env": env, "cwd": cwd, "timeout": timeout})
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, "boom")


def ok_output(mcp_servers=(), **overrides):
    """stream-json: an init line, an assistant line, then the result line."""
    init = {"type": "system", "subtype": "init", "mcp_servers": list(mcp_servers)}
    result = {"type": "result", "result": "Done.", "is_error": False, "total_cost_usd": 0.0012, "duration_ms": 2100}
    result.update(overrides)
    return "\n".join(json.dumps(line) for line in (init, {"type": "assistant"}, result)) + "\n"


def request(**overrides):
    base = dict(system_prompt="SYS", user_message="USER", model="claude-haiku-5-5", timeout_seconds=30,
                max_budget_usd=0.05)
    base.update(overrides)
    return ModelRequest(**base)


def model(fake, tmp_path):
    return ClaudeCodeHeadless(binary="claude", workdir=tmp_path, child_env_flag="ECHO_OS_CHILD", run_process=fake)


def test_call_is_isolated_from_user_config(tmp_path):
    fake = FakeProcess(ok_output())
    model(fake, tmp_path).run(request())
    argv, env = fake.calls[0]["argv"], fake.calls[0]["env"]
    assert argv[:2] == ["claude", "-p"]
    assert argv[argv.index("--output-format") + 1] == "stream-json" and "--verbose" in argv
    for flag in ("--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands"):
        assert flag in argv
    assert argv[argv.index("--tools") + 1] == ""
    assert json.loads(argv[argv.index("--settings") + 1]) == {"disableAllHooks": True}
    assert argv[argv.index("--system-prompt") + 1] == "SYS"
    assert argv[argv.index("--model") + 1] == "claude-haiku-5-5"
    assert argv[-1] == "USER"
    assert env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
    assert env["ECHO_OS_CHILD"] == "1"
    assert fake.calls[0]["cwd"] == tmp_path


def test_mcp_servers_tools_and_schema_are_passed_through(tmp_path):
    fake = FakeProcess(ok_output(structured_output={"relevant": True}))
    result = model(fake, tmp_path).run(request(
        mcp_servers={"kb": {"type": "http", "url": "https://kb"}},
        allowed_tools=["mcp__kb__search"],
        json_schema={"type": "object"},
    ))
    argv = fake.calls[0]["argv"]
    assert json.loads(argv[argv.index("--mcp-config") + 1]) == {"mcpServers": {"kb": {"type": "http", "url": "https://kb"}}}
    assert argv[argv.index("--allowedTools") + 1] == "mcp__kb__search"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert json.loads(argv[argv.index("--json-schema") + 1]) == {"type": "object"}
    assert result.structured == {"relevant": True}


def test_result_carries_text_cost_and_latency(tmp_path):
    result = model(FakeProcess(ok_output()), tmp_path).run(request())
    assert (result.text, result.cost_usd, result.duration_ms) == ("Done.", 0.0012, 2100)


@pytest.mark.parametrize("fake", [
    FakeProcess(raises=subprocess.TimeoutExpired("claude", 30)),
    FakeProcess(ok_output(), returncode=1),
    FakeProcess("not json"),
    FakeProcess(json.dumps({"type": "system", "subtype": "init"})),  # no result line
    FakeProcess(ok_output(is_error=True, result="auth failed")),
    FakeProcess(raises=FileNotFoundError("claude")),
])
def test_failures_raise_headless_model_error(fake, tmp_path):
    with pytest.raises(HeadlessModelError):
        model(fake, tmp_path).run(request())


def test_api_keys_are_dropped_like_the_users_shell_wrapper(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    fake = FakeProcess(ok_output())
    model(fake, tmp_path).run(request())
    env = fake.calls[0]["env"]
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env


def test_mcp_server_status_is_reported(tmp_path):
    fake = FakeProcess(ok_output(mcp_servers=[{"name": "notes-kb", "status": "needs-auth"}]))
    assert model(fake, tmp_path).run(request()).mcp_status == {"notes-kb": "needs-auth"}
