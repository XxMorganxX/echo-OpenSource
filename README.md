# echo-OS

Hear when a long Claude Code task finishes. When any Claude Code session on this Mac ends a long
turn, echo-OS writes a one- or two-line headline with a small fast model and reads it aloud, prefixed
by the session's call sign:

> *"Charlie. The billing refactor is done and all 42 tests pass."*

- **One watcher for the whole machine.** Every interactive session gets a NATO call sign (Alpha,
  Bravo, Charlie…) for as long as it runs.
- **Long turns only.** By default, at least 3 minutes and 5 tool calls.
- **Optional KB context.** A separate agent decides whether your knowledge base (notes-kb) has
  something worth adding, and fetches it.
- **Editable system prompt.** Change how headlines are written from the panel. Edits apply to the
  next echo.
- **A tiny menu bar app** (same framework as the to-do app) that shows live sessions and recent
  echoes, with mute and replay.

Design and decisions: [docs/spec.md](docs/spec.md). Agents:
[headline](echo_os/agents/headline/README.md), [KB relevance](echo_os/agents/kb_relevance/README.md).

## Requirements

- macOS, Python 3.13
- Claude Code CLI (`claude`) logged in. Headless calls use your plan, not an API key.
- Optional: notes-kb authenticated in Claude Code (`/mcp` → notes-kb → Authenticate).
- Optional: `OPENAI_API_KEY` for the OpenAI voice.

## Setup

```bash
python3.13 -m venv venv
./venv/bin/pip install -r requirements.txt -e .
./echoctl test        # run the test suite
./echoctl say "Alpha. Voice check."
./echoctl install     # launchd agent + Claude Code hooks + Daemon Deck manifest
```

`install` does three things:

1. Renders `launchd/echo-os.plist.template` into `~/Library/LaunchAgents/` and starts it (menu bar
   app + daemon, at login, restarts on crash).
2. Adds hook entries for `SessionStart`, `UserPromptSubmit`, `Stop` and `SessionEnd` to
   `~/.claude/settings.json`, keeping every other hook. The first install saves a backup next to it
   (`settings.json.echo-os.bak`).
3. Writes the Daemon Deck registry manifest.

`./echoctl uninstall` reverses all three.

## Use

```bash
./echoctl show       # toggle the panel (or click "Echo" in the menu bar)
./echoctl open       # the same panel in a browser
./echoctl status | logs | restart | stop
./echoctl headline <transcript.jsonl>   # run both agents on a transcript, print the result
./echoctl kb <transcript.jsonl>         # just the KB relevance agent
```

## Configuration

Thresholds, ports, call signs and voice live in [`echo_os/settings.py`](echo_os/settings.py); the
common ones can be set in `.env` (see [`.env.example`](.env.example)). Each agent's model, limits and
message templates are in its own `config.py`. The headline system prompt is
[`echo_os/agents/headline/system_prompt.md`](echo_os/agents/headline/system_prompt.md), which the
panel edits in place.

## How it works

Each hook runs [`hooks/echo-hook.sh`](hooks/echo-hook.sh), which POSTs the event to
`127.0.0.1:8431` in the background and returns at once. On `Stop` the daemon reads the turn out of
the session transcript and checks the length gate. Then one worker runs the KB relevance agent and
the headline agent (each is a stripped-down `claude -p` call on Haiku, about 3 seconds and a fraction
of a cent). Last, it queues the speech. Headless sessions, including echo-OS's own calls, are
ignored.

`state/` (gitignored) holds call-sign assignments, the echo history (`echoes.jsonl`, which includes
transcript excerpts) and preferences.
