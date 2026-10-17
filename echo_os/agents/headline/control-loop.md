# Control loop

Single pass, owned by Claude Code headless: one user message in, one text result out.

- **Termination:** the model's end of turn. With no tools there is exactly one model call.
- **Budget:** `--max-budget-usd` caps spend; the subprocess timeout caps latency.
- **Errors:** timeout, non-zero exit or an empty result raise `HeadlessModelError`. The pipeline
  catches it, logs it, and records the echo as failed. It does not retry: a late headline is worth
  less than none.
- **Post-processing:** strip markdown, collapse whitespace, cap at `MAX_HEADLINE_CHARS`.
