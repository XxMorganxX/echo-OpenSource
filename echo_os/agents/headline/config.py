"""Headline agent: every tunable value and prompt reference lives here."""

from __future__ import annotations

from pathlib import Path

MODEL = "claude-haiku-5-5"
TIMEOUT_SECONDS = 45
MAX_BUDGET_USD = 0.05

# The editable system prompt. Re-read on every call so panel edits apply to the next echo.
SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "system_prompt.md"

# Input shaping: the digest is truncated before it reaches the model.
MAX_ASK_CHARS = 1_500
MAX_RESPONSE_CHARS = 6_000
# Output shaping: safety caps in case the model ignores the length rules.
MAX_HEADLINE_CHARS = 280
# Questions and suggestions are shown as bullets on screen, never spoken.
MAX_ITEMS_PER_LIST = 4
MAX_ITEM_CHARS = 160

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "questions": {"type": "array", "items": {"type": "string"}},
        "suggestions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "questions", "suggestions"],
}

USER_MESSAGE_TEMPLATE = """\
Project: {project}
Duration: {duration}
Tool calls: {tool_calls}

What the user asked:
<ask>
{ask}
</ask>

The agent's final response:
<response>
{response}
</response>
{kb_section}
Write the headline, and list the questions and suggestions."""

KB_SECTION_TEMPLATE = """
Knowledge-base context (use only if it helps):
<kb>
{context}
</kb>
"""


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
