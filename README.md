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
- **A popup you can read.** Each echo also appears as a small card in the top-right corner while it
  is spoken (and still appears when speech is muted). Each working directory has its own card color,
  so you can tell projects apart at a glance. The card shows a live waveform while it's spoken, how
  long the turn took, how many tools it used and when it finished, and how the KB figured in: used
  (with the number of notes), nothing relevant, needs login, unavailable, or off. Drag a card to move
  the stack anywhere; new cards appear there from then on (drag it back to the top-right corner to
  reset).
- **Questions and suggestions on screen.** When the agent asks you something or suggests next steps,
  the voice says so ("…two questions for you on screen") and the card lists them as bullets. Those
  cards stay up until you close them, reply to that session, or it ends.
- **One speech queue.** Echoes, replays and anything sent to `POST /api/speak` play one at a time,
  so voices never overlap. Other tools should speak through that endpoint.
- **A tiny menu bar app** (same framework as the to-do app) that shows live sessions and recent
  echoes, with mute, replay, and a KB light that shows whether notes-kb is logged in (click it to
  re-check).

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
./echoctl install     # launchd agent + Claude Code hooks + Daemon Deck manifests
./echoctl say "Alpha. Voice check."   # queued through the running app
```

`install` does three things:

1. Renders `launchd/echo-os.plist.template` into `~/Library/LaunchAgents/` and starts it (menu bar
   app + daemon, at login, restarts on crash).
2. Adds hook entries for `SessionStart`, `UserPromptSubmit`, `Stop` and `SessionEnd` to
   `~/.claude/settings.json`, keeping every other hook. The first install saves a backup next to it
   (`settings.json.echo-os.bak`).
3. Writes two Daemon Deck registry manifests: the app (`echo-os`) and its hooks (`echo-os-hooks`).

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
the headline agent (each is a stripped-down `claude -p` call on Haiku that counts toward your Claude plan's usage,
not API billing). Last, it queues the speech. Headless sessions, including echo-OS's own calls, are
ignored.

Anything else that wants to talk can join the queue:

```bash
curl -X POST localhost:8431/api/speak -H 'Content-Type: application/json' \
  -d '{"text": "Deploy finished.", "title": "CI"}'
```

`state/` (gitignored) holds call-sign assignments, the echo history (`echoes.jsonl`, which includes
transcript excerpts) and preferences.
