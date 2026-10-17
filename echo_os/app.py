"""Composition root: builds the running echo-OS service from settings.

Everything provider-shaped (model, voice) is chosen here, once. The HTTP server and menu bar app
only see `EchoApp`.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from echo_os import settings
from echo_os.agents.headline import config as headline_config
from echo_os.echo.pipeline import EchoJob, EchoPipeline

MAX_PROMPT_CHARS = 20_000


class JobSink(Protocol):
    def submit(self, job: EchoJob) -> None: ...


@dataclass
class EchoApp:
    pipeline: EchoPipeline
    worker: JobSink
    prompt_path: Path
    recent_limit: int
    thresholds: dict
    voice_provider: str
    background: list = field(default_factory=list)  # threads to start/stop with the app

    def start(self) -> None:
        for part in self.background:
            part.start()

    def stop(self) -> None:
        for part in reversed(self.background):
            part.stop()

    def handle_hook(self, payload: dict, *, entrypoint: str, pid: int | None) -> None:
        job = self.pipeline.handle_hook(payload, entrypoint=entrypoint, pid=pid, now=time.time())
        if job is not None:
            self.worker.submit(job)

    def state(self) -> dict:
        return {
            "sessions": [asdict(session) for session in self.pipeline.registry.active()],
            "echoes": self.pipeline.history.recent(self.recent_limit),
            "muted": self.pipeline.preferences.muted,
            "kb": self.pipeline.kb_status(),
            "thresholds": self.thresholds,
            "voice": self.voice_provider,
        }

    def read_prompt(self) -> str:
        return self.prompt_path.read_text(encoding="utf-8")

    def write_prompt(self, text: str) -> None:
        text = text.strip()
        if not text:
            raise ValueError("The system prompt can't be empty.")
        if len(text) > MAX_PROMPT_CHARS:
            raise ValueError(f"The system prompt is over {MAX_PROMPT_CHARS} characters.")
        tmp = self.prompt_path.with_suffix(".tmp")
        tmp.write_text(text + "\n", encoding="utf-8")
        tmp.replace(self.prompt_path)


def build_app() -> EchoApp:
    """The real service, wired from settings. Imports are local so tests never touch providers."""
    from echo_os.agents.headline.agent import HeadlineAgent
    from echo_os.agents.kb_relevance.agent import KbRelevanceAgent
    from echo_os.agents.shared.headless_model import ClaudeCodeHeadless
    from echo_os.echo.history import EchoHistory
    from echo_os.echo.preferences import Preferences
    from echo_os.echo.worker import EchoWorker, PeriodicTask, QueuedSpeaker
    from echo_os.sessions import SessionRegistry
    from echo_os.voice import create_voice

    model = ClaudeCodeHeadless(binary=settings.CLAUDE_BINARY, workdir=settings.HEADLESS_WORKDIR,
                               child_env_flag=settings.CHILD_ENV_FLAG)
    registry = SessionRegistry(settings.SESSIONS_PATH, call_signs=settings.CALL_SIGNS,
                               idle_expiry_seconds=settings.SESSION_IDLE_EXPIRY_SECONDS)
    speaker = QueuedSpeaker(create_voice())
    pipeline = EchoPipeline(
        registry=registry,
        headline_agent=HeadlineAgent(model),
        kb_agent=KbRelevanceAgent(model),
        speaker=speaker,
        history=EchoHistory(settings.ECHOES_PATH),
        preferences=Preferences(settings.PREFERENCES_PATH),
        kb_enabled=settings.KB_AGENT_ENABLED,
        min_turn_seconds=settings.MIN_TURN_SECONDS,
        min_tool_calls=settings.MIN_TOOL_CALLS,
        max_job_age_seconds=settings.MAX_JOB_AGE_SECONDS,
        tracked_entrypoints=settings.TRACKED_ENTRYPOINTS,
        spoken_template=settings.SPOKEN_TEMPLATE,
    )
    worker = EchoWorker(pipeline.process, settle_seconds=settings.TRANSCRIPT_SETTLE_SECONDS)
    sweeper = PeriodicTask(lambda: registry.sweep(now=time.time()),
                           interval_seconds=settings.SESSION_SWEEP_INTERVAL_SECONDS, name="session-sweeper")
    return EchoApp(
        pipeline=pipeline,
        worker=worker,
        prompt_path=headline_config.SYSTEM_PROMPT_PATH,
        recent_limit=settings.RECENT_ECHOES_LIMIT,
        thresholds={"min_turn_seconds": settings.MIN_TURN_SECONDS, "min_tool_calls": settings.MIN_TOOL_CALLS},
        voice_provider=settings.VOICE_PROVIDER,
        background=[speaker, worker, sweeper],
    )
