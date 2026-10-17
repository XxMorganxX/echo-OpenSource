# Headline agent

Turns one finished Claude Code turn into a spoken headline of one or two short sentences.

- **In:** a `TurnDigest` (project, the user's ask, the final response, tool count, duration) and an
  optional `KbContext` from the [KB relevance agent](../kb_relevance/README.md).
- **Out:** plain speakable text. The call sign ("Charlie.") is prepended by the pipeline, not the
  model, so it is always right.
- **Run:** called by `echo_os.echo.pipeline`; try it by hand with `./echo headline <transcript.jsonl>`.

Component docs: [model](model.md) · [tools](tool-registry.md) · [control loop](control-loop.md) ·
[state](state.md) · [memory](memory.md) · [logging](logging.md). Parameters: [config.py](config.py).
System prompt (editable from the panel): [system_prompt.md](system_prompt.md).
