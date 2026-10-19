"""The echo pipeline: hook events in; call signs, headlines and speech out.

`handle_hook` runs on HTTP threads and only updates session state; a Stop returns an `EchoJob`
for the single worker. `process` runs on that worker: transcript → long-horizon gate →
KB relevance agent → headline agent → speech and history. A turn below the gate gets a minimal
silent popup instead (no model call, not in history): the finished background tasks that started it,
or else a one-line "done" chip.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Protocol

from echo_os.agents.headline.agent import HeadlineAgent
from echo_os.agents.kb_relevance.agent import KbLookup
from echo_os.kb_status import UNUSABLE_STATES
from echo_os.agents.shared.headless_model import HeadlessModelError
from echo_os.agents.shared.text import to_speech, truncate
from echo_os.echo.announcer import Announcement
from echo_os.echo.history import EchoHistory
from echo_os.echo.kb_usage import kb_usage_from_record
from echo_os.echo.preferences import Preferences
from echo_os.sessions import SessionRegistry
from echo_os.transcript import BackgroundTask, is_long_horizon, read_last_turn, TurnDigest

logger = logging.getLogger(__name__)

STORED_ASK_CHARS = 300
BACKGROUND_ASK_PREFIX = "Background task finished: "


class KnowledgeLookup(Protocol):
    """Where KB context comes from. The default is KbRelevanceAgent (any MCP server, via kb.json);
    to use something else (a local notes folder, a database, an HTTP API), implement this and pass it
    as `kb_agent` in app.build_app. Fail open: return KbLookup(None, error=...) instead of raising."""

    def lookup(self, digest: TurnDigest, *, project: str) -> KbLookup: ...


class AnnouncementQueue(Protocol):
    def announce(self, announcement: Announcement) -> None: ...

    def resolve(self, session_id: str) -> None: ...


@dataclass(frozen=True)
class EchoJob:
    session_id: str
    transcript_path: str
    ended_at: float
    queued_at: float
    last_assistant_message: str | None = None


@dataclass
class Echo:
    id: str
    created_at: float
    session_id: str
    call_sign: str
    project: str
    ask: str
    tool_calls: int
    duration_seconds: float
    headline: str = ""
    spoken_text: str = ""
    kb: dict | None = None
    headline_cost_usd: float = 0.0
    headline_ms: int = 0
    total_ms: int = 0
    error: str | None = None
    questions: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    color: int | None = None  # the working directory's color slot


def spoken_name(project: str) -> str:
    """A folder name as a voice should say it: "web-app" → "web app"."""
    return " ".join(re.split(r"[-_.\s]+", project)).strip()


def spoken_text(template: str, *, project: str, call_sign: str, headline: str) -> str:
    """The words spoken for an echo. The project and call sign come from here, never from a model."""
    text = template.format(project=spoken_name(project), call_sign=call_sign, headline=headline)
    return text.lstrip(" ,.")  # a session with no known directory leaves the separator behind


class EchoPipeline:
    def __init__(
        self,
        *,
        registry: SessionRegistry,
        headline_agent: HeadlineAgent,
        kb_agent: KnowledgeLookup | None,
        announcer: AnnouncementQueue,
        history: EchoHistory,
        preferences: Preferences,
        kb_enabled: bool,
        min_turn_seconds: float,
        min_tool_calls: int,
        max_job_age_seconds: float,
        tracked_entrypoints: set[str],
        spoken_template: str,
        background_detail_chars: int,
        turn_done_popups: bool,
    ):
        self.registry = registry
        self.history = history
        self.preferences = preferences
        self._headline_agent = headline_agent
        self._kb_agent = kb_agent
        self._announcer = announcer
        self._kb_enabled = kb_enabled
        self._min_turn_seconds = min_turn_seconds
        self._min_tool_calls = min_tool_calls
        self._max_job_age_seconds = max_job_age_seconds
        self._tracked_entrypoints = tracked_entrypoints
        self._spoken_template = spoken_template
        self._background_detail_chars = background_detail_chars
        self._turn_done_popups = turn_done_popups
        self._kb_status_lock = threading.Lock()
        self._kb_status: dict = {"state": "unknown", "error": None, "at": None}
        # Optional KbAuthMonitor (the panel's KB light); each lookup reports what it saw.
        self.kb_monitor = None

    # -- Hook ingress (HTTP threads) --------------------------------------------------------
    def handle_hook(self, payload: dict, *, entrypoint: str, pid: int | None, now: float) -> EchoJob | None:
        # An empty entrypoint means an older hook script; track rather than silently drop.
        if entrypoint and entrypoint not in self._tracked_entrypoints:
            return None
        event = payload.get("hook_event_name")
        session_id = payload.get("session_id")
        if not session_id:
            return None
        cwd = payload.get("cwd") or ""

        if event == "SessionEnd":
            self.registry.end(session_id)
            self._announcer.resolve(session_id)
            return None
        self.registry.touch(session_id, cwd=cwd, pid=pid, now=now)
        if event == "UserPromptSubmit":
            self.registry.mark_working(session_id, now=now)
            # You replied to this session, so its questions are answered.
            self._announcer.resolve(session_id)
        elif event == "Stop":
            self.registry.mark_idle(session_id, now=now)
            transcript_path = payload.get("transcript_path")
            if transcript_path:
                return EchoJob(session_id, transcript_path, ended_at=now, queued_at=now,
                               last_assistant_message=payload.get("last_assistant_message"))
        return None

    # -- Worker ----------------------------------------------------------------------------------
    def process(self, job: EchoJob, *, now: float | None = None) -> Echo | None:
        started = time.monotonic()
        now = time.time() if now is None else now
        if now - job.queued_at > self._max_job_age_seconds:
            logger.info("Dropping stale job for %s (%.0fs old)", job.session_id, now - job.queued_at)
            return None

        digest = read_last_turn(job.transcript_path, ended_at=job.ended_at,
                                last_assistant_message=job.last_assistant_message)
        if digest is None:
            logger.info("No readable turn in %s", job.transcript_path)
            return None
        long_horizon = is_long_horizon(digest, min_seconds=self._min_turn_seconds, min_tool_calls=self._min_tool_calls)
        if not long_horizon and not digest.background_tasks and not self._turn_done_popups:
            logger.info("Skip %s: %.0fs, %d tool calls (below threshold)",
                        job.session_id, digest.duration_seconds, digest.tool_calls)
            return None

        session = self.registry.get(job.session_id)
        if session is None or session.status == "ended":
            session = self.registry.touch(job.session_id, cwd="", now=now)
        if not long_horizon:
            self._announce_short_turn(digest, session)
            return None
        ask = digest.ask or BACKGROUND_ASK_PREFIX + ", ".join(task.label for task in digest.background_tasks)
        echo = Echo(
            id=uuid.uuid4().hex[:12], created_at=now, session_id=session.session_id,
            call_sign=session.call_sign, project=session.project, color=session.color,
            ask=truncate(ask, STORED_ASK_CHARS), tool_calls=digest.tool_calls,
            duration_seconds=round(digest.duration_seconds, 1),
        )

        kb_lookup = self._lookup_kb(digest, project=session.project)
        if kb_lookup is not None:
            echo.kb = {
                "relevant": kb_lookup.context is not None,
                "context": kb_lookup.context.context if kb_lookup.context else "",
                "sources": kb_lookup.context.sources if kb_lookup.context else [],
                "error": kb_lookup.error, "server_status": kb_lookup.server_status,
                "cost_usd": kb_lookup.cost_usd, "duration_ms": kb_lookup.duration_ms,
            }

        try:
            headline = self._headline_agent.write(
                digest, project=session.project, kb_context=kb_lookup.context if kb_lookup else None
            )
        except HeadlessModelError as exc:
            echo.error = str(exc)
            logger.error("Headline failed for %s: %s", echo.call_sign, exc)
        else:
            echo.headline = headline.text
            echo.questions, echo.suggestions = list(headline.questions), list(headline.suggestions)
            echo.headline_cost_usd, echo.headline_ms = headline.cost_usd, headline.duration_ms
            echo.spoken_text = spoken_text(self._spoken_template, project=echo.project, call_sign=echo.call_sign,
                                           headline=headline.text)
            self.registry.set_last_headline(session.session_id, headline.text, now=now)
            self._announcer.announce(Announcement(
                spoken_text=echo.spoken_text, title=echo.call_sign, subtitle=echo.project, body=echo.headline,
                kb_usage=kb_usage_from_record(echo.kb),
                questions=tuple(echo.questions), suggestions=tuple(echo.suggestions), session_id=echo.session_id,
                duration_seconds=echo.duration_seconds, tool_calls=echo.tool_calls, finished_at=echo.created_at,
                color=echo.color, pid=session.pid,
            ))

        echo.total_ms = int((time.monotonic() - started) * 1000)
        self.history.append(asdict(echo))
        logger.info("Echo %s %s: %r (kb=%s, %dms)", echo.id, echo.call_sign, echo.headline or echo.error,
                    "used" if echo.kb and echo.kb["relevant"] else "none", echo.total_ms)
        return echo

    def replay(self, echo_id: str) -> bool:
        record = self.history.get(echo_id)
        if not record or not record.get("spoken_text"):
            return False
        self._announcer.announce(Announcement(
            spoken_text=record["spoken_text"], title=record.get("call_sign", ""),
            subtitle=record.get("project", ""), body=record.get("headline", ""),
            kb_usage=kb_usage_from_record(record.get("kb")),
            questions=tuple(record.get("questions") or ()), suggestions=tuple(record.get("suggestions") or ()),
            session_id=record.get("session_id", ""),
            duration_seconds=record.get("duration_seconds"), tool_calls=record.get("tool_calls"),
            finished_at=record.get("created_at"), color=record.get("color"),
            pid=self._live_pid(record.get("session_id", "")),
        ))
        return True

    def _announce_short_turn(self, digest: TurnDigest, session) -> None:
        """The minimal silent card for the background tasks that started this turn, or else the "done" chip."""
        tasks: tuple[BackgroundTask, ...] = digest.background_tasks
        if tasks:
            logger.info("Background done %s: %s", session.call_sign,
                        ", ".join(f"{t.label} ({t.status})" for t in tasks))
        else:
            logger.info("Turn done %s: %.0fs, %d tool calls (below threshold)",
                        session.call_sign, digest.duration_seconds, digest.tool_calls)
        self._announcer.announce(Announcement(
            spoken_text="", title=session.call_sign, subtitle=session.project,
            body=truncate(to_speech(digest.response), self._background_detail_chars) if tasks else "",
            session_id=session.session_id, color=session.color, pid=session.pid, background_tasks=tasks,
            turn_done=not tasks, duration_seconds=round(digest.duration_seconds, 1), tool_calls=digest.tool_calls,
        ))

    def _live_pid(self, session_id: str) -> int | None:
        session = self.registry.get(session_id)
        return session.pid if session is not None and session.status != "ended" else None

    def kb_status(self) -> dict:
        with self._kb_status_lock:
            return dict(self._kb_status)

    def _lookup_kb(self, digest, *, project: str) -> KbLookup | None:
        if not self._kb_enabled:
            return None
        known_state = self.kb_monitor.snapshot().get("state") if self.kb_monitor is not None else None
        skipped = known_state in UNUSABLE_STATES
        if skipped:
            lookup = KbLookup(None, error=f"skipped: KB {known_state}", server_status=known_state)
        else:
            lookup = self._kb_agent.lookup(digest, project=project)
        with self._kb_status_lock:
            self._kb_status = {
                "state": "error" if lookup.error else ("used" if lookup.context else "not relevant"),
                "error": lookup.error, "at": time.time(),
            }
        if lookup.server_status and self.kb_monitor is not None and not skipped:
            self.kb_monitor.observe(lookup.server_status)
        if lookup.error:
            logger.warning("KB agent failed open: %s", lookup.error)
        return lookup
