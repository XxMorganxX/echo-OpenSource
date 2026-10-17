"""KB relevance agent: every tunable value and prompt reference lives here."""

from __future__ import annotations

from pathlib import Path

MODEL = "claude-haiku-5-5"
TIMEOUT_SECONDS = 40
MAX_BUDGET_USD = 0.05
MAX_TOOL_CALLS = 3  # stated in the prompt; budget and timeout enforce it hard

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "system_prompt.md"

KB_MCP_SERVER_NAME = "notes-kb"
KB_MCP_URL = "https://kb.example.com/mcp"
ALLOWED_TOOLS = [
    f"mcp__{KB_MCP_SERVER_NAME}__search_memories",
    f"mcp__{KB_MCP_SERVER_NAME}__find_entity",
]

MAX_ASK_CHARS = 1_500
MAX_RESPONSE_CHARS = 3_000
MAX_CONTEXT_CHARS = 400

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "context": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["relevant", "context", "sources"],
}

USER_MESSAGE_TEMPLATE = """\
Project: {project}
At most {max_tool_calls} tool calls.

What the user asked:
<ask>
{ask}
</ask>

The agent's final response:
<response>
{response}
</response>"""


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
