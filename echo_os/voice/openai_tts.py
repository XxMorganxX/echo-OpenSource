"""Voice via OpenAI text-to-speech, played with `afplay`."""

from __future__ import annotations

import json
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from echo_os.voice.interface import VoiceError

SPEECH_URL = "https://api.openai.com/v1/audio/speech"


def _post(url: str, body: bytes, headers: dict, timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _run(argv: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(argv, timeout=timeout, capture_output=True, text=True)


class OpenAiTts:
    def __init__(self, *, api_key: str, model: str, voice: str, instructions: str, timeout_seconds: float,
                 workdir: Path, post: Callable = _post, run: Callable = _run):
        self._api_key, self._model, self._voice, self._instructions = api_key, model, voice, instructions
        self._timeout, self._workdir = timeout_seconds, workdir
        self._post, self._run = post, run

    def speak(self, text: str) -> None:
        body = json.dumps({
            "model": self._model, "voice": self._voice, "input": text,
            "instructions": self._instructions, "response_format": "mp3",
        }).encode()
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        try:
            audio = self._post(SPEECH_URL, body, headers, self._timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise VoiceError(f"OpenAI TTS request failed: {exc}") from exc

        self._workdir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=self._workdir, delete=False) as handle:
            handle.write(audio)
            path = Path(handle.name)
        try:
            completed = self._run(["afplay", str(path)], timeout=self._timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VoiceError(f"afplay failed: {exc}") from exc
        finally:
            path.unlink(missing_ok=True)
        if completed.returncode != 0:
            raise VoiceError(f"afplay exited {completed.returncode}")
