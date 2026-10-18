"""The model contract both agents call, and its Claude Code headless implementation.

Agents depend on `HeadlessModel`, never on `claude -p` directly, so the provider can be swapped
(e.g. for a direct API call) without touching agent code.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol


class HeadlessModelError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelRequest:
    system_prompt: str
    user_message: str
    model: str
    timeout_seconds: float
    max_budget_usd: float
    mcp_servers: dict[str, dict] = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)
    json_schema: dict | None = None


@dataclass(frozen=True)
class ModelResult:
    text: str
    structured: dict | None
    cost_usd: float
    duration_ms: int
    # MCP server name -> connection status as the provider reported it ("connected", "needs-auth", ...).
    mcp_status: dict[str, str] = field(default_factory=dict)
    # The tools the call actually had. An MCP server can connect yet fail to list its tools.
    tools: tuple[str, ...] = ()


class HeadlessModel(Protocol):
    def run(self, request: ModelRequest) -> ModelResult: ...


RunProcess = Callable[..., subprocess.CompletedProcess]


def _run_process(argv: list[str], *, env: dict, cwd: Path, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(argv, env=env, cwd=cwd, timeout=timeout, capture_output=True, text=True, stdin=subprocess.DEVNULL)


class ClaudeCodeHeadless:
    """Runs one `claude -p` call with everything user-specific stripped out.

    Without the stripping the default context is ~163k tokens per call; with it, a few hundred.
    Hooks are disabled so the call neither re-triggers echo-OS nor fires the user's own hooks.
    """

    def __init__(self, *, binary: str, workdir: Path, child_env_flag: str, run_process: RunProcess = _run_process):
        self._binary = binary
        self._workdir = workdir
        self._child_env_flag = child_env_flag
        self._run_process = run_process

    def run(self, request: ModelRequest) -> ModelResult:
        self._workdir.mkdir(parents=True, exist_ok=True)
        try:
            completed = self._run_process(
                self._argv(request), env=self._env(), cwd=self._workdir, timeout=request.timeout_seconds
            )
        except subprocess.TimeoutExpired as exc:
            raise HeadlessModelError(f"timed out after {request.timeout_seconds}s") from exc
        except OSError as exc:
            raise HeadlessModelError(f"could not start {self._binary}: {exc}") from exc

        init, payload = self._parse_stream(completed.stdout)
        if payload is None:
            detail = (completed.stderr or completed.stdout or "").strip()[:300]
            raise HeadlessModelError(f"exit {completed.returncode}, no result in output: {detail}")
        if completed.returncode != 0 or payload.get("is_error"):
            raise HeadlessModelError(f"exit {completed.returncode}: {str(payload.get('result', ''))[:300]}")

        structured = payload.get("structured_output")
        return ModelResult(
            text=str(payload.get("result") or ""),
            structured=structured if isinstance(structured, dict) else None,
            cost_usd=float(payload.get("total_cost_usd") or 0.0),
            duration_ms=int(payload.get("duration_ms") or 0),
            mcp_status={
                str(server.get("name")): str(server.get("status"))
                for server in (init or {}).get("mcp_servers") or []
                if isinstance(server, dict)
            },
            tools=tuple(str(tool) for tool in (init or {}).get("tools") or []),
        )

    @staticmethod
    def _parse_stream(stdout: str) -> tuple[dict | None, dict | None]:
        """stream-json output: the init line carries MCP server status, the last line the result."""
        init = result = None
        for line in stdout.splitlines():
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            if message.get("type") == "system" and message.get("subtype") == "init":
                init = message
            elif message.get("type") == "result":
                result = message
        return init, result

    def _argv(self, request: ModelRequest) -> list[str]:
        argv = [
            self._binary, "-p",
            "--model", request.model,
            "--output-format", "stream-json", "--verbose",
            "--no-session-persistence",
            "--settings", json.dumps({"disableAllHooks": True}),
            "--tools", "",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--max-budget-usd", str(request.max_budget_usd),
            "--system-prompt", request.system_prompt,
        ]
        if request.mcp_servers:
            argv += ["--mcp-config", json.dumps({"mcpServers": request.mcp_servers})]
        if request.allowed_tools:
            argv += ["--allowedTools", ",".join(request.allowed_tools), "--permission-mode", "dontAsk"]
        if request.json_schema is not None:
            argv += ["--json-schema", json.dumps(request.json_schema)]
        # "--" stops option parsing so a user message starting with "-" is never read as a flag.
        argv += ["--", request.user_message]
        return argv

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] = "1"
        env[self._child_env_flag] = "1"
        # Never let an outer Claude session's identity leak into the child. API keys are dropped the
        # same way the user's `claude` shell wrapper drops them, so calls bill to the logged-in plan.
        for key in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT", "CLAUDECODE",
                    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            env.pop(key, None)
        return env
