# echo-OS

Hear when a long Claude Code task finishes. When any Claude Code session on your Mac ends a long
turn, echo-OS writes a one- or two-line headline with a small fast model and reads it aloud,
prefixed by the project folder and the session's call sign:

> *"billing svc, Alpha. The billing refactor is done and all 42 tests pass."*

- **One watcher for the whole machine.** Every interactive session gets a NATO call sign (Alpha,
  Bravo, Charlie…) for as long as it runs, counted per project folder: two projects can each have
  an Alpha, and a second session in the same folder is its Bravo. The project and call sign are
  added by code, never by the model.
- **Long turns only.** By default, at least 3 minutes and 5 tool calls.
- **Bring your own knowledge base.** A separate agent decides whether your knowledge base has
  something worth adding, and fetches it. Any MCP server works; see
  [Connect your own knowledge base](#connect-your-own-knowledge-base).
- **Editable system prompt.** Change how headlines are written from the panel. Edits apply to the
  next echo.
- **A popup you can read.** Each echo also appears as a small card in the top-right corner while it
  is spoken (and still appears when speech is muted). Each project folder has its own card color.
  The card shows a live waveform while it's spoken, how long the turn took, how many tools it used
  and when it finished, and how the KB figured in. Drag a card to move the stack anywhere; new cards
  appear there from then on (drag it back to the top-right corner to reset).
- **Questions and suggestions on screen.** When the agent asks you something or suggests next steps,
  the voice says so ("…two questions for you on screen") and the card lists them as bullets. Those
  cards stay up until you close them, reply to that session, or it ends.
- **One speech queue.** Echoes, replays and anything sent to `POST /api/speak` play one at a time,
  so voices never overlap. Other tools can speak through that endpoint.
- **A tiny menu bar app** that shows live sessions and recent echoes, with mute, replay, and a KB
  light that shows whether your knowledge base is reachable (click it to re-check).

Design and decisions: [docs/spec.md](docs/spec.md). Agents:
[headline](echo_os/agents/headline/README.md), [KB relevance](echo_os/agents/kb_relevance/README.md).

## Requirements

- macOS 14 or later.
- Python 3.13. With Homebrew: `brew install python@3.13`.
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI (`claude`), logged in: run
  `claude` once and sign in. echo-OS makes its model calls through it, on your plan.
- Optional: an MCP server for your knowledge base.
- Optional: `OPENAI_API_KEY` for the OpenAI voice (the default is macOS `say`, no setup).

## Setup

```bash
git clone https://github.com/XxMorganxX/echo-OpenSource.git echo-os
cd echo-os
./setup.sh            # checks prerequisites, creates ./venv, installs, runs the tests
./echoctl install     # start the menu bar app at login + add the Claude Code hooks
```

`setup.sh` changes nothing outside this folder; `install` is the step that touches your Mac
(below). To do setup by hand instead: `python3.13 -m venv venv` then
`./venv/bin/pip install -r requirements.txt -e .`. The virtualenv must be `./venv`: `echoctl` and
the background agent run from it. `install` records this folder's path, so if you move the folder,
run `./echoctl install` again.

### Check it works

1. **Echo** appears in the menu bar, and `./echoctl status` prints `running` and a health line.
2. `./echoctl say "Voice check."` speaks and shows a card in the top-right corner.
3. The model calls work through your Claude login:
   `./echoctl headline "$(ls -t ~/.claude/projects/*/*.jsonl | head -1)"` prints a headline for your
   most recent session (it isn't spoken).
4. Open a **new** Claude Code session; sessions that were already running don't load the new hooks.
   Echoes come only after long turns (3 minutes and 5 tool calls). To see one now, put
   `ECHO_OS_MIN_TURN_SECONDS=0` and `ECHO_OS_MIN_TOOL_CALLS=0` in `.env`, run `./echoctl restart`, and
   give Claude any small task. Remove both lines afterwards.

`install` does the following:

1. Renders `launchd/echo-os.plist.template` into `~/Library/LaunchAgents/` and starts it (menu bar
   app + daemon, at login, restarts on crash).
2. Adds hook entries for `SessionStart`, `UserPromptSubmit`, `Stop` and `SessionEnd` to
   `~/.claude/settings.json`, keeping every other hook. The first install saves a backup next to it
   (`settings.json.echo-os.bak`).
3. Only if `~/.config/background-systems/registry/` exists: writes two Daemon Deck registry
   manifests describing the agent and its hooks. Otherwise this step is skipped.

`./echoctl uninstall` reverses all of it.

## Use

```bash
./echoctl show       # toggle the panel (or click "Echo" in the menu bar)
./echoctl open       # the same panel in a browser
./echoctl status | logs | restart | stop
./echoctl headline <transcript.jsonl>   # run both agents on a transcript, print the result
./echoctl kb <transcript.jsonl>         # just the KB relevance agent
```

Session transcripts live in `~/.claude/projects/<project>/<session-id>.jsonl`.

## Connect your own knowledge base

The KB relevance agent is a headless Claude Code call that may use one MCP server and only the
tools you list. The connection is a local file, `kb.json`, which git ignores, so your server and
how you search it stay private.

1. Copy the template: `cp kb.example.json kb.json`.
2. Point `mcp_server` at your server. It takes the same shape as a Claude Code MCP config:
   - remote: `{"type": "http", "url": "https://…/mcp"}` (or `"type": "sse"`)
   - local: `{"command": "…", "args": ["…"], "env": {…}}` (stdio)
3. List the read-only tools the agent may call in `tools`, by their names on that server (not the
   `mcp__…` form).
4. Describe what the KB holds in `about` (one sentence; it tells the agent when a lookup is worth
   it). Put anything specific to your tools in `instructions`, for example how to read a match score.
5. If the server needs a login, register it in Claude Code under the same name as `server_name`
   and log in once: `claude mcp add --transport http <server_name> <url>`, then `/mcp` →
   `<server_name>` → Authenticate in Claude Code.
6. Try it: `./echoctl kb <transcript.jsonl>`. Then `./echoctl restart`.

No `kb.json` (or `ECHO_OS_KB_AGENT=false`) keeps the KB agent off; echoes work the same without it.
`ECHO_OS_KB_CONFIG` points at a `kb.json` somewhere else.

**Not using MCP?** Implement `KnowledgeLookup` (one method, `lookup(digest, project) → KbLookup`, in
[`echo_os/echo/pipeline.py`](echo_os/echo/pipeline.py)) for your notes folder, database or API, and
pass it as `kb_agent` in [`echo_os/app.py`](echo_os/app.py). Fail open: return
`KbLookup(None, error=…)` rather than raising, so a KB outage never costs an echo.

## Configuration

Thresholds, ports, call signs, colors and voice live in [`echo_os/settings.py`](echo_os/settings.py);
the common ones can be set in `.env` (see [`.env.example`](.env.example)). Each agent's model, limits
and message templates are in its own `config.py`. The headline system prompt is
[`echo_os/agents/headline/system_prompt.md`](echo_os/agents/headline/system_prompt.md), which the
panel edits in place.

## How it works

Each hook runs [`hooks/echo-hook.sh`](hooks/echo-hook.sh), which POSTs the event to
`127.0.0.1:8431` in the background and returns at once. On `Stop` the daemon reads the turn out of
the session transcript and checks the length gate. Then one worker runs the KB relevance agent and
the headline agent: each is a stripped-down `claude -p` call on Haiku. Last, it queues the speech.
Headless sessions, including echo-OS's own calls, are ignored.

Anything else that wants to talk can join the queue:

```bash
curl -X POST localhost:8431/api/speak -H 'Content-Type: application/json' \
  -d '{"text": "Deploy finished.", "title": "CI"}'
```

## Troubleshooting

`./echoctl logs` shows what the agent is doing; most problems name themselves there.

- **No echo after a long task.** Was the session started after `install`? Running sessions don't pick
  up new hooks. Check that `./echoctl status` says `running`.
- **Echoes fail with `could not start claude`.** The agent doesn't use your shell's PATH, only the
  one in its plist (`~/.local/bin`, `/opt/homebrew/bin`, `/usr/local/bin` and the system folders).
  `install` warns about this. Put the full path in `.env`, e.g.
  `ECHO_OS_CLAUDE_BINARY=/path/to/claude` (find it with `whence -p claude` in zsh), then
  `./echoctl restart`.
- **Headline calls fail with a login error.** Run `claude` in a terminal and sign in again.
- **Nothing is spoken.** Check that `say hello` works in a terminal, the volume, and that the menu
  bar app isn't muted.
- **Port 8431 is taken.** Set `ECHO_OS_PORT` in `.env` and run `./echoctl install` again.
- **KB light is red or yellow.** Hover over it to see why; click it to re-check. Most often the server needs a login: `/mcp` in
  Claude Code → your server → Authenticate.

## Cost and privacy

- **Cost.** Each echo is one short Haiku call for the headline, plus one for the KB agent when a KB
  is connected. At API prices that's well under a cent per echo; on a Claude subscription it counts
  toward your plan's usage. Short turns cost nothing: they're skipped before any model call.
- **What leaves your Mac.** An excerpt of the finished turn (your request and the agent's final
  reply) goes to the model through your own Claude Code login. With a KB connected, the agent's
  search queries go to your KB server. With the OpenAI voice selected, the headline text goes to
  OpenAI to be spoken. Nothing goes anywhere else.
- **What stays local.** `state/` (gitignored) holds call-sign assignments, the echo history
  (`echoes.jsonl`, which includes transcript excerpts) and preferences. `kb.json` and `.env` are
  gitignored too.
- The HTTP server listens on `127.0.0.1` only and rejects requests whose `Host` isn't local.

## Development

```bash
./echoctl test                      # or: ./venv/bin/python -m pytest -q
```

The tests need macOS (the popup tests build real AppKit views) but never call a model or speak.
Before pushing, `./scripts/check-publication.sh` checks that no secret or private file is in git;
`--install-hook` makes git run it on every push. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Using with Claude Code

This repo has a [`CLAUDE.md`](CLAUDE.md) with its commands, architecture and rules. Run `claude` in
the repo and it's read automatically.

## Contributing

Issues and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
