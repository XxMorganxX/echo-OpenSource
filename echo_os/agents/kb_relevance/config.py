"""KB relevance agent: every tunable value and prompt reference lives here.

Which knowledge base to use is not here: that's your local kb.json (see connection.py).
"""

from __future__ import annotations

import re
from pathlib import Path

MODEL = "claude-haiku-5-5"
TIMEOUT_SECONDS = 40
MAX_BUDGET_USD = 0.05
MAX_TOOL_CALLS = 3  # stated in the prompt; budget and timeout enforce it hard

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "system_prompt.md"

# Filled into system_prompt.md's {about} and {instructions} from kb.json; empty fields leave nothing.
ABOUT_TEMPLATE = "About this knowledge base: {about}"
INSTRUCTIONS_TEMPLATE = "\nInstructions for this knowledge base:\n{instructions}"

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


def load_system_prompt(*, about: str = "", instructions: str = "") -> str:
    # str.replace, not format: the prompt file and the user's instructions may contain braces.
    template = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.replace("{about}", ABOUT_TEMPLATE.format(about=about) if about else "")
    prompt = prompt.replace("{instructions}", INSTRUCTIONS_TEMPLATE.format(instructions=instructions) if instructions else "")
    # An empty placeholder leaves an extra blank line behind.
    return re.sub(r"\n{3,}", "\n\n", prompt).strip()
