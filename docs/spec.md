# echo-OS — spec

**Status:** v1, 2026-10-16. Working log: [tasks/build-echo-os.md](../tasks/build-echo-os.md).

## What it is

When a Claude Code session on this Mac finishes a **long** turn, echo-OS reads the turn, writes a
one- to two-line headline with a small fast model, and speaks it aloud, prefixed by the session's
phonetic call sign: *"Charlie. Billing refactor is done and all 42 tests pass."*

One background process watches every Claude Code session on the machine. A tiny menu bar app shows
the sessions, the recent echoes, and lets you edit the headline system prompt and mute speech.

## Architecture

```
Claude Code session (any)                     echo-OS daemon (one launchd agent)
  hooks: SessionStart ─┐                     ┌─ HTTP server 127.0.0.1:8431
         UserPromptSubmit                    │    /api/hook  ← hook events
         Stop          ├─ hooks/echo-hook.sh ─┤    /api/*     ← menu bar panel / browser
         SessionEnd   ─┘   (curl, ≤1 s, never blocks)
                                             ├─ SessionRegistry   call signs, status, liveness
                                             ├─ EchoWorker (one queue, one job at a time)
                                             │    transcript → TurnDigest → long-horizon gate
                                             │    → KB relevance agent (notes-kb, optional)
                                             │    → headline agent → history
                                             ├─ Announcer (one queue: popup + speech, one at a time)
                                             └─ menu bar status item + WKWebView panel + popups
```

Same framework as the to-do app (`an existing menu bar app`): Python 3.13, PyObjC menu bar app with a
borderless floating `WKWebView` panel, the panel's HTML/JS served by an embedded stdlib
`ThreadingHTTPServer` that also exposes a JSON API, one per-user launchd agent, a bash control script,
and a Daemon Deck registry manifest.

### "One background session"

Interpreted as one monitoring process for the whole machine (not one per Claude session). Each
headline is a short-lived headless `claude -p` call made by that process, serialized through a single
queue. A persistent stream-json Claude session was rejected: its context grows with every echo,
summaries could bleed between sessions, and it needs reset logic, all to save ~1 s of CLI startup.

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | Hooks forward raw JSON to the daemon over HTTP with `curl -m 1`; failures are swallowed. | A hook must never slow or break a user's session. If the daemon is down, echoes are simply missed. |
| D2 | Long-horizon gate: turn wall-clock ≥ `MIN_TURN_SECONDS` (180) **and** tool calls ≥ `MIN_TOOL_CALLS` (5). | Duration is what "I walked away" means; the tool floor screens out long thinking-only answers. Both in `settings.py`. |
| D3 | Turn boundaries come from the transcript: the turn starts at the first human prompt after the previous `turn_duration`/`stop_hook_summary` record. Markers after the turn's last message are ignored, and messages typed mid-turn (`queued_command` attachments) join the ask. | Survives daemon restarts. Claude Code writes the current turn's own markers moments after the Stop hook, so they are usually present by the time the transcript is read and must not be taken as a turn boundary. |
| D4 | Headless calls run `claude -p` with `--system-prompt`, `--tools ""`, `--strict-mcp-config`, `disableAllHooks`, `--no-session-persistence`, and `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`. | Measured: the default context is 163k tokens ($0.16/call); stripped it is ~640 tokens ($0.001, ~3 s). Disabling hooks stops recursion and stops the user's own Stop hooks (notification sound) firing for background calls. |
| D5 | Call signs: NATO alphabet (Alpha, Bravo, Charlie…), lowest free name; freed when the session ends or its `CLAUDE_PID` dies; a resumed session gets its old name back if free. Overflow → "Alpha 2". | Short, unambiguous when spoken. List lives in `settings.py`. "Alpha"/"Juliet" spellings because TTS reads them better than "Alfa"/"Juliett". |
| D6 | Only interactive sessions are tracked: `CLAUDE_CODE_ENTRYPOINT` (passed by the hook) in `cli`/`claude-desktop`. `sdk-cli` (headless `claude -p`, including echo-OS's own) is ignored. | Automation runs would otherwise claim call signs and chatter. |
| D7 | The headline system prompt is a Markdown file, `echo_os/agents/headline/system_prompt.md`, re-read on every echo. The panel edits it in place. | Editable without restart, and git-tracked so prompt edits are versioned. |
| D8 | The KB relevance agent is a separate headless call with only `search_memories` and `find_entity` from notes-kb, structured JSON output, a budget cap, and a timeout. It fails open: any error → no KB context. | Keeps the headline path alive when notes-kb is down or unauthenticated. The agent decides relevance itself and is told to skip tools for generic turns. |
| D9 | Voice behind a `VoiceOutput` contract. Default `macos-say` (no setup); `openai` (gpt-4o-mini-tts → `afplay`) when selected and `OPENAI_API_KEY` is set. | TTS is the most likely provider to change. `say` works on day one. |
| D10 | Model behind a `HeadlessModel` contract; v1 implementation is Claude Code headless with `claude-haiku-5-5`. | The user asked for a background Claude Code session; the contract leaves room for a direct API call later. |
| D12 | Every voice message goes through one `Announcer` queue in the app: echoes, replays, `POST /api/speak` and `./echoctl say`. Mute is checked at play time. | Nothing ever talks over anything else, and other bots can join the same queue instead of calling a voice directly. |
| D13 | Each announcement shows a top-right popup card (native `NSPanel`, panel colors) at the moment its speech starts; cards stack, stay up for reading time (6–20 s) and open the panel on click. Popups still show when muted. The top-right corner shows KB usage for that echo: "KB · N notes" (used), "nothing relevant", "needs login", "unavailable" or "KB off", each with its own icon and color; `/api/speak` messages have none. | Lets you read what was said; muting turns echoes into read-only. A native window avoids Notification Center grouping and Focus modes. |
| D14 | The panel header has a KB light (green connected, amber needs login, red unreachable, gray unknown/off). Sources: `claude mcp get notes-kb` at startup, every 5 min and on click (no model call, ~3 s), plus the server status every KB lookup reports. | An expired notes-kb login otherwise shows up only as quietly worse headlines. Lookups catch it the moment an echo hits it; the timer catches it between echoes. |
| D15 | The headline agent returns structured output: `headline` (spoken) plus `questions` and `suggestions` (shown as bullets on the popup and panel, never spoken). The headline answers a direct question first ("Yes, …") and points to the screen when there are items ("…two questions for you on screen"). Items come only from the agent's final response. | You hear the gist and read the details; questions don't get lost in speech. |
| D16 | Cards with questions or suggestions are sticky: no timer; they close on their ✕, when you send that session your next prompt (`UserPromptSubmit`), or when it ends (`SessionEnd`). Clicking a sticky card opens the panel and leaves it up. Plain cards still fade. | A question should stay in view until you've dealt with it; replying to the session is the natural "answered" signal. |
| D11 | History is an append-only JSONL (`state/echoes.jsonl`) holding every echo with its inputs, KB decision, cost and latency. Skipped turns are logged, not stored. | Doubles as the agents' logging layer and the panel's feed. |

## Hook contract

`hooks/echo-hook.sh` is registered in `~/.claude/settings.json` for `SessionStart`,
`UserPromptSubmit`, `Stop` and `SessionEnd`. It exits immediately when `ECHO_OS_CHILD` is set, and
otherwise POSTs stdin to `/api/hook?entrypoint=$CLAUDE_CODE_ENTRYPOINT&pid=$CLAUDE_PID`. The payload
fields used: `hook_event_name`, `session_id`, `transcript_path`, `cwd`, `source` (SessionStart),
`reason` (SessionEnd), `last_assistant_message` (Stop, when present).

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness |
| POST | `/api/hook` | hook ingress |
| GET | `/api/state` | sessions, recent echoes, mute flag, KB status, thresholds |
| GET/PUT | `/api/prompt` | read / replace the headline system prompt |
| POST | `/api/mute` | `{"muted": bool}` |
| POST | `/api/kb/check` | re-check notes-kb's login now; returns the light's state |
| POST | `/api/speak` | `{"text": str, "title"?: str}`: queue a voice message (202) |
| POST | `/api/echoes/<id>/replay` | speak an echo again |

## Agents

Two target agents, each documented by the six-component spec in its own directory:

- [`echo_os/agents/headline/`](../echo_os/agents/headline/README.md) — writes the spoken headline.
- [`echo_os/agents/kb_relevance/`](../echo_os/agents/kb_relevance/README.md) — decides whether the KB
  has context worth adding, and fetches it.

Shared model plumbing lives in `echo_os/agents/shared/`.

## Out of scope (v1)

- Echoing subagent completions (`SubagentStop`) or headless sessions.
- Remote machines; everything is localhost.
- Interrupting speech when you return to the terminal.
- A fallback to grepping the local vault when notes-kb is unavailable.
