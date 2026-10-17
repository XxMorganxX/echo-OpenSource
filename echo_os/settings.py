"""Single source of truth for echo-OS paths, ports, thresholds and provider selection.

Agent-specific parameters and prompts live in each agent's own `config.py`
(`echo_os/agents/<agent>/config.py`). Loads the app's `.env` on import, so every entry point sees
the same environment without a shell wrapper.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

APP_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(APP_ROOT / ".env")

# -- Local filesystem ----------------------------------------------------------
STATE_ROOT = APP_ROOT / "state"
SESSIONS_PATH = STATE_ROOT / "sessions.json"
ECHOES_PATH = STATE_ROOT / "echoes.jsonl"
PREFERENCES_PATH = STATE_ROOT / "preferences.json"
# Headless model calls run here so no project's CLAUDE.md or .claude/ settings apply.
HEADLESS_WORKDIR = STATE_ROOT / "headless"
LOG_FILE = Path.home() / "Library" / "Logs" / "echo-os" / "echo.log"

# -- HTTP server (embedded in the menu bar app) --------------------------------
SERVER_HOST = "127.0.0.1"
SERVER_PORT = int(os.environ.get("ECHO_OS_PORT", "8431"))

# -- macOS integration ---------------------------------------------------------
LAUNCHD_LABEL = os.environ.get("ECHO_OS_LAUNCHD_LABEL", "local.echo-os")
MENUBAR_TOGGLE_NOTIFICATION = f"{LAUNCHD_LABEL}.toggle"
MENUBAR_SHOW_NOTIFICATION = f"{LAUNCHD_LABEL}.show"

# -- Claude Code -----------------------------------------------------------------
CLAUDE_BINARY = os.environ.get("ECHO_OS_CLAUDE_BINARY", "claude")
# Set on every headless call echo-OS makes; the hook script exits early when it sees it.
CHILD_ENV_FLAG = "ECHO_OS_CHILD"
# Hook events echo-OS registers for. Order matters only for readability in settings.json.
HOOK_EVENTS = ["SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"]
# Sessions from these entrypoints get call signs and echoes; everything else (sdk-cli = headless
# `claude -p`, including echo-OS's own calls) is ignored.
TRACKED_ENTRYPOINTS = {"cli", "claude-desktop"}

# -- Call signs ------------------------------------------------------------------
# NATO alphabet, spelled the way text-to-speech pronounces best ("Alpha", "Juliet").
CALL_SIGNS = [
    "Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel", "India", "Juliet",
    "Kilo", "Lima", "Mike", "November", "Oscar", "Papa", "Quebec", "Romeo", "Sierra", "Tango",
    "Uniform", "Victor", "Whiskey", "X-ray", "Yankee", "Zulu",
]
# A session with no hook event for this long and no live process is considered gone.
SESSION_IDLE_EXPIRY_SECONDS = 12 * 60 * 60
SESSION_SWEEP_INTERVAL_SECONDS = 60

# -- Long-horizon gate ------------------------------------------------------------
# A turn is echoed only when it ran at least this long AND made at least this many tool calls.
MIN_TURN_SECONDS = int(os.environ.get("ECHO_OS_MIN_TURN_SECONDS", "180"))
MIN_TOOL_CALLS = int(os.environ.get("ECHO_OS_MIN_TOOL_CALLS", "5"))
# The Stop hook can fire a moment before the transcript's last lines are flushed.
TRANSCRIPT_SETTLE_SECONDS = 1.5
# Jobs that waited longer than this in the queue are dropped rather than spoken late.
MAX_JOB_AGE_SECONDS = 10 * 60

# -- Pipeline ------------------------------------------------------------------------
KB_AGENT_ENABLED = os.environ.get("ECHO_OS_KB_AGENT", "true").lower() == "true"
# How often the panel's KB light re-checks notes-kb's login (`claude mcp get`, no model call).
KB_STATUS_CHECK_SECONDS = 5 * 60
# Spoken text = call sign + headline.
SPOKEN_TEMPLATE = "{call_sign}. {headline}"
RECENT_ECHOES_LIMIT = 30

# -- Popup (menu bar app only) ----------------------------------------------------------
# A small card in the top-right corner that shows each announcement while it is spoken.
POPUP_ENABLED = os.environ.get("ECHO_OS_POPUP", "true").lower() == "true"
POPUP_WIDTH = 340
POPUP_MARGIN = 12
POPUP_GAP = 8
# On screen for roughly reading time, clamped to these bounds.
POPUP_READING_WORDS_PER_SECOND = 2.5
POPUP_MIN_SECONDS = 6
POPUP_MAX_SECONDS = 20

# -- Voice -----------------------------------------------------------------------------
VOICE_PROVIDER = os.environ.get("ECHO_OS_VOICE", "macos-say")  # macos-say | openai
MACOS_SAY_VOICE = os.environ.get("ECHO_OS_SAY_VOICE", "")  # "" = system default voice
MACOS_SAY_RATE_WPM = int(os.environ.get("ECHO_OS_SAY_RATE", "190"))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_TTS_MODEL = os.environ.get("ECHO_OS_OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = os.environ.get("ECHO_OS_OPENAI_TTS_VOICE", "alloy")
OPENAI_TTS_INSTRUCTIONS = "Speak like a calm radio operator giving a brief status update."
VOICE_TIMEOUT_SECONDS = 60
