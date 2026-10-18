# Model

- **Endpoint:** `claude-haiku-5-5` through Claude Code headless, via the shared `HeadlessModel`
  contract. Same isolation as the headline agent, except the MCP server from your kb.json is attached.
- **Output:** structured, via `--json-schema` (`relevant`, `context`, `sources`). The schema is in
  [config.py](config.py).
- **Constraints:** `TIMEOUT_SECONDS` 40, `MAX_BUDGET_USD` 0.05.
- **System prompt:** [system_prompt.md](system_prompt.md).
