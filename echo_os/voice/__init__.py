"""Voice output: one entry point picks the provider from settings."""

from __future__ import annotations

import logging

from echo_os import settings
from echo_os.voice.interface import VoiceError, VoiceOutput
from echo_os.voice.macos_say import MacOsSay
from echo_os.voice.openai_tts import OpenAiTts

logger = logging.getLogger(__name__)

__all__ = ["VoiceError", "VoiceOutput", "create_voice"]


def create_voice(provider: str | None = None) -> VoiceOutput:
    provider = provider or settings.VOICE_PROVIDER
    say = MacOsSay(voice=settings.MACOS_SAY_VOICE, rate_wpm=settings.MACOS_SAY_RATE_WPM,
                   timeout_seconds=settings.VOICE_TIMEOUT_SECONDS)
    if provider == "macos-say":
        return say
    if provider == "openai":
        if not settings.OPENAI_API_KEY:
            logger.warning("ECHO_OS_VOICE=openai but OPENAI_API_KEY is empty; using macOS say")
            return say
        return OpenAiTts(
            api_key=settings.OPENAI_API_KEY, model=settings.OPENAI_TTS_MODEL, voice=settings.OPENAI_TTS_VOICE,
            instructions=settings.OPENAI_TTS_INSTRUCTIONS, timeout_seconds=settings.VOICE_TIMEOUT_SECONDS,
            workdir=settings.STATE_ROOT / "audio",
        )
    raise ValueError(f"Unknown voice provider: {provider!r} (expected macos-say or openai)")
