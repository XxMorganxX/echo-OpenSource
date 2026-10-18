"""Your knowledge-base connection: which MCP server the KB agent may use, and how.

It lives in a local, gitignored `kb.json` (see `kb.example.json` and the README), so a public
checkout carries no one's private KB. No file means no knowledge base: the agent stays off.

    {
      "server_name": "notes",                                   # MCP server name; tools are mcp__<name>__<tool>
      "mcp_server": {"type": "http", "url": "https://..."},     # Claude Code MCP config: http, sse or stdio
      "tools": ["search_notes"],                                # the only tools the agent may call
      "about": "Notes on my projects, clients and people.",    # optional: what the KB holds
      "instructions": "Use only strong matches."                # optional: appended to the system prompt
    }
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

SERVER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class KbConfigError(ValueError):
    """kb.json exists but can't be used; the message says why and names the file."""


@dataclass(frozen=True)
class KbConnection:
    server_name: str
    mcp_server: dict
    tools: tuple[str, ...]
    about: str = ""
    instructions: str = ""

    @property
    def allowed_tools(self) -> list[str]:
        return [f"mcp__{self.server_name}__{tool}" for tool in self.tools]


def load_connection(path: Path) -> KbConnection | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KbConfigError(f"{path}: not readable JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise KbConfigError(f"{path}: expected a JSON object")
    server_name, mcp_server, tools = data.get("server_name"), data.get("mcp_server"), data.get("tools")
    if not isinstance(server_name, str) or not SERVER_NAME_PATTERN.match(server_name):
        raise KbConfigError(f"{path}: server_name must be letters, digits, '-' or '_'")
    if not isinstance(mcp_server, dict) or not mcp_server:
        raise KbConfigError(f"{path}: mcp_server must be a Claude Code MCP server config object")
    if not isinstance(tools, list) or not tools or not all(isinstance(tool, str) and tool for tool in tools):
        raise KbConfigError(f"{path}: tools must be a non-empty list of tool names")
    return KbConnection(server_name=server_name, mcp_server=mcp_server, tools=tuple(tools),
                        about=str(data.get("about") or "").strip(),
                        instructions=str(data.get("instructions") or "").strip())
