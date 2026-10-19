# echo-OS

**Version:** 0.1.0 | **Port:** 8431 (127.0.0.1 only) | **Stack:** Python 3.13, PyObjC (AppKit), macOS 14+

## What

Claude Code hooks post every session's events to a local daemon. When a long turn finishes, two
small headless `claude -p` agents write a headline (optionally using the user's knowledge base), and
the daemon speaks it, prefixed in code by the project folder and a per-project NATO call sign, and
shows it as a popup card. A menu bar app hosts the daemon, the panel and the popups.

## Quick start

```bash
./setup.sh              # venv, dependencies, tests (changes nothing outside this folder)
./echoctl install       # launchd agent + Claude Code hooks in ~/.claude/settings.json
./echoctl test          # run the tests
```

## Commands

```bash
./echoctl status | logs | restart | stop | start | uninstall
./echoctl show                      # toggle the panel (also: ./echoctl open, in a browser)
./echoctl say "text"                # queue speech through the running app
./echoctl headline <transcript>     # run both agents on a transcript, print the result
./echoctl kb <transcript>           # only the KB relevance agent
./scripts/check-publication.sh      # fail if anything private or secret is in git (runs on push)
```

## Architecture

```
hooks/echo-hook.sh      every hook event -> POST 127.0.0.1:8431, returns at once
echo_os/server/         HTTP API + the panel (static/)
echo_os/sessions.py     session registry: per-project call signs and card colors
echo_os/transcript.py   reads the finished turn out of the session's transcript
echo_os/echo/           pipeline (gate -> KB agent -> headline agent -> announce), worker, history
echo_os/agents/         headline and kb_relevance agents, each with its six component docs + config.py
echo_os/voice/          speech providers behind one interface (macOS say, OpenAI)
echo_os/menubar/        the AppKit app that embeds the daemon; popup cards and their placement
docs/spec.md            design decisions (D1...), the source of truth for behavior
```

A `Stop` event reaches the worker, which reads the turn and applies the length gate. If the turn
passes, the worker runs the agents through `agents/shared/headless_model.py` (a stripped-down
`claude -p`). It then queues the spoken line and the popup through `echo/announcer.py`, one at a time.

## Key files

```
echo_os/settings.py                   every tunable value; .env overrides the common ones
echo_os/app.py                        wiring: builds the pipeline, agents, monitor and server
echo_os/echo/pipeline.py              the echo flow, spoken-text template, KnowledgeLookup protocol
echo_os/agents/*/config.py            each agent's model, limits and prompt templates
echo_os/agents/headline/system_prompt.md   the headline prompt (the panel edits it in place)
echo_os/hook_install.py               adds/removes the hook entries in ~/.claude/settings.json
echoctl                               install/control script for the launchd agent
```

## Configuration

Everything is optional; see `.env.example`. The common ones:

| Variable | Default | What it does |
|----------|---------|--------------|
| `ECHO_OS_MIN_TURN_SECONDS` / `ECHO_OS_MIN_TOOL_CALLS` | 180 / 5 | which turns get an echo |
| `ECHO_OS_VOICE` | `macos-say` | or `openai` (needs `OPENAI_API_KEY`) |
| `ECHO_OS_KB_CONFIG` | `./kb.json` | knowledge-base connection (copy `kb.example.json`) |
| `ECHO_OS_CLAUDE_BINARY` | `claude` | full path if launchd can't find it |
| `ECHO_OS_PORT` | 8431 | reinstall after changing |

## Rules for this repo

- **It's public.** Never commit `kb.json`, `.env`, `state/` or `tasks/`; they hold private data and
  are gitignored. `scripts/check-publication.sh` must pass before any push. Install it as a pre-push
  hook once: `./scripts/check-publication.sh --install-hook`.
- Tests never call a model or speak. Write the test first for real logic; `./echoctl test` must pass.
- Behavior changes update `docs/spec.md` (and an agent's docs if it changes) in the same commit.
- Values and prompts live in `settings.py` or an agent's `config.py`, never inline.

See [CONTRIBUTING.md](CONTRIBUTING.md).
