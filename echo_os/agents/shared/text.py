"""Small text helpers shared by the agents."""

from __future__ import annotations

import re


def truncate(text: str, limit: int) -> str:
    """Cuts at a word boundary at or under `limit` characters, marking the cut with an ellipsis."""
    if len(text) <= limit:
        return text
    cut = text[: max(0, limit - 1)]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip() + "…"


def to_speech(text: str) -> str:
    """Plain, single-line text from model output that may contain markdown."""
    lines = [re.sub(r"^\s*(?:[-*+]\s+|#+\s*|>\s*|\d+[.)]\s+)", "", line) for line in text.splitlines()]
    text = " ".join(lines)
    text = re.sub(r"\*\*|__|`", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip().strip('"').strip()
