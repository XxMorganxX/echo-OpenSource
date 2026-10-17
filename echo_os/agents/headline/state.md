# State

Per run, in memory only: the `TurnDigest`, the optional `KbContext`, the rendered user message and
the `ModelResult`. Nothing is shared between runs; each echo is an independent call.
