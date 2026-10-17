"""Headline agent: turns a finished turn into one or two speakable sentences."""

from __future__ import annotations

from dataclasses import dataclass

from echo_os.agents.headline import config
from echo_os.agents.kb_relevance.agent import KbContext
from echo_os.agents.shared.headless_model import HeadlessModel, HeadlessModelError, ModelRequest
from echo_os.agents.shared.text import to_speech, truncate
from echo_os.transcript import TurnDigest


@dataclass(frozen=True)
class Headline:
    text: str
    cost_usd: float
    duration_ms: int


def spoken_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} seconds"
    hours, minutes = divmod(seconds // 60, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
    if minutes:
        parts.append(f"{minutes} minute" + ("s" if minutes != 1 else ""))
    return " ".join(parts)


class HeadlineAgent:
    def __init__(self, model: HeadlessModel):
        self._model = model

    def write(self, digest: TurnDigest, *, project: str, kb_context: KbContext | None = None) -> Headline:
        kb_section = config.KB_SECTION_TEMPLATE.format(context=kb_context.context) if kb_context else ""
        request = ModelRequest(
            system_prompt=config.load_system_prompt(),
            user_message=config.USER_MESSAGE_TEMPLATE.format(
                project=project,
                duration=spoken_duration(digest.duration_seconds),
                tool_calls=digest.tool_calls,
                ask=truncate(digest.ask, config.MAX_ASK_CHARS),
                response=truncate(digest.response, config.MAX_RESPONSE_CHARS),
                kb_section=kb_section,
            ),
            model=config.MODEL,
            timeout_seconds=config.TIMEOUT_SECONDS,
            max_budget_usd=config.MAX_BUDGET_USD,
        )
        result = self._model.run(request)
        text = truncate(to_speech(result.text), config.MAX_HEADLINE_CHARS)
        if not text:
            raise HeadlessModelError("model returned an empty headline")
        return Headline(text=text, cost_usd=result.cost_usd, duration_ms=result.duration_ms)
