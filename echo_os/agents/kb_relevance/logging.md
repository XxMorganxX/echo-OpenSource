# Logging

- The KB decision (`relevant`, `context`, `sources`, cost, latency, error) is stored inside each
  echo's line in `state/echoes.jsonl`.
- Process log: one line per run, including the reason when it failed open (timeout, auth, parse).
- The panel shows the KB status of the last run so an auth failure is visible.
