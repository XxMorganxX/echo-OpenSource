# Model

- **Endpoint:** `claude-haiku-5-5` through Claude Code headless (`claude -p`), via the shared
  `HeadlessModel` contract in [`../shared/headless_model.py`](../shared/headless_model.py). Swapping
  to a direct API call means a new `HeadlessModel` implementation; this agent does not change.
- **Why Haiku:** the job is compression of text already in hand; latency matters because the result
  is spoken.
- **Constraints:** `TIMEOUT_SECONDS` 45, `MAX_BUDGET_USD` 0.05 (from [config.py](config.py)).
  Measured cost ~$0.002 and ~3 s per call with the stripped context.
- **System prompt:** [system_prompt.md](system_prompt.md), re-read every call. The user message is
  built by `build_user_message()` in [agent.py](agent.py) from a template in config.
- **Context isolation:** no CLAUDE.md, no hooks, no MCP servers, no built-in tools (spec D4).
