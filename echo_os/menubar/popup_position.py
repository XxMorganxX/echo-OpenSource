"""Where the popup stack sits, and where a drag leaves it. Pure geometry, no AppKit.

Coordinates are AppKit's global screen space: origin bottom-left, y grows upward. Screens are their
visible frames (menu bar and Dock excluded) as (x, y, width, height).

The stack hangs from an anchor. With no anchor it hangs from the top-right corner of the default
screen. A drop in a screen's upper half grows the stack downward from its top edge; a drop in the
lower half grows it upward from its bottom edge, so a stack parked near the Dock doesn't run off
the screen. The oldest card is always nearest the anchor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

Rect = tuple[float, float, float, float]


@dataclass(frozen=True)
class Anchor:
    x: float  # left edge of the stack
    edge: float  # the stack's top edge when it grows down, its bottom edge when it grows up
    grows: str  # "down" | "up"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data) -> "Anchor | None":
        """None for anything that isn't a valid saved anchor."""
        if not isinstance(data, dict) or data.get("grows") not in ("down", "up"):
            return None
        try:
            return cls(x=float(data["x"]), edge=float(data["edge"]), grows=data["grows"])
        except (KeyError, TypeError, ValueError):
            return None


def stack_origins(anchor: Anchor | None, heights: list[float], *, screens: list[Rect], default_screen: Rect,
                  width: float, margin: float, gap: float) -> list[tuple[float, float]]:
    """Window origins for cards of these heights, oldest first. An anchor that's on no current
    screen (a monitor was unplugged, the resolution changed) falls back to the default corner."""
    screen = _containing(screens, anchor.x + width / 2, anchor.edge) if anchor else None
    if anchor is None or screen is None:
        screen = default_screen
        anchor = Anchor(x=screen[0] + screen[2] - width - margin, edge=screen[1] + screen[3] - margin, grows="down")
    left, bottom, right, top = screen[0], screen[1], screen[0] + screen[2], screen[1] + screen[3]
    x = min(max(anchor.x, left), right - width)
    first = heights[0] if heights else 0
    origins = []
    if anchor.grows == "down":
        edge = min(max(anchor.edge, bottom + first), top)
        for height in heights:
            origins.append((x, edge - height))
            edge -= height + gap
    else:
        edge = max(min(anchor.edge, top - first), bottom)
        for height in heights:
            origins.append((x, edge))
            edge += height + gap
    return origins


def anchor_from_drop(*, left: float, top: float, bottom: float, screens: list[Rect], default_screen: Rect,
                     width: float, margin: float, snap_distance: float) -> Anchor | None:
    """The anchor a dragged stack leaves behind, given its bounding box when dropped. Clamped onto
    the screen it was dropped on; None (back to the default corner) when dropped near that corner."""
    center_x, center_y = left + width / 2, (top + bottom) / 2
    screen = _containing(screens, center_x, center_y) or _nearest(screens, center_x, center_y) or default_screen
    screen_left, screen_bottom = screen[0], screen[1]
    screen_right, screen_top = screen[0] + screen[2], screen[1] + screen[3]
    x = min(max(left, screen_left), screen_right - width)
    corner_x, corner_top = screen_right - width - margin, screen_top - margin
    if abs(x - corner_x) <= snap_distance and abs(min(top, screen_top) - corner_top) <= snap_distance:
        return None
    if center_y >= screen_bottom + screen[3] / 2:
        return Anchor(x=x, edge=min(top, screen_top), grows="down")
    return Anchor(x=x, edge=max(bottom, screen_bottom), grows="up")


def _containing(screens: list[Rect], x: float, y: float) -> Rect | None:
    return next((s for s in screens if s[0] <= x <= s[0] + s[2] and s[1] <= y <= s[1] + s[3]), None)


def _nearest(screens: list[Rect], x: float, y: float) -> Rect | None:
    def distance(s: Rect) -> float:
        dx = max(s[0] - x, 0, x - (s[0] + s[2]))
        dy = max(s[1] - y, 0, y - (s[1] + s[3]))
        return dx * dx + dy * dy

    return min(screens, key=distance, default=None)
