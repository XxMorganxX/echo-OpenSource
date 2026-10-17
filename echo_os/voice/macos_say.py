"""Voice via macOS `say`: no setup, no network, no cost."""

from __future__ import annotations

import subprocess
from typing import Callable

from echo_os.voice.interface import VoiceError


def _run(argv: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(argv, timeout=timeout, capture_output=True, text=True)


class MacOsSay:
    def __init__(self, *, voice: str, rate_wpm: int, timeout_seconds: float, run: Callable = _run):
        self._voice, self._rate_wpm, self._timeout = voice, rate_wpm, timeout_seconds
        self._run = run

    def speak(self, text: str) -> None:
        argv = ["say"]
        if self._voice:
            argv += ["-v", self._voice]
        argv += ["-r", str(self._rate_wpm), "--", text]
        try:
            completed = self._run(argv, timeout=self._timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VoiceError(f"say failed: {exc}") from exc
        if completed.returncode != 0:
            raise VoiceError(f"say exited {completed.returncode}: {completed.stderr.strip()[:200]}")
