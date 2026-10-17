# Logging

- Every echo is one JSON line in `state/echoes.jsonl`: call sign, session, project, the digest fields,
  KB decision, headline, model cost, latency, and error if any.
- Process log `~/Library/Logs/echo-os/echo.log`: one line per model call (agent, duration, cost) and
  every error.
- To debug a bad headline: find its line in `echoes.jsonl`, re-run `./echo headline <transcript>`
  against the same transcript, and edit the system prompt.
