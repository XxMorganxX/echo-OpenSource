"""Whether your knowledge-base server is logged in, for the panel's status light.

Two sources: `claude mcp get <server>` (no model call, ~3 s) run at startup, on a timer and on
demand; and the server status every KB lookup reports, which catches an expired login the moment
an echo hits it.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

CHECK_TIMEOUT_SECONDS = 30
# Checked in order: "Connected · tools fetch failed" must not read as connected.
STATUS_PATTERNS = (("tools fetch failed", "tools-failed"), ("Needs authentication", "needs-auth"),
                   ("Connected", "connected"), ("Failed", "failed"))
# States in which a lookup can't succeed. Echoes skip the lookup (and its wait, up to ~30 s for a
# server that won't list its tools) until a check or a lookup sees the server healthy again.
UNUSABLE_STATES = {"needs-auth", "failed", "tools-failed"}


def parse_mcp_get(output: str) -> str:
    if output.startswith("No MCP server named"):
        return "missing"
    for line in output.splitlines():
        if line.strip().startswith("Status:"):
            for needle, state in STATUS_PATTERNS:
                if needle in line:
                    return state
    return "unknown"


def _run_process(argv: list[str], *, env: dict, cwd: Path, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(argv, env=env, cwd=cwd, timeout=timeout, capture_output=True, text=True, stdin=subprocess.DEVNULL)


class KbAuthMonitor:
    def __init__(self, *, binary: str, server_name: str, workdir: Path, child_env_flag: str,
                 run_process: Callable = _run_process, clock: Callable[[], float] = time.time):
        self._binary, self._server_name, self._workdir = binary, server_name, workdir
        self._child_env_flag, self._run_process, self._clock = child_env_flag, run_process, clock
        self._lock = threading.Lock()
        self._state, self._checked_at, self._source = "unknown", None, None

    def check(self) -> None:
        env = dict(os.environ)
        env[self._child_env_flag] = "1"
        for key in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT", "CLAUDECODE"):
            env.pop(key, None)
        self._workdir.mkdir(parents=True, exist_ok=True)
        try:
            completed = self._run_process([self._binary, "mcp", "get", self._server_name], env=env,
                                          cwd=self._workdir, timeout=CHECK_TIMEOUT_SECONDS)
            state = parse_mcp_get((completed.stdout or "") + (completed.stderr or ""))
        except (OSError, subprocess.TimeoutExpired):
            state = "unknown"
        with self._lock:
            # A server attached only through kb.json isn't registered in Claude Code, so `mcp get`
            # can't see it; what the last lookup saw is the better answer then.
            if state == "missing" and self._source == "kb lookup":
                return
        self._set(state, "check")

    def observe(self, state: str) -> None:
        """Server status seen by a KB lookup; fresher than the last check."""
        self._set(state, "kb lookup")

    def snapshot(self) -> dict:
        with self._lock:
            return {"state": self._state, "checked_at": self._checked_at, "source": self._source}

    def _set(self, state: str, source: str) -> None:
        with self._lock:
            self._state, self._checked_at, self._source = state, self._clock(), source
