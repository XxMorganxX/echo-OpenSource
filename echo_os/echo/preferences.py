"""User settings that change at runtime, persisted across restarts: the mute toggle (set from the
panel) and where you dragged the popups to (None = the default top-right corner)."""

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
        if not isinstance(data, dict):
            data = {}
        self.muted = bool(data.get("muted", False))
        anchor = data.get("popup_anchor")
        self.popup_anchor: dict | None = anchor if isinstance(anchor, dict) else None

    def set_muted(self, muted: bool) -> None:
        with self._lock:
            self.muted = muted
            self._save()

    def set_popup_anchor(self, anchor: dict | None) -> None:
        with self._lock:
            self.popup_anchor = anchor
            self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"muted": self.muted, "popup_anchor": self.popup_anchor}), encoding="utf-8")
        tmp.replace(self._path)
