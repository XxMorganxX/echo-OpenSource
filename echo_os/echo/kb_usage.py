"""How the knowledge base figured in one echo, for the popup's KB status.

Derived from the `kb` dict stored on each echo, so a live echo and its replay show the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KbUsage:
    state: str  # used | not-relevant | needs-auth | unavailable | off
    notes: int = 0  # number of KB notes behind the context, when used


def kb_usage_from_record(kb: dict | None) -> KbUsage:
    if kb is None:
        return KbUsage("off")
    if kb.get("relevant"):
        return KbUsage("used", notes=len(kb.get("sources") or []))
    error = kb.get("error")
    if not error:
        return KbUsage("not-relevant")
    # Older records have no server_status; their error text carries it ("notes-kb needs-auth").
    if kb.get("server_status") == "needs-auth" or "needs-auth" in str(error):
        return KbUsage("needs-auth")
    return KbUsage("unavailable")
