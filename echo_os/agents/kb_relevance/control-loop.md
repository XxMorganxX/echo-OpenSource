# Control loop

Claude Code headless runs the tool loop. The agent's own limits:

- **Relevance first:** the prompt tells the model to answer `relevant: false` without calling tools
  when the turn names nothing specific (generic refactors, test fixes).
- **Call cap:** the prompt allows at most `MAX_TOOL_CALLS` (3) calls; `--max-budget-usd` and the
  subprocess timeout enforce it hard.
- **Termination:** structured output returned, or timeout/budget hit.
- **Errors:** any failure → `None` (fail open). `relevant: true` with empty context is treated as
  `None`. Context is capped at `MAX_CONTEXT_CHARS`.
