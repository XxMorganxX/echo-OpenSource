"""Tracks every interactive Claude Code session on the machine and gives each a call sign.

A call sign is held from a session's first hook event until it ends (SessionEnd, its process
dies, or it goes quiet past the expiry). The lowest free sign is handed out first; a resumed
session gets its previous sign back when that sign is free. State is persisted so names survive a
daemon restart.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

# Ended sessions are kept only so a resumed session can reclaim its old call sign.
MAX_ENDED_SESSIONS_KEPT = 200


@dataclass
class Session:
    session_id: str
    call_sign: str
    project: str
    cwd: str
    pid: int | None
    status: str  # working | idle | ended
    started_at: float
    last_event_at: float
    last_headline: str = ""


def process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class SessionRegistry:
    def __init__(self, path: Path, *, call_signs: list[str], idle_expiry_seconds: float = 12 * 3600):
        self._path = path
        self._call_signs = call_signs
        self._idle_expiry_seconds = idle_expiry_seconds
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = self._load()

    # -- Queries ---------------------------------------------------------------------------
    def get(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)

    def active(self) -> list[Session]:
        with self._lock:
            sessions = [s for s in self._sessions.values() if s.status != "ended"]
        return sorted(sessions, key=lambda s: self._sign_order(s.call_sign))

    # -- Events ----------------------------------------------------------------------------
    def touch(self, session_id: str, *, cwd: str, now: float, pid: int | None = None) -> Session:
        """Registers a session (or revives an ended one) and returns it with its call sign."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.status == "ended":
                previous_sign = session.call_sign if session else None
                session = Session(
                    session_id=session_id,
                    call_sign=self._free_sign(preferred=previous_sign),
                    project=Path(cwd).name or cwd,
                    cwd=cwd,
                    pid=pid,
                    status="idle",
                    started_at=now,
                    last_event_at=now,
                    last_headline=session.last_headline if session else "",
                )
                self._sessions[session_id] = session
            session.last_event_at = now
            if cwd:
                session.cwd, session.project = cwd, Path(cwd).name or cwd
            if pid:
                session.pid = pid
            self._save()
            return session

    def mark_working(self, session_id: str, *, now: float) -> None:
        self._set_status(session_id, "working", now)

    def mark_idle(self, session_id: str, *, now: float) -> None:
        self._set_status(session_id, "idle", now)

    def end(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.status = "ended"
                self._save()

    def set_last_headline(self, session_id: str, headline: str, *, now: float) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.last_headline = headline
                self._save()

    def sweep(self, *, now: float, is_alive: Callable[[int], bool] = process_is_alive) -> list[Session]:
        """Ends sessions whose process is gone, or that have no pid and have been quiet too long."""
        ended = []
        with self._lock:
            for session in self._sessions.values():
                if session.status == "ended":
                    continue
                dead = session.pid is not None and not is_alive(session.pid)
                expired = session.pid is None and now - session.last_event_at > self._idle_expiry_seconds
                if dead or expired:
                    session.status = "ended"
                    ended.append(session)
            if ended:
                self._save()
        return ended

    # -- Internals -------------------------------------------------------------------------
    def _set_status(self, session_id: str, status: str, now: float) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None and session.status != "ended":
                session.status = status
                session.last_event_at = now
                self._save()

    def _free_sign(self, *, preferred: str | None) -> str:
        taken = {s.call_sign for s in self._sessions.values() if s.status != "ended"}
        if preferred and preferred not in taken:
            return preferred
        round_number = 1
        while True:
            for sign in self._call_signs:
                candidate = sign if round_number == 1 else f"{sign} {round_number}"
                if candidate not in taken:
                    return candidate
            round_number += 1

    def _sign_order(self, call_sign: str) -> tuple[int, int]:
        base, _, suffix = call_sign.partition(" ")
        index = self._call_signs.index(base) if base in self._call_signs else len(self._call_signs)
        return (int(suffix) if suffix.isdigit() else 1, index)

    def _load(self) -> dict[str, Session]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return {item["session_id"]: Session(**item) for item in raw}
        except (FileNotFoundError, json.JSONDecodeError, TypeError, KeyError):
            return {}

    def _save(self) -> None:
        live = [s for s in self._sessions.values() if s.status != "ended"]
        ended = sorted((s for s in self._sessions.values() if s.status == "ended"), key=lambda s: s.last_event_at)
        kept = live + ended[-MAX_ENDED_SESSIONS_KEPT:]
        self._sessions = {s.session_id: s for s in kept}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(s) for s in kept], indent=2), encoding="utf-8")
        tmp.replace(self._path)
