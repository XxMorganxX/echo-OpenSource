"""Brings the terminal tab running a Claude Code session to the front (clicking its popup does this).

The hook reports each session's Claude process id. Walking up the process tree from it gives the
session's tty, which names its tab, and the outermost `.app` ancestor, which is the terminal app.
Terminal and iTerm2 select the exact tab by tty over AppleScript. Any other app (VS Code, Ghostty,
Warp, ...) is only brought to the front: none has a scriptable way to pick a tab. Sessions inside
tmux or screen have no app ancestor, so there is nothing to focus and the caller falls back.

The first AppleScript use triggers macOS's Automation prompt ("Echo wants to control Terminal").
If it is denied, or the tab is gone, the app is still brought forward.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5  # the first run waits on the Automation prompt only until this

# Each script gets the tty ("/dev/ttys013") as its argument and returns "found" or "missing".
TERMINAL_SCRIPT = """on run argv
    set target to item 1 of argv
    tell application id "com.apple.Terminal"
        repeat with w in windows
            repeat with t in tabs of w
                if tty of t is target then
                    if miniaturized of w then set miniaturized of w to false
                    set selected of t to true
                    set index of w to 1
                    activate
                    return "found"
                end if
            end repeat
        end repeat
    end tell
    return "missing"
end run"""

ITERM_SCRIPT = """on run argv
    set target to item 1 of argv
    tell application id "com.googlecode.iterm2"
        repeat with w in windows
            repeat with t in tabs of w
                repeat with s in sessions of t
                    if tty of s is target then
                        select w
                        select t
                        select s
                        activate
                        return "found"
                    end if
                end repeat
            end repeat
        end repeat
    end tell
    return "missing"
end run"""

# By app bundle name. Apps not listed are only brought to the front.
TAB_SCRIPTS = {"Terminal.app": TERMINAL_SCRIPT, "iTerm.app": ITERM_SCRIPT}


@dataclass(frozen=True)
class Process:
    ppid: int
    tty: str  # "ttys013"; "??" when it has none
    command: str


@dataclass(frozen=True)
class TerminalTarget:
    app_path: str  # "/System/Applications/Utilities/Terminal.app"
    tty: str  # "/dev/ttys013"


def parse_process_table(text: str) -> dict[int, Process]:
    """Parses `ps -axo pid=,ppid=,tty=,comm=`. Commands keep their spaces."""
    table = {}
    for line in text.splitlines():
        fields = line.split(maxsplit=3)
        if len(fields) == 4 and fields[0].isdigit() and fields[1].isdigit():
            table[int(fields[0])] = Process(ppid=int(fields[1]), tty=fields[2], command=fields[3])
    return table


def process_table() -> dict[int, Process]:
    result = subprocess.run(["ps", "-axo", "pid=,ppid=,tty=,comm="], capture_output=True, text=True,
                            timeout=TIMEOUT_SECONDS, check=False)
    return parse_process_table(result.stdout)


def find_terminal(pid: int, processes: dict[int, Process]) -> TerminalTarget | None:
    """The app and tty a session runs in, or None when it has no tty or no app above it."""
    process = processes.get(pid)
    if process is None or not process.tty.startswith("tty"):
        return None
    app_path = None
    current, seen = process.ppid, set()
    while current > 1 and current not in seen:
        seen.add(current)
        parent = processes.get(current)
        if parent is None:
            break
        if ".app/" in parent.command:
            # The first ".app" in the path is the outer bundle, so helpers resolve to their app.
            app_path = parent.command[:parent.command.index(".app/") + len(".app")]
        current = parent.ppid
    return TerminalTarget(app_path=app_path, tty=f"/dev/{process.tty}") if app_path else None


def focus_session(pid: int | None, *, processes: dict[int, Process] | None = None,
                  run: Callable = subprocess.run) -> bool:
    """Brings the session's terminal to the front, on its own tab where the app allows.
    Returns False when there is nothing to focus. Blocks on `osascript`; call it off the main thread."""
    if pid is None:
        return False
    try:
        target = find_terminal(pid, process_table() if processes is None else processes)
        if target is None:
            logger.info("No terminal app found for pid %s", pid)
            return False
        script = TAB_SCRIPTS.get(Path(target.app_path).name)
        if script is not None:
            result = run(["osascript", "-e", script, target.tty], capture_output=True, text=True,
                         timeout=TIMEOUT_SECONDS, check=False)
            if result.stdout.strip() == "found":
                return True
            logger.warning("Tab %s not selected in %s: %s", target.tty, target.app_path,
                           (result.stderr or result.stdout).strip() or "not found")
        return run(["open", "-a", target.app_path], capture_output=True, text=True,
                   timeout=TIMEOUT_SECONDS, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Focusing the terminal for pid %s failed: %s", pid, exc)
        return False
