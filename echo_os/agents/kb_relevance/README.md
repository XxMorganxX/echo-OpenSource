# KB relevance agent

Decides whether the personal knowledge base (notes-kb) holds context that would make a headline more
meaningful, and if so fetches it.

- **In:** a `TurnDigest`.
- **Out:** a `KbContext` (`relevant`, one or two sentences of `context`, `sources`) or `None`.
- **Fails open:** notes-kb down, unauthenticated, slow, or returning junk → `None`, and the headline is
  written without it.
- **Run:** called by `echo_os.echo.pipeline` when `KB_AGENT_ENABLED`; try it with
  `./echo kb <transcript.jsonl>`.

Component docs: [model](model.md) · [tools](tool-registry.md) · [control loop](control-loop.md) ·
[state](state.md) · [memory](memory.md) · [logging](logging.md). Parameters: [config.py](config.py).
System prompt: [system_prompt.md](system_prompt.md).
