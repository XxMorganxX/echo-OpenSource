"""Echo log (JSONL). Feeds the panel and doubles as the agents' run log.

Echoes older than `max_age_seconds` are no longer listed or replayable, and are dropped from the
file on the next append. Records without a `created_at` are kept.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable


class EchoHistory:
    def __init__(self, path: Path, *, max_age_seconds: float | None = None, clock: Callable[[], float] = time.time):
        self._path = path
        self._max_age_seconds = max_age_seconds
        self._clock = clock
        self._lock = threading.Lock()

    def append(self, record: dict) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            lines = self._read_lines()
            kept = [line for line in lines if not self._is_expired(_parse(line))]
            if len(kept) < len(lines):
                tmp = self._path.with_suffix(".tmp")
                tmp.write_text("".join(line + "\n" for line in kept + [json.dumps(record)]), encoding="utf-8")
                tmp.replace(self._path)
                return
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")

    def recent(self, limit: int) -> list[dict]:
        return list(reversed(self._read()))[:limit]

    def get(self, echo_id: str) -> dict | None:
        return next((record for record in reversed(self._read()) if record.get("id") == echo_id), None)

    def _read(self) -> list[dict]:
        with self._lock:
            lines = self._read_lines()
        records = [_parse(line) for line in lines]
        return [record for record in records if record is not None and not self._is_expired(record)]

    def _read_lines(self) -> list[str]:
        try:
            return self._path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []

    def _is_expired(self, record: dict | None) -> bool:
        if record is None:
            return False  # unreadable lines are skipped on read, never silently rewritten away
        created_at = record.get("created_at")
        if self._max_age_seconds is None or not isinstance(created_at, (int, float)):
            return False
        return self._clock() - created_at > self._max_age_seconds


def _parse(line: str) -> dict | None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None
