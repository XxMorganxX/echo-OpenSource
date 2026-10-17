"""The echo pipeline: hook events in; call signs, headlines and speech out.

`handle_hook` runs on HTTP threads and only updates session state; a Stop returns an `EchoJob`
for the single worker. `process` runs on that worker: transcript → long-horizon gate →
KB relevance agent → headline agent → speech and history.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Protocol

from echo_os.agents.headline.agent import HeadlineAgent
from echo_os.agents.kb_relevance.agent import KbLookup, KbRelevanceAgent
from echo_os.agents.shared.headless_model import HeadlessModelError
from echo_os.agents.shared.text import truncate
from echo_os.echo.announcer import Announcement
from echo_os.echo.history import EchoHistory
from echo_os.echo.preferences import Preferences
from echo_os.sessions import SessionRegistry
from echo_os.transcript import is_long_horizon, read_last_turn

logger = logging.getLogger(__name__)

STORED_ASK_CHARS = 300


class AnnouncementQueue(Protocol):
    def announce(self, announcement: Announcement) -> None: ...


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


class EchoPipeline:
    def __init__(
        self,
        *,
        registry: SessionRegistry,
        headline_agent: HeadlineAgent,
        kb_agent: KbRelevanceAgent,
        announcer: AnnouncementQueue,
        history: EchoHistory,
        preferences: Preferences,
        kb_enabled: bool,
        min_turn_seconds: float,
        min_tool_calls: int,
        max_job_age_seconds: float,
        tracked_entrypoints: set[str],
        spoken_template: str,
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
        self._kb_status_lock = threading.Lock()
        self._kb_status: dict = {"state": "unknown", "error": None, "at": None}

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
            return None
        self.registry.touch(session_id, cwd=cwd, pid=pid, now=now)
        if event == "UserPromptSubmit":
            self.registry.mark_working(session_id, now=now)
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
        if not is_long_horizon(digest, min_seconds=self._min_turn_seconds, min_tool_calls=self._min_tool_calls):
            logger.info("Skip %s: %.0fs, %d tool calls (below threshold)",
                        job.session_id, digest.duration_seconds, digest.tool_calls)
            return None

        session = self.registry.get(job.session_id)
        if session is None or session.status == "ended":
            session = self.registry.touch(job.session_id, cwd="", now=now)
        echo = Echo(
            id=uuid.uuid4().hex[:12], created_at=now, session_id=session.session_id,
            call_sign=session.call_sign, project=session.project,
            ask=truncate(digest.ask, STORED_ASK_CHARS), tool_calls=digest.tool_calls,
            duration_seconds=round(digest.duration_seconds, 1),
        )

        kb_lookup = self._lookup_kb(digest, project=session.project)
        if kb_lookup is not None:
            echo.kb = {
                "relevant": kb_lookup.context is not None,
                "context": kb_lookup.context.context if kb_lookup.context else "",
                "sources": kb_lookup.context.sources if kb_lookup.context else [],
                "error": kb_lookup.error, "cost_usd": kb_lookup.cost_usd, "duration_ms": kb_lookup.duration_ms,
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
            echo.headline_cost_usd, echo.headline_ms = headline.cost_usd, headline.duration_ms
            echo.spoken_text = self._spoken_template.format(call_sign=echo.call_sign, headline=headline.text)
            self.registry.set_last_headline(session.session_id, headline.text, now=now)
            self._announcer.announce(Announcement(
                spoken_text=echo.spoken_text, title=echo.call_sign, subtitle=echo.project, body=echo.headline
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
        ))
        return True

    def kb_status(self) -> dict:
        with self._kb_status_lock:
            return dict(self._kb_status)

    def _lookup_kb(self, digest, *, project: str) -> KbLookup | None:
        if not self._kb_enabled:
            return None
        lookup = self._kb_agent.lookup(digest, project=project)
        with self._kb_status_lock:
            self._kb_status = {
                "state": "error" if lookup.error else ("used" if lookup.context else "not relevant"),
                "error": lookup.error, "at": time.time(),
            }
        if lookup.error:
            logger.warning("KB agent failed open: %s", lookup.error)
        return lookup
