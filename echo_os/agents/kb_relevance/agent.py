"""KB relevance agent: decides whether your knowledge base has context worth adding to a headline,
and fetches it through the MCP server named in your kb.json.

Fails open: any problem yields no context plus the reason, never an exception.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from echo_os.agents.kb_relevance import config
from echo_os.agents.kb_relevance.connection import KbConnection
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
    # The KB server's connection status as the call saw it ("connected", "needs-auth", ...); None if unknown.
    server_status: str | None = None


class KbRelevanceAgent:
    """The default `KnowledgeLookup` (see echo/pipeline.py): any MCP knowledge base, via kb.json."""

    def __init__(self, model: HeadlessModel, connection: KbConnection):
        self._model = model
        self._connection = connection

    def lookup(self, digest: TurnDigest, *, project: str) -> KbLookup:
        connection = self._connection
        request = ModelRequest(
            system_prompt=config.load_system_prompt(about=connection.about, instructions=connection.instructions),
            user_message=config.USER_MESSAGE_TEMPLATE.format(
                project=project,
                max_tool_calls=config.MAX_TOOL_CALLS,
                ask=truncate(digest.ask, config.MAX_ASK_CHARS),
                response=truncate(digest.response, config.MAX_RESPONSE_CHARS),
            ),
            model=config.MODEL,
            timeout_seconds=config.TIMEOUT_SECONDS,
            max_budget_usd=config.MAX_BUDGET_USD,
            mcp_servers={connection.server_name: dict(connection.mcp_server)},
            allowed_tools=connection.allowed_tools,
            json_schema=config.OUTPUT_SCHEMA,
        )
        try:
            result = self._model.run(request)
        except HeadlessModelError as exc:
            return KbLookup(context=None, error=str(exc))

        server_status = result.mcp_status.get(connection.server_name, "missing")
        cost = dict(cost_usd=result.cost_usd, duration_ms=result.duration_ms)
        # If the model couldn't search, its "not relevant" would be meaningless. Report why instead.
        if not set(connection.allowed_tools) & set(result.tools):
            if server_status == "connected":  # connected, but listing its tools failed or timed out
                return KbLookup(None, f"{connection.server_name} tools unavailable", server_status="tools-failed", **cost)
            return KbLookup(None, f"{connection.server_name} {server_status}", server_status=server_status, **cost)
        cost["server_status"] = server_status
        if server_status != "connected":
            return KbLookup(None, f"{connection.server_name} {server_status}", **cost)

        answer = result.structured
        if not isinstance(answer, dict):
            return KbLookup(None, "no structured output", **cost)
        context_text = str(answer.get("context") or "").strip()
        if not answer.get("relevant") or not context_text:
            return KbLookup(None, None, **cost)
        sources = [str(source) for source in answer.get("sources") or []]
        context = KbContext(context=truncate(context_text, config.MAX_CONTEXT_CHARS), sources=sources)
        return KbLookup(context, None, **cost)
