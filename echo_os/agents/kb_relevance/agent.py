"""KB relevance agent: decides whether notes-kb has context worth adding to a headline, and fetches it.

Fails open: any problem yields no context plus the reason, never an exception.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from echo_os.agents.kb_relevance import config
from echo_os.agents.shared.headless_model import HeadlessModel, HeadlessModelError, ModelRequest
from echo_os.agents.shared.text import truncate
from echo_os.transcript import TurnDigest


@dataclass(frozen=True)
class KbContext:
    context: str
    sources: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class KbLookup:
    context: KbContext | None
    error: str | None = None
    cost_usd: float = 0.0
    duration_ms: int = 0


class KbRelevanceAgent:
    def __init__(self, model: HeadlessModel):
        self._model = model

    def lookup(self, digest: TurnDigest, *, project: str) -> KbLookup:
        request = ModelRequest(
            system_prompt=config.load_system_prompt(),
            user_message=config.USER_MESSAGE_TEMPLATE.format(
                project=project,
                max_tool_calls=config.MAX_TOOL_CALLS,
                ask=truncate(digest.ask, config.MAX_ASK_CHARS),
                response=truncate(digest.response, config.MAX_RESPONSE_CHARS),
            ),
            model=config.MODEL,
            timeout_seconds=config.TIMEOUT_SECONDS,
            max_budget_usd=config.MAX_BUDGET_USD,
            mcp_servers={config.KB_MCP_SERVER_NAME: {"type": "http", "url": config.KB_MCP_URL}},
            allowed_tools=list(config.ALLOWED_TOOLS),
            json_schema=config.OUTPUT_SCHEMA,
        )
        try:
            result = self._model.run(request)
        except HeadlessModelError as exc:
            return KbLookup(context=None, error=str(exc))

        server_status = result.mcp_status.get(config.KB_MCP_SERVER_NAME, "missing")
        if server_status != "connected":
            # The model can't search, so its "not relevant" would be meaningless. Report why.
            return KbLookup(None, f"{config.KB_MCP_SERVER_NAME} {server_status}", result.cost_usd, result.duration_ms)

        answer = result.structured
        if not isinstance(answer, dict):
            return KbLookup(None, "no structured output", result.cost_usd, result.duration_ms)
        context_text = str(answer.get("context") or "").strip()
        if not answer.get("relevant") or not context_text:
            return KbLookup(None, None, result.cost_usd, result.duration_ms)
        sources = [str(source) for source in answer.get("sources") or []]
        context = KbContext(context=truncate(context_text, config.MAX_CONTEXT_CHARS), sources=sources)
        return KbLookup(context, None, result.cost_usd, result.duration_ms)
