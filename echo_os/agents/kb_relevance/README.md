# KB relevance agent

Decides whether your knowledge base holds context that would make a headline more meaningful, and if
so fetches it. Any MCP server works; you connect yours in a local `kb.json` (see the repo README,
"Connect your own knowledge base"). No `kb.json`, no KB agent.

- **In:** a `TurnDigest`.
- **Out:** a `KbContext` (`relevant`, one or two sentences of `context`, `sources`) or `None`.
- **Fails open:** the KB server down, logged out, slow, or returning junk → `None`, and the headline is
  written without it.
- **Run:** called by `echo_os.echo.pipeline` when a kb.json is present; try it with
  `./echoctl kb <transcript.jsonl>`.

Not using MCP? Implement `KnowledgeLookup` (in `echo_os/echo/pipeline.py`) and pass it as
`kb_agent` in `echo_os/app.py`; this agent is just the default implementation.

Component docs: [model](model.md) · [tools](tool-registry.md) · [control loop](control-loop.md) ·
[state](state.md) · [memory](memory.md) · [logging](logging.md). Parameters: [config.py](config.py).
System prompt: [system_prompt.md](system_prompt.md) (`{about}` and `{instructions}` come from kb.json).
Connection: [connection.py](connection.py).
