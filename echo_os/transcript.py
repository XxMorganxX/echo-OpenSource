"""Reads the turn that just finished out of a Claude Code transcript (JSONL).

A turn starts at the first human prompt after the previous turn's end marker. Claude Code writes
`system/turn_duration` after the Stop hook runs, so the current turn has no end marker yet: its
duration is measured from that first prompt to the moment the Stop hook fired.

A background command or agent that finishes while the session is idle starts a turn of its own with a
`<task-notification>` user entry (origin "task-notification"), not a human prompt. Such a turn has an
empty ask and lists the finished tasks in `background_tasks`; it is timed from the first notification.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

TURN_END_SUBTYPES = {"turn_duration", "stop_hook_summary"}
# Bookkeeping that Claude Code records as user entries but nobody typed as a request.
NON_PROMPT_PREFIXES = ("<local-command-stdout>", "<local-command-caveat>", "<local-command-stderr>")
TASK_NOTIFICATION_PREFIX = "<task-notification>"
# `Background command "Run the suite" completed (exit code 0)`, `Agent "Profile from docs" finished`.
TASK_SUMMARY_PATTERN = re.compile(r'^(?:Background command|Agent)\s+"(?P<label>.*)"\s+(?P<rest>.*)$', re.S)
NONZERO_EXIT_PATTERN = re.compile(r"\(exit code (?!0\))\d+\)")


@dataclass(frozen=True)
class BackgroundTask:
    label: str  # what the session named the command or agent
    status: str  # completed | failed | killed | stopped

    @property
    def ok(self) -> bool:
        return self.status == "completed"


@dataclass(frozen=True)
class TurnDigest:
    ask: str
    response: str
    tool_calls: int
    duration_seconds: float
    # Background tasks whose completion started this turn; the ask is empty then.
    background_tasks: tuple[BackgroundTask, ...] = ()


def parse_task_notification(text: str) -> BackgroundTask | None:
    """The finished task a `<task-notification>` block describes, or None for any other text."""
    if not text.lstrip().startswith(TASK_NOTIFICATION_PREFIX):
        return None
    status = _tag(text, "status") or "completed"
    summary = html.unescape(_tag(text, "summary") or "Background task")
    match = TASK_SUMMARY_PATTERN.match(summary)
    if status == "completed" and match and NONZERO_EXIT_PATTERN.search(match["rest"]):
        status = "failed"
    return BackgroundTask(label=(match["label"] if match else summary).strip(), status=status)


def is_long_horizon(digest: TurnDigest, *, min_seconds: float, min_tool_calls: int) -> bool:
    return digest.duration_seconds >= min_seconds and digest.tool_calls >= min_tool_calls


def read_last_turn(
    transcript_path: Path | str,
    *,
    ended_at: float,
    last_assistant_message: str | None = None,
) -> TurnDigest | None:
    """Digest of the final turn, or None when the transcript is missing or the turn was started by
    neither a human prompt nor a finished background task."""
    entries = _read_entries(Path(transcript_path))
    if entries is None:
        return None

    turn = _entries_of_last_turn(entries)
    prompts = [(entry, text) for entry in turn if (text := _human_prompt_text(entry)) is not None]
    notifications = [(entry, task) for entry in turn if (task := _task_notification(entry)) is not None]
    if not prompts:
        return _background_turn(turn, notifications, ended_at=ended_at,
                                last_assistant_message=last_assistant_message)

    started_at = _timestamp(prompts[0][0])
    # Messages typed while the turn was running arrive as queued_command attachments.
    start_index = turn.index(prompts[0][0])
    prompts += [(entry, text) for entry in turn[start_index:] if (text := _queued_prompt_text(entry)) is not None]
    prompts.sort(key=lambda pair: turn.index(pair[0]))
    main_line = [entry for entry in turn if not entry.get("isSidechain")]
    response = (last_assistant_message or "").strip() or _final_response(main_line)
    return TurnDigest(
        ask="\n\n".join(text for _, text in prompts),
        response=response,
        tool_calls=sum(len(_blocks(entry, "tool_use")) for entry in main_line if entry.get("type") == "assistant"),
        duration_seconds=max(0.0, ended_at - started_at) if started_at is not None else 0.0,
    )


def _background_turn(turn: list[dict], notifications: list, *, ended_at: float,
                     last_assistant_message: str | None) -> TurnDigest | None:
    if not notifications:
        return None
    started_at = _timestamp(notifications[0][0])
    main_line = [entry for entry in turn if not entry.get("isSidechain")]
    return TurnDigest(
        ask="",
        response=(last_assistant_message or "").strip() or _final_response(main_line),
        tool_calls=sum(len(_blocks(entry, "tool_use")) for entry in main_line if entry.get("type") == "assistant"),
        duration_seconds=max(0.0, ended_at - started_at) if started_at is not None else 0.0,
        background_tasks=tuple(task for _, task in notifications),
    )


def _read_entries(path: Path) -> list[dict] | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return None
    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def _entries_of_last_turn(entries: list[dict]) -> list[dict]:
    # The current turn's own end markers are usually written by the time we read (moments after the
    # Stop hook), so only markers before the turn's last message count as a previous turn's end.
    last_message = max(
        (i for i, entry in enumerate(entries) if entry.get("type") in ("user", "assistant")), default=-1
    )
    entries = entries[: last_message + 1]
    for index in range(len(entries) - 1, -1, -1):
        entry = entries[index]
        if entry.get("type") == "system" and entry.get("subtype") in TURN_END_SUBTYPES:
            return entries[index + 1 :]
    return entries


def _human_prompt_text(entry: dict) -> str | None:
    if entry.get("type") != "user" or entry.get("isSidechain") or entry.get("isMeta"):
        return None
    origin = entry.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return None  # a task notification or a message from another session, not something you typed
    return _user_text(entry)


def _task_notification(entry: dict) -> BackgroundTask | None:
    if entry.get("type") != "user" or entry.get("isSidechain") or entry.get("isMeta"):
        return None
    origin = entry.get("origin")
    if not isinstance(origin, dict) or origin.get("kind") != "task-notification":
        return None
    return parse_task_notification(_user_text(entry) or "")


def _user_text(entry: dict) -> str | None:
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        if any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content):
            return None
        text = "\n".join(block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text")
    else:
        return None
    text = text.strip()
    if not text or text.startswith(NON_PROMPT_PREFIXES):
        return None
    return text


def _queued_prompt_text(entry: dict) -> str | None:
    attachment = entry.get("attachment")
    if entry.get("type") != "attachment" or entry.get("isSidechain") or not isinstance(attachment, dict):
        return None
    if attachment.get("type") != "queued_command" or (attachment.get("origin") or {}).get("kind") != "human":
        return None
    text = str(attachment.get("prompt") or "").strip()
    return text or None


def _blocks(entry: dict, block_type: str) -> list[dict]:
    content = (entry.get("message") or {}).get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict) and block.get("type") == block_type]


def _final_response(main_line: list[dict]) -> str:
    """Assistant text written after the last tool call: the answer, not the progress narration."""
    texts: list[str] = []
    for entry in main_line:
        if entry.get("type") != "assistant":
            continue
        if _blocks(entry, "tool_use"):
            texts = []
            continue
        texts.extend(block.get("text", "").strip() for block in _blocks(entry, "text"))
    return "\n\n".join(text for text in texts if text)


def _tag(text: str, name: str) -> str | None:
    match = re.search(rf"<{name}>(.*?)</{name}>", text, re.S)
    return match.group(1).strip() if match else None


def _timestamp(entry: dict) -> float | None:
    raw = entry.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
