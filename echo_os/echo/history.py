"""Append-only echo log (JSONL). Feeds the panel and doubles as the agents' run log."""

from __future__ import annotations

import json
import threading
from pathlib import Path


class EchoHistory:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()

    def append(self, record: dict) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")

    def recent(self, limit: int) -> list[dict]:
        return list(reversed(self._read()))[:limit]

    def get(self, echo_id: str) -> dict | None:
        return next((record for record in reversed(self._read()) if record.get("id") == echo_id), None)

    def _read(self) -> list[dict]:
        with self._lock:
            try:
                lines = self._path.read_text(encoding="utf-8").splitlines()
            except FileNotFoundError:
                return []
        records = []
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records
