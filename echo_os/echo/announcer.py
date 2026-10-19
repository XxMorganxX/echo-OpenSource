"""The one way anything gets spoken: a single queue that plays announcements in order.

Every voice message (echoes, replays, `POST /api/speak`, `./echoctl say`) goes through here, so
two never play at once. Each announcement's popup appears as its speech starts, so the screen and
the voice stay in step. Mute is checked at play time: muting also silences anything already queued,
while popups keep showing. An announcement with no spoken text only pops up.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from echo_os.echo.kb_usage import KbUsage
from echo_os.echo.preferences import Preferences
from echo_os.echo.worker import QueueThread
from echo_os.transcript import BackgroundTask
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
    # Shown as bullets on the popup, never spoken; the headline points to them.
    questions: tuple[str, ...] = ()
    suggestions: tuple[str, ...] = ()
    # The Claude Code session this echo came from; its popups close when you reply to it or it ends.
    session_id: str = ""
    # The finished turn, shown in the popup's footer; None for messages that aren't echoes.
    duration_seconds: float | None = None
    tool_calls: int | None = None
    finished_at: float | None = None  # epoch seconds
    # The working directory's slot in settings.DIRECTORY_COLORS; None draws the card neutral.
    color: int | None = None
    # The session's Claude process, so a click on the popup can find its terminal tab; None when
    # there is no live session (/api/speak, a replay after the session ended).
    pid: int | None = None
    # Set for the minimal "background task finished" card; `body` is then the start of Claude's reply.
    background_tasks: tuple[BackgroundTask, ...] = ()
    # Set for the one-line "done" chip on a turn too short for an echo; `body` is then empty.
    turn_done: bool = False


class Popup(Protocol):
    def show(self, announcement: "Announcement", *, speaking: bool) -> None:
        """Displays the popup and returns at once. `speaking` is False when speech is muted."""

    def finished_speaking(self, announcement: "Announcement") -> None:
        """The voice is done with this announcement (spoken, or failed)."""

    def resolve(self, session_id: str) -> None:
        """Closes the session's popups that wait for an answer (you replied, or the session ended)."""


class Announcer(QueueThread):
    def __init__(self, *, voice: VoiceOutput, preferences: Preferences, popup: Popup | None):
        super().__init__("echo-announcer")
        self._voice, self._preferences, self._popup = voice, preferences, popup

    def announce(self, announcement: Announcement) -> None:
        self._put(announcement)

    def resolve(self, session_id: str) -> None:
        """Immediate, not queued: an answered question should disappear now, not after queued speech."""
        if self._popup is not None:
            try:
                self._popup.resolve(session_id)
            except Exception:
                logger.exception("Popup resolve failed")

    def _handle(self, announcement: Announcement) -> None:
        speaking = bool(announcement.spoken_text) and not self._preferences.muted
        self._tell_popup("show", announcement, speaking=speaking)
        if not speaking:
            return
        try:
            self._voice.speak(announcement.spoken_text)
        except VoiceError as exc:
            logger.error("Speech failed: %s", exc)
        self._tell_popup("finished_speaking", announcement)

    def _tell_popup(self, method: str, *args, **kwargs) -> None:
        if self._popup is None:
            return
        try:
            getattr(self._popup, method)(*args, **kwargs)
        except Exception:
            logger.exception("Popup %s failed", method)
