"""Top-right popup cards that show each announcement while it is spoken.

The announcer calls `show`/`resolve` from other threads; everything AppKit happens on the main
thread via `AppHelper.callAfter`. Cards stack downward.

Two kinds of card:
- Plain: fades after reading time; clicking it dismisses it and opens the panel.
- Sticky (has questions or suggestions): stays until you close it with its ✕, reply to that Claude
  session, or the session ends. Clicking it opens the panel and leaves it up.

Dragging any card moves the whole stack; where you drop it is saved in preferences and used for
every card after (see popup_position.py). Dropping it back near the top-right corner restores the default.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

from AppKit import (
    NSAnimationContext,
    NSEvent,
    NSBackingStoreBuffered,
    NSGraphicsContext,
    NSSymbolVariableColorEffect,
    NSButton,
    NSLineBreakByTruncatingTail,
    NSImage,
    NSImageView,
    NSBezierPath,
    NSColor,
    NSFont,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSStatusWindowLevel,
    NSTextField,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
import objc
from PyObjCTools import AppHelper

from echo_os import settings
from echo_os.echo.kb_usage import KbUsage
from echo_os.menubar.popup_position import Anchor, anchor_from_drop, stack_origins

logger = logging.getLogger(__name__)

PADDING_X = 14
PADDING_Y = 11
LINE_GAP = 6
KB_ICON_SIZE = 12
SECTION_GAP = 10
ITEM_GAP = 3
FOOTER_GAP = 10
CLOSE_SIZE = 16
CLOSE_GAP = 6
VOICE_ICON_SIZE = 14
SECTION_ICON_SIZE = 11
BULLET = "•"
BULLET_INDENT = 14
PILL_PADDING_X = 7
PILL_GAP = 7
STRIPE_WIDTH = 3
COUNTDOWN_HEIGHT = 2
COUNTDOWN_INSET_Y = 4
QUESTIONS_HEADING = "Questions for you"
SUGGESTIONS_HEADING = "Suggestions"
CORNER_RADIUS = 12
FADE_SECONDS = 0.25
SLIDE_DISTANCE = 24
SLIDE_SECONDS = 0.22
DRAG_THRESHOLD = 3  # points the mouse must move before a press becomes a drag instead of a click
SNAP_DISTANCE = 24  # dropping within this of the default corner restores the default position

# Same tokens as the panel's styles.css.
BACKGROUND = NSColor.colorWithSRGBRed_green_blue_alpha_(22 / 255, 27 / 255, 34 / 255, 0.97)
BORDER = NSColor.colorWithWhite_alpha_(1.0, 0.26)
HAIRLINE = NSColor.colorWithWhite_alpha_(1.0, 0.08)
TEXT = NSColor.colorWithSRGBRed_green_blue_alpha_(240 / 255, 246 / 255, 252 / 255, 1.0)
MUTED = NSColor.colorWithSRGBRed_green_blue_alpha_(139 / 255, 148 / 255, 158 / 255, 1.0)
ACCENT = NSColor.colorWithSRGBRed_green_blue_alpha_(88 / 255, 166 / 255, 255 / 255, 1.0)

WARNING = NSColor.colorWithSRGBRed_green_blue_alpha_(210 / 255, 153 / 255, 34 / 255, 1.0)


def _srgb(hex_color: str):
    red, green, blue = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return NSColor.colorWithSRGBRed_green_blue_alpha_(red, green, blue, 1.0)


# Each working directory's color (slots assigned in sessions.py), so stacked cards from different
# projects are told apart at a glance. Messages that aren't from a session (/api/speak) are neutral.
DIRECTORY_COLORS = tuple(_srgb(hex_color) for hex_color in settings.DIRECTORY_COLORS)
NEUTRAL = MUTED
# How strongly the directory color tints the card's fill and border. The neutral card keeps the panel's colors.
CARD_TINT = 0.12
BORDER_TINT_ALPHA = 0.5

# KB status in the card's footer: (SF Symbol, color, label, tooltip) per KbUsage state.
KB_STATUS = {
    "used": ("book.fill", ACCENT, "KB · {notes}", "Informed by your knowledge base ({notes})"),
    "not-relevant": ("book", MUTED, "KB · nothing relevant", "Knowledge base searched; nothing relevant"),
    "needs-auth": ("lock.fill", WARNING, "KB · needs login",
                   "notes-kb needs login: in Claude Code run /mcp, pick notes-kb, Authenticate"),
    "unavailable": ("exclamationmark.triangle.fill", WARNING, "KB · unavailable",
                    "Knowledge base lookup failed (see echo-OS log)"),
    "off": ("book", MUTED.colorWithAlphaComponent_(0.6), "KB off", "Knowledge base agent is turned off"),
}

# Header indicator for the voice: (SF Symbol, tooltip) per state. "speaking" animates until speech ends.
VOICE_INDICATOR = {
    "speaking": ("waveform", "Speaking"),
    "muted": ("speaker.slash.fill", "Muted"),
}

# Section heading icon and bullet color: (heading, SF Symbol, icon color, bullet color).
SECTIONS = (
    (QUESTIONS_HEADING, "questionmark.bubble.fill", WARNING, WARNING),
    (SUGGESTIONS_HEADING, "lightbulb.fill", ACCENT, MUTED),
)


def is_sticky(announcement) -> bool:
    return bool(announcement.questions or announcement.suggestions)


def display_seconds(body: str) -> float:
    """How long a plain (non-sticky) card stays up: roughly reading time, clamped."""
    reading = len(body.split()) / settings.POPUP_READING_WORDS_PER_SECOND
    return min(settings.POPUP_MAX_SECONDS, max(settings.POPUP_MIN_SECONDS, reading + 2))


def card_color(color: int | None):
    """The working directory's color for a palette slot; None (not from a session) is neutral."""
    return NEUTRAL if color is None else DIRECTORY_COLORS[color % len(DIRECTORY_COLORS)]


def meta_text(*, duration_seconds: float | None, tool_calls: int | None, finished_at: float | None) -> str:
    """Footer details for an echo: "12 min · 34 tools · 2:41 PM". Missing parts are left out."""
    parts = []
    if duration_seconds is not None:
        seconds = round(duration_seconds)
        if seconds >= 3600:
            parts.append(f"{seconds // 3600} h {round(seconds % 3600 / 60)} min")
        elif seconds >= 60:
            parts.append(f"{round(seconds / 60)} min")
        else:
            parts.append(f"{seconds} s")
    if tool_calls is not None:
        parts.append(f"{tool_calls} tool" + ("" if tool_calls == 1 else "s"))
    if finished_at is not None:
        parts.append(time.strftime("%-I:%M %p", time.localtime(finished_at)))
    return " · ".join(parts)


def _symbol(name: str, description: str):
    return NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, description)


class CloseButton(NSButton):
    """Borderless ✕ that calls a Python function; it is its own target so nothing else must stay alive."""

    def initWithFrame_onClose_(self, frame, on_close):  # noqa: N802
        self = self.initWithFrame_(frame)
        if self is None:
            return None
        self.on_close = on_close
        self.setBordered_(False)
        self.setImage_(_symbol("xmark", "Dismiss"))
        self.setContentTintColor_(MUTED)
        self.setToolTip_("Dismiss")
        self.setTarget_(self)
        self.setAction_("fire:")
        return self

    def acceptsFirstMouse_(self, event):  # noqa: N802
        return True

    def fire_(self, sender):  # noqa: N802
        self.on_close()


class CardView(NSView):
    """Rounded dark card tinted with its working directory's color, with that color down its left edge, drawn in drawRect_ (no layers,
    so it can also be rendered to an image)."""

    def initWithFrame_onClick_color_(self, frame, on_click, color):  # noqa: N802
        self = self.initWithFrame_(frame)
        if self is None:
            return None
        self.on_click = on_click
        self.color = color
        self.voice_indicator = None
        self.on_drag = None  # (dx, dy) while dragging; set by the presenter
        self.on_drop = None
        self._press = self._last = None
        self._dragging = False
        return self

    def isOpaque(self):  # noqa: N802
        return False

    def acceptsFirstMouse_(self, event):  # noqa: N802
        return True

    def drawRect_(self, rect):  # noqa: N802
        bounds = self.bounds()
        inset = NSMakeRect(0.5, 0.5, bounds.size.width - 1, bounds.size.height - 1)
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(inset, CORNER_RADIUS, CORNER_RADIUS)
        tinted = self.color is not NEUTRAL
        (BACKGROUND.blendedColorWithFraction_ofColor_(CARD_TINT, self.color) if tinted else BACKGROUND).setFill()
        path.fill()
        NSGraphicsContext.saveGraphicsState()
        path.addClip()
        self.color.setFill()
        NSBezierPath.fillRect_(NSMakeRect(0, 0, STRIPE_WIDTH, bounds.size.height))
        NSGraphicsContext.restoreGraphicsState()
        (self.color.colorWithAlphaComponent_(BORDER_TINT_ALPHA) if tinted else BORDER).setStroke()
        path.setLineWidth_(1.0)
        path.stroke()

    # A press that moves less than DRAG_THRESHOLD is a click (handled on release); more is a drag.
    # Global mouse coordinates, because the window itself moves under the mouse during the drag.
    def mouseDown_(self, event):  # noqa: N802
        self._press = self._last = NSEvent.mouseLocation()
        self._dragging = False

    def mouseDragged_(self, event):  # noqa: N802
        if self._press is None:
            return
        point = NSEvent.mouseLocation()
        if not self._dragging and max(abs(point.x - self._press.x), abs(point.y - self._press.y)) < DRAG_THRESHOLD:
            return
        self._dragging = True
        if self.on_drag is not None:
            self.on_drag(point.x - self._last.x, point.y - self._last.y)
        self._last = point

    def mouseUp_(self, event):  # noqa: N802
        if self._press is None:
            return
        dragged, self._press, self._dragging = self._dragging, None, False
        callback = self.on_drop if dragged else self.on_click
        if callback is not None:
            callback()


class FilledView(NSView):
    """A rounded rectangle of one color: the call-sign pill, the footer hairline, the countdown bar."""

    def initWithFrame_color_radius_(self, frame, color, radius):  # noqa: N802
        self = self.initWithFrame_(frame)
        if self is None:
            return None
        self.color, self.radius = color, radius
        return self

    def isOpaque(self):  # noqa: N802
        return False

    def drawRect_(self, rect):  # noqa: N802
        self.color.setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(self.bounds(), self.radius, self.radius).fill()


def _label(text: str, font, color, width: float):
    field = NSTextField.wrappingLabelWithString_(text)
    field.setFont_(font)
    field.setTextColor_(color)
    field.setPreferredMaxLayoutWidth_(width)
    field.setSelectable_(False)
    # Measure at the exact drawing width: fittingSize can come up a line short when a wrap lands on a hyphen.
    height = field.cell().cellSizeForBounds_(NSMakeRect(0, 0, width, 10_000)).height
    field.setFrameSize_((width, height))
    return field


def _one_line(text: str, font, color, max_width: float | None = None):
    """A single-line label, truncated with an ellipsis when wider than max_width."""
    field = NSTextField.labelWithString_(text)
    field.setFont_(font)
    field.setTextColor_(color)
    field.setLineBreakMode_(NSLineBreakByTruncatingTail)
    field.sizeToFit()
    if max_width is not None and field.frame().size.width > max_width:
        field.setFrameSize_((max(0, max_width), field.frame().size.height))
    return field


def _icon(symbol: str, tooltip: str, color, size: float):
    view = NSImageView.alloc().initWithFrame_(NSMakeRect(0, 0, size, size))
    view.setImage_(_symbol(symbol, tooltip))
    view.setContentTintColor_(color)
    view.setToolTip_(tooltip)
    return view


def _pill(text: str, color):
    """The call sign on a tinted capsule in its session color."""
    label = _one_line(text, NSFont.systemFontOfSize_weight_(11.5, 0.4), color)
    size = label.frame().size
    pill = FilledView.alloc().initWithFrame_color_radius_(
        NSMakeRect(0, 0, size.width + 2 * PILL_PADDING_X, size.height + 2), color.colorWithAlphaComponent_(0.16),
        (size.height + 2) / 2)
    label.setFrameOrigin_((PILL_PADDING_X, 1))
    pill.addSubview_(label)
    return pill


def _kb_status_views(usage: KbUsage) -> tuple:
    symbol, color, label_template, tooltip_template = KB_STATUS.get(usage.state, KB_STATUS["unavailable"])
    notes = f"{usage.notes} note" + ("" if usage.notes == 1 else "s")
    label_text, tooltip = label_template.format(notes=notes), tooltip_template.format(notes=notes)
    icon = _icon(symbol, tooltip, color, KB_ICON_SIZE)
    label = _one_line(label_text, NSFont.systemFontOfSize_weight_(10.5, 0.3), color)
    label.setToolTip_(tooltip)
    return icon, label


def _item_sections(questions: tuple[str, ...], suggestions: tuple[str, ...], width: float) -> list:
    """Rows for the bulleted sections, top to bottom: an icon + small heading, then one row per item."""
    views = []
    for (heading, symbol, icon_color, bullet_color), items in zip(SECTIONS, (questions, suggestions)):
        if not items:
            continue
        views.append(("heading", _section_heading(heading, symbol, icon_color, width)))
        for item in items:
            views.append(("item", _bullet_row(item, bullet_color, width)))
    return views


def _section_heading(text: str, symbol: str, color, width: float):
    label = _one_line(text, NSFont.systemFontOfSize_weight_(10.5, 0.4), MUTED, width - BULLET_INDENT)
    height = label.frame().size.height
    row = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    icon = _icon(symbol, text, color, SECTION_ICON_SIZE)
    icon.setFrameOrigin_((0, round((height - SECTION_ICON_SIZE) / 2)))
    label.setFrameOrigin_((BULLET_INDENT, 0))
    row.addSubview_(icon)
    row.addSubview_(label)
    return row


def _bullet_row(item: str, bullet_color, width: float):
    """A bullet in its own column so wrapped lines hang under the text, not under the bullet."""
    font = NSFont.systemFontOfSize_(12.5)
    text = _label(item, font, TEXT, width - BULLET_INDENT)
    bullet = NSTextField.labelWithString_(BULLET)
    bullet.setFont_(font)
    bullet.setTextColor_(bullet_color)
    bullet.sizeToFit()
    row = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, text.frame().size.height))
    text.setFrameOrigin_((BULLET_INDENT, 0))
    bullet.setFrameOrigin_((2, text.frame().size.height - bullet.frame().size.height))
    row.addSubview_(bullet)
    row.addSubview_(text)
    return row


def _place_right(view, right: float, middle: float) -> float:
    """Puts `view` with its right edge at `right`, centered on `middle`; returns its left edge."""
    size = view.frame().size
    view.setFrameOrigin_((right - size.width, round(middle - size.height / 2)))
    return right - size.width


def build_card(*, title: str, subtitle: str, body: str, on_click: Callable | None, kb_usage: KbUsage | None = None,
               questions: tuple[str, ...] = (), suggestions: tuple[str, ...] = (), on_close: Callable | None = None,
               meta: str = "", voice_state: str | None = None, color: int | None = None):
    """The card view, sized to its text. Separate from the window so it can be rendered offscreen.

    `color` is the working directory's palette slot. Top to bottom: header (call-sign pill, project, voice indicator, ✕ when `on_close` is given),
    headline, question/suggestion sections, footer (`meta` details, KB status).
    """
    width = settings.POPUP_WIDTH
    text_width = width - 2 * PADDING_X
    color = card_color(color)

    # Header: right side first, so the project label gets whatever width is left.
    header_right = []
    if on_close is not None:
        header_right.append(CloseButton.alloc().initWithFrame_onClose_(NSMakeRect(0, 0, CLOSE_SIZE, CLOSE_SIZE), on_close))
    voice_indicator = None
    if voice_state in VOICE_INDICATOR:
        symbol, tooltip = VOICE_INDICATOR[voice_state]
        voice_indicator = _icon(symbol, tooltip, color if voice_state == "speaking" else MUTED, VOICE_ICON_SIZE)
        header_right.append(voice_indicator)
    right_width = sum(view.frame().size.width for view in header_right) + CLOSE_GAP * len(header_right)
    pill = _pill(title, color)
    project = _one_line(subtitle, NSFont.systemFontOfSize_(12), MUTED,
                        text_width - pill.frame().size.width - PILL_GAP - right_width)
    header_height = max(pill.frame().size.height, project.frame().size.height)

    body_label = _label(body, NSFont.systemFontOfSize_(13), TEXT, text_width)
    sections = _item_sections(questions, suggestions, text_width)

    status = _kb_status_views(kb_usage) if kb_usage is not None else None
    status_width = (KB_ICON_SIZE + 3 + status[1].frame().size.width) if status else 0
    meta_label = (_one_line(meta, NSFont.systemFontOfSize_(10.5), MUTED,
                            text_width - (status_width + CLOSE_GAP if status else 0)) if meta else None)
    footer_height = max([view.frame().size.height for view in ((meta_label,) if meta_label else ()) +
                         ((status[1],) if status else ())] or [0])

    # Stack top to bottom. AppKit's y grows upward, so lay out from the top edge down.
    rows = [body_label] + [view for _, view in sections]
    gaps = [LINE_GAP] + [SECTION_GAP if kind == "heading" else ITEM_GAP for kind, _ in sections]
    height = (PADDING_Y * 2 + header_height + sum(view.frame().size.height for view in rows) + sum(gaps)
              + (FOOTER_GAP + footer_height if footer_height else 0))
    card = CardView.alloc().initWithFrame_onClick_color_(NSMakeRect(0, 0, width, height), on_click, color)
    card.voice_indicator = voice_indicator

    top = height - PADDING_Y
    header_middle = top - header_height / 2
    pill.setFrameOrigin_((PADDING_X, round(header_middle - pill.frame().size.height / 2)))
    project.setFrameOrigin_((PADDING_X + pill.frame().size.width + PILL_GAP,
                             round(header_middle - project.frame().size.height / 2)))
    card.addSubview_(pill)
    card.addSubview_(project)
    right = width - PADDING_X
    for view in header_right:  # ✕ outermost, then the voice indicator
        right = _place_right(view, right + (3 if isinstance(view, CloseButton) else 0), header_middle) - CLOSE_GAP
        card.addSubview_(view)

    y = top - header_height
    for view, gap in zip(rows, gaps):
        y -= gap + view.frame().size.height
        view.setFrameOrigin_((PADDING_X, y))
        card.addSubview_(view)

    if footer_height:
        footer_middle = PADDING_Y + footer_height / 2
        hairline = FilledView.alloc().initWithFrame_color_radius_(
            NSMakeRect(PADDING_X, PADDING_Y + footer_height + FOOTER_GAP / 2, text_width, 1), HAIRLINE, 0)
        card.addSubview_(hairline)
        if meta_label is not None:
            meta_label.setFrameOrigin_((PADDING_X, round(footer_middle - meta_label.frame().size.height / 2)))
            card.addSubview_(meta_label)
        if status is not None:
            icon, label = status
            left = _place_right(label, width - PADDING_X, footer_middle)
            _place_right(icon, left - 3, footer_middle)
            card.addSubview_(icon)
            card.addSubview_(label)
    return card


def start_speaking_animation(indicator) -> None:
    indicator.addSymbolEffect_(NSSymbolVariableColorEffect.effect().effectWithIterative())


def add_countdown(card, seconds: float) -> None:
    """A thin bar along the bottom of a plain card that drains until it fades; sticky cards have none."""
    frame = NSMakeRect(PADDING_X, COUNTDOWN_INSET_Y, settings.POPUP_WIDTH - 2 * PADDING_X, COUNTDOWN_HEIGHT)
    bar = FilledView.alloc().initWithFrame_color_radius_(frame, card.color.colorWithAlphaComponent_(0.55),
                                                         COUNTDOWN_HEIGHT / 2)
    card.addSubview_(bar)

    def drain(context):
        context.setDuration_(seconds)
        # QuartzCore is loaded by AppKit; looking the class up avoids a pyobjc-framework-Quartz dependency.
        context.setTimingFunction_(objc.lookUpClass("CAMediaTimingFunction").functionWithName_("linear"))
        bar.animator().setFrameSize_((0, COUNTDOWN_HEIGHT))

    NSAnimationContext.runAnimationGroup_completionHandler_(drain, None)


class PopupPresenter:
    """Implements the announcer's Popup contract with stacked top-right cards."""

    def __init__(self, *, on_click: Callable[[], None] | None = None, preferences=None):
        """`preferences` (echo_os.echo.preferences.Preferences) keeps the dragged-to position; without
        it the stack always sits in the default corner and drags last until the cards close."""
        self._on_click = on_click
        self._preferences = preferences
        self._cards: list[_Card] = []  # oldest first: nearest the anchor
        self._dragging = False
        self._unsaved_anchor: Anchor | None = None  # used only without preferences

    def show(self, announcement, *, speaking: bool) -> None:
        AppHelper.callAfter(self._show_on_main, announcement, speaking)

    def finished_speaking(self, announcement) -> None:
        AppHelper.callAfter(self._finished_speaking_on_main, announcement)

    def resolve(self, session_id: str) -> None:
        AppHelper.callAfter(self._resolve_on_main, session_id)

    def _show_on_main(self, announcement, speaking: bool) -> None:
        sticky = is_sticky(announcement)
        logger.info("Popup show: %s%s (%d on screen)", announcement.title, " [sticky]" if sticky else "", len(self._cards))
        holder: dict = {}

        def clicked():
            if not sticky:
                self._dismiss(holder.get("window"))
            if self._on_click is not None:
                self._on_click()

        card = build_card(
            title=announcement.title, subtitle=announcement.subtitle, body=announcement.body, on_click=clicked,
            kb_usage=announcement.kb_usage, questions=announcement.questions, suggestions=announcement.suggestions,
            on_close=(lambda: self._dismiss(holder.get("window"))) if sticky else None,
            meta=meta_text(duration_seconds=announcement.duration_seconds, tool_calls=announcement.tool_calls,
                           finished_at=announcement.finished_at),
            voice_state="speaking" if speaking else "muted", color=announcement.color,
        )
        window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            card.frame(), NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel, NSBackingStoreBuffered, False
        )
        holder["window"] = window
        card.on_drag = self._drag_by
        card.on_drop = self._drop
        window.setReleasedWhenClosed_(False)
        window.setLevel_(NSStatusWindowLevel)
        window.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary)
        window.setOpaque_(False)
        window.setBackgroundColor_(NSColor.clearColor())
        window.setHasShadow_(True)
        window.setHidesOnDeactivate_(False)
        window.setContentView_(card)
        window.setAlphaValue_(0.0)

        self._cards.append(_Card(window, announcement, sticky, card.voice_indicator))
        self._layout(entering=window)
        window.orderFrontRegardless()
        if speaking:
            start_speaking_animation(card.voice_indicator)
        if not sticky:
            seconds = display_seconds(announcement.body)
            add_countdown(card, seconds)
            AppHelper.callLater(seconds, self._dismiss, window)

    def _finished_speaking_on_main(self, announcement) -> None:
        for card in self._cards:
            if card.announcement is announcement and card.voice_indicator is not None:
                card.voice_indicator.removeAllSymbolEffects()
                card.voice_indicator.animator().setAlphaValue_(0.0)

    def _resolve_on_main(self, session_id: str) -> None:
        if not session_id:
            return
        for card in list(self._cards):
            if card.sticky and card.announcement.session_id == session_id:
                logger.info("Popup resolved: session %s answered or ended", session_id[:8])
                self._dismiss(card.window)

    def _dismiss(self, window) -> None:
        entry = next((card for card in self._cards if card.window is window), None)
        if entry is None:
            return
        self._cards.remove(entry)
        logger.info("Popup dismiss (%d left)", len(self._cards))
        window.animator().setAlphaValue_(0.0)
        AppHelper.callLater(FADE_SECONDS, window.orderOut_, None)
        self._layout()

    def _drag_by(self, dx: float, dy: float) -> None:
        """The whole stack follows the mouse, unanimated."""
        self._dragging = True
        for card in self._cards:
            origin = card.window.frame().origin
            card.window.setFrameOrigin_((origin.x + dx, origin.y + dy))

    def _drop(self) -> None:
        self._dragging = False
        if not self._cards:
            return
        frames = [card.window.frame() for card in self._cards]
        anchor = anchor_from_drop(
            left=frames[0].origin.x, top=max(f.origin.y + f.size.height for f in frames),
            bottom=min(f.origin.y for f in frames), screens=_visible_frames(), default_screen=_default_screen(),
            width=settings.POPUP_WIDTH, margin=settings.POPUP_MARGIN, snap_distance=SNAP_DISTANCE)
        logger.info("Popups moved to %s", anchor or "the default corner")
        if self._preferences is not None:
            self._preferences.set_popup_anchor(anchor.to_dict() if anchor else None)
        else:
            self._unsaved_anchor = anchor
        self._layout()

    def _anchor(self) -> Anchor | None:
        if self._preferences is not None:
            return Anchor.from_dict(self._preferences.popup_anchor)
        return self._unsaved_anchor

    def _layout(self, entering=None) -> None:
        """Stacks the cards from the anchor (see popup_position.py). The entering card slides in
        sideways from the nearer screen edge; the others glide to their new places."""
        if self._dragging:  # the drop lays everything out
            return
        default = _default_screen()
        origins = stack_origins(self._anchor(), [card.window.frame().size.height for card in self._cards],
                                screens=_visible_frames(), default_screen=default, width=settings.POPUP_WIDTH,
                                margin=settings.POPUP_MARGIN, gap=settings.POPUP_GAP)

        def animate(context):
            context.setDuration_(SLIDE_SECONDS)
            for card, (x, y) in zip(self._cards, origins):
                size = card.window.frame().size
                # NSWindow's animator animates frame changes, not setFrameOrigin_.
                card.window.animator().setFrame_display_(NSMakeRect(x, y, size.width, size.height), True)
                if card.window is entering:
                    card.window.animator().setAlphaValue_(1.0)

        for card, (x, y) in zip(self._cards, origins):
            if card.window is entering:
                from_right = x + settings.POPUP_WIDTH / 2 >= default[0] + default[2] / 2
                card.window.setFrameOrigin_((x + (SLIDE_DISTANCE if from_right else -SLIDE_DISTANCE), y))
        NSAnimationContext.runAnimationGroup_completionHandler_(animate, None)


def _rect(frame) -> tuple[float, float, float, float]:
    return (frame.origin.x, frame.origin.y, frame.size.width, frame.size.height)


def _visible_frames() -> list:
    return [_rect(screen.visibleFrame()) for screen in NSScreen.screens()]


def _default_screen() -> tuple[float, float, float, float]:
    screen = NSScreen.mainScreen() or NSScreen.screens()[0]
    return _rect(screen.visibleFrame())


@dataclass
class _Card:
    """One card on screen."""

    window: object
    announcement: object
    sticky: bool
    voice_indicator: object
