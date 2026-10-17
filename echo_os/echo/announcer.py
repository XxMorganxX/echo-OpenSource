"""The one way anything gets spoken: a single queue that plays announcements in order.

Every voice message (echoes, replays, `POST /api/speak`, `./echoctl say`) goes through here, so
two never play at once. Each announcement's popup appears as its speech starts, so the screen and
the voice stay in step. Mute is checked at play time: muting also silences anything already queued,
while popups keep showing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from echo_os.echo.kb_usage import KbUsage
from echo_os.echo.preferences import Preferences
from echo_os.echo.worker import QueueThread
from echo_os.voice import VoiceError, VoiceOutput

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Announcement:
    spoken_text: str
    title: str  # call sign, or the caller's name for /api/speak
    subtitle: str  # project
    body: str  # headline
    # How the KB figured in this echo; None for messages that aren't echoes (e.g. /api/speak).
    kb_usage: KbUsage | None = None


class Popup(Protocol):
    def show(self, *, title: str, subtitle: str, body: str, kb_usage: KbUsage | None) -> None:
        """Displays the popup and returns at once (it dismisses itself)."""


class Announcer(QueueThread):
    def __init__(self, *, voice: VoiceOutput, preferences: Preferences, popup: Popup | None):
        super().__init__("echo-announcer")
        self._voice, self._preferences, self._popup = voice, preferences, popup

    def announce(self, announcement: Announcement) -> None:
        self._put(announcement)

    def _handle(self, announcement: Announcement) -> None:
        if self._popup is not None:
            try:
                self._popup.show(title=announcement.title, subtitle=announcement.subtitle, body=announcement.body,
                                 kb_usage=announcement.kb_usage)
            except Exception:
                logger.exception("Popup failed")
        if self._preferences.muted:
            return
        try:
            self._voice.speak(announcement.spoken_text)
        except VoiceError as exc:
            logger.error("Speech failed: %s", exc)
