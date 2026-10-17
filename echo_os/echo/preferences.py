"""User toggles that change at runtime (set from the panel), persisted across restarts."""

from __future__ import annotations

import json
import threading
from pathlib import Path


class Preferences:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        self.muted = bool(data.get("muted", False)) if isinstance(data, dict) else False

    def set_muted(self, muted: bool) -> None:
        with self._lock:
            self.muted = muted
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps({"muted": muted}), encoding="utf-8")
