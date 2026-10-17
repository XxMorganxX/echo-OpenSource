"""The contract every voice provider implements. Callers depend on this, never on a provider."""

from __future__ import annotations

from typing import Protocol


class VoiceError(RuntimeError):
    pass


class VoiceOutput(Protocol):
    def speak(self, text: str) -> None:
        """Speaks `text` and returns when playback ends. Raises VoiceError on failure."""
