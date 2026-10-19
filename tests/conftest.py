"""Shared builders for fake Claude Code transcripts."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

T0 = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)


def at(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def human(text, seconds, **extra):
    return {"type": "user", "isSidechain": False, "timestamp": at(seconds),
            "message": {"role": "user", "content": text}, "entrypoint": "cli", **extra}


def assistant_text(text, seconds, sidechain=False):
    return {"type": "assistant", "isSidechain": sidechain, "timestamp": at(seconds),
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def tool_use(name, seconds, sidechain=False):
    return {"type": "assistant", "isSidechain": sidechain, "timestamp": at(seconds),
            "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": name, "input": {}}]}}


def tool_result(seconds):
    return {"type": "user", "isSidechain": False, "timestamp": at(seconds),
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}}


def turn_end(seconds):
    return {"type": "system", "subtype": "turn_duration", "durationMs": 1000, "timestamp": at(seconds)}


@pytest.fixture
def write_transcript(tmp_path: Path):
    def _write(entries, name="session.jsonl") -> Path:
        path = tmp_path / name
        with path.open("w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write((entry if isinstance(entry, str) else json.dumps(entry)) + "\n")
        return path
    return _write


def task_notification(summary, seconds, status="completed"):
    """The user entry Claude Code writes when a background command or agent finishes."""
    content = (f"<task-notification>\n<task-id>b1</task-id>\n<tool-use-id>toolu_1</tool-use-id>\n"
               f"<output-file>/tmp/b1.output</output-file>\n<status>{status}</status>\n"
               f"<summary>{summary}</summary>\n</task-notification>")
    return human(content, seconds, origin={"kind": "task-notification"})
