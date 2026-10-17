"""Top-right popup cards that show each announcement while it is spoken.

The announcer calls `show`/`resolve` from other threads; everything AppKit happens on the main
thread via `AppHelper.callAfter`. Cards stack downward.

Two kinds of card:
- Plain: fades after reading time; clicking it dismisses it and opens the panel.
- Sticky (has questions or suggestions): stays until you close it with its ✕, reply to that Claude
  session, or the session ends. Clicking it opens the panel and leaves it up.
"""

from __future__ import annotations

import logging
from typing import Callable

from AppKit import (
    NSBackingStoreBuffered,
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
from PyObjCTools import AppHelper

from echo_os import settings
from echo_os.echo.kb_usage import KbUsage

logger = logging.getLogger(__name__)

PADDING_X = 14
PADDING_Y = 11
LINE_GAP = 4
KB_ICON_SIZE = 12
SECTION_GAP = 9
ITEM_GAP = 3
CLOSE_SIZE = 16
CLOSE_GAP = 6
BULLET = "•"
BULLET_INDENT = 14
QUESTIONS_HEADING = "Questions for you"
SUGGESTIONS_HEADING = "Suggestions"
KB_ICON_GAP = 6
CORNER_RADIUS = 12
FADE_SECONDS = 0.25

# Same tokens as the panel's styles.css.
BACKGROUND = NSColor.colorWithSRGBRed_green_blue_alpha_(22 / 255, 27 / 255, 34 / 255, 0.97)
BORDER = NSColor.colorWithWhite_alpha_(1.0, 0.26)
TEXT = NSColor.colorWithSRGBRed_green_blue_alpha_(240 / 255, 246 / 255, 252 / 255, 1.0)
MUTED = NSColor.colorWithSRGBRed_green_blue_alpha_(139 / 255, 148 / 255, 158 / 255, 1.0)
ACCENT = NSColor.colorWithSRGBRed_green_blue_alpha_(88 / 255, 166 / 255, 255 / 255, 1.0)

WARNING = NSColor.colorWithSRGBRed_green_blue_alpha_(210 / 255, 153 / 255, 34 / 255, 1.0)

# KB status in the card's top-right corner: (SF Symbol, color, label, tooltip) per KbUsage state.
KB_STATUS = {
    "used": ("book.fill", ACCENT, "KB · {notes}", "Informed by your knowledge base ({notes})"),
    "not-relevant": ("book", MUTED, "KB · nothing relevant", "Knowledge base searched; nothing relevant"),
    "needs-auth": ("lock.fill", WARNING, "KB · needs login",
                   "notes-kb needs login: in Claude Code run /mcp, pick notes-kb, Authenticate"),
    "unavailable": ("exclamationmark.triangle.fill", WARNING, "KB · unavailable",
                    "Knowledge base lookup failed (see echo-OS log)"),
    "off": ("book", MUTED.colorWithAlphaComponent_(0.6), "KB off", "Knowledge base agent is turned off"),
}


def is_sticky(announcement) -> bool:
    return bool(announcement.questions or announcement.suggestions)


def display_seconds(body: str) -> float:
    """How long a plain (non-sticky) card stays up: roughly reading time, clamped."""
    reading = len(body.split()) / settings.POPUP_READING_WORDS_PER_SECOND
    return min(settings.POPUP_MAX_SECONDS, max(settings.POPUP_MIN_SECONDS, reading + 2))


class CloseButton(NSButton):
    """Borderless ✕ that calls a Python function; it is its own target so nothing else must stay alive."""

    def initWithFrame_onClose_(self, frame, on_close):  # noqa: N802
        self = self.initWithFrame_(frame)
        if self is None:
            return None
        self.on_close = on_close
        self.setBordered_(False)
        self.setImage_(NSImage.imageWithSystemSymbolName_accessibilityDescription_("xmark", "Dismiss"))
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
    """Rounded dark card drawn in drawRect_ (no layers, so it can also be rendered to an image)."""

    def initWithFrame_onClick_(self, frame, on_click):  # noqa: N802
        self = self.initWithFrame_(frame)
        if self is None:
            return None
        self.on_click = on_click
        return self

    def isOpaque(self):  # noqa: N802
        return False

    def acceptsFirstMouse_(self, event):  # noqa: N802
        return True

    def drawRect_(self, rect):  # noqa: N802
        bounds = self.bounds()
        inset = NSMakeRect(0.5, 0.5, bounds.size.width - 1, bounds.size.height - 1)
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(inset, CORNER_RADIUS, CORNER_RADIUS)
        BACKGROUND.setFill()
        path.fill()
        BORDER.setStroke()
        path.setLineWidth_(1.0)
        path.stroke()

    def mouseDown_(self, event):  # noqa: N802
        if self.on_click is not None:
            self.on_click()


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


def _kb_status_views(usage: KbUsage) -> tuple:
    symbol, color, label_template, tooltip_template = KB_STATUS.get(usage.state, KB_STATUS["unavailable"])
    notes = f"{usage.notes} note" + ("" if usage.notes == 1 else "s")
    label_text, tooltip = label_template.format(notes=notes), tooltip_template.format(notes=notes)
    icon = NSImageView.alloc().initWithFrame_(NSMakeRect(0, 0, KB_ICON_SIZE, KB_ICON_SIZE))
    icon.setImage_(NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, tooltip))
    icon.setContentTintColor_(color)
    icon.setToolTip_(tooltip)
    label = NSTextField.labelWithString_(label_text)
    label.setFont_(NSFont.systemFontOfSize_weight_(10.5, 0.3))
    label.setTextColor_(color)
    label.setToolTip_(tooltip)
    label.sizeToFit()
    return icon, label


def _item_sections(questions: tuple[str, ...], suggestions: tuple[str, ...], width: float) -> list:
    """Labels for the bulleted sections, top to bottom: a small caps heading, then one label per item."""
    views = []
    for heading, items in ((QUESTIONS_HEADING, questions), (SUGGESTIONS_HEADING, suggestions)):
        if not items:
            continue
        views.append(("heading", _label(heading, NSFont.systemFontOfSize_weight_(10.5, 0.4), MUTED, width)))
        for item in items:
            views.append(("item", _bullet_row(item, width)))
    return views


def _bullet_row(item: str, width: float):
    """A bullet in its own column so wrapped lines hang under the text, not under the bullet."""
    font = NSFont.systemFontOfSize_(12.5)
    text = _label(item, font, TEXT, width - BULLET_INDENT)
    bullet = NSTextField.labelWithString_(BULLET)
    bullet.setFont_(font)
    bullet.setTextColor_(MUTED)
    bullet.sizeToFit()
    row = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, text.frame().size.height))
    text.setFrameOrigin_((BULLET_INDENT, 0))
    bullet.setFrameOrigin_((2, text.frame().size.height - bullet.frame().size.height))
    row.addSubview_(bullet)
    row.addSubview_(text)
    return row


def build_card(*, title: str, subtitle: str, body: str, on_click: Callable | None, kb_usage: KbUsage | None = None,
               questions: tuple[str, ...] = (), suggestions: tuple[str, ...] = (), on_close: Callable | None = None):
    """The card view, sized to its text. Separate from the window so it can be rendered offscreen.

    `on_close` adds a ✕ in the top-right corner (sticky cards).
    """
    width = settings.POPUP_WIDTH
    text_width = width - 2 * PADDING_X
    close_width = CLOSE_SIZE + CLOSE_GAP if on_close else 0
    status = _kb_status_views(kb_usage) if kb_usage is not None else None
    status_width = (KB_ICON_SIZE + 3 + status[1].frame().size.width) if status else 0
    heading_width = text_width - close_width - (status_width + KB_ICON_GAP if status else 0)
    heading = f"{title}  ·  {subtitle}" if subtitle else title
    # One line, truncated with an ellipsis: a long project name must not push the headline down.
    heading_label = NSTextField.labelWithString_(heading)
    heading_label.setFont_(NSFont.boldSystemFontOfSize_(12))
    heading_label.setTextColor_(TEXT)
    heading_label.setLineBreakMode_(NSLineBreakByTruncatingTail)
    heading_label.setFrameSize_((heading_width, heading_label.fittingSize().height))
    if subtitle:
        # Call sign in white, project muted.
        from AppKit import (NSAttributedString, NSFontAttributeName, NSForegroundColorAttributeName,
                            NSMutableAttributedString, NSMutableParagraphStyle, NSParagraphStyleAttributeName)

        # Attributed text ignores the label's line-break mode, so truncation is set on the text itself.
        truncating = NSMutableParagraphStyle.alloc().init()
        truncating.setLineBreakMode_(NSLineBreakByTruncatingTail)
        styled = NSMutableAttributedString.alloc().initWithString_attributes_(
            title, {NSFontAttributeName: NSFont.boldSystemFontOfSize_(12), NSForegroundColorAttributeName: TEXT,
                    NSParagraphStyleAttributeName: truncating})
        styled.appendAttributedString_(NSAttributedString.alloc().initWithString_attributes_(
            f"  ·  {subtitle}", {NSFontAttributeName: NSFont.systemFontOfSize_(12), NSForegroundColorAttributeName: MUTED,
                                 NSParagraphStyleAttributeName: truncating}))
        heading_label.setAttributedStringValue_(styled)
    body_label = _label(body, NSFont.systemFontOfSize_(13), TEXT, text_width)
    sections = _item_sections(questions, suggestions, text_width)

    # Stack top to bottom: heading, headline, then each section. AppKit's y grows upward, so lay out
    # from the bottom of the stack.
    stack = [heading_label, body_label] + [view for _, view in sections]
    gaps = [LINE_GAP] + [SECTION_GAP if kind == "heading" else ITEM_GAP for kind, _ in sections]
    height = PADDING_Y * 2 + sum(view.frame().size.height for view in stack) + sum(gaps)
    card = CardView.alloc().initWithFrame_onClick_(NSMakeRect(0, 0, width, height), on_click)
    y = height - PADDING_Y
    for index, view in enumerate(stack):
        if index:
            y -= gaps[index - 1]
        y -= view.frame().size.height
        view.setFrameOrigin_((PADDING_X, y))
        card.addSubview_(view)
    if status is not None:
        # Right-aligned on the heading's first line: [icon] KB · label
        icon, label = status
        heading_frame = heading_label.frame()
        middle = heading_frame.origin.y + heading_frame.size.height / 2
        label_size = label.frame().size
        label.setFrameOrigin_((width - PADDING_X - close_width - label_size.width, round(middle - label_size.height / 2)))
        icon.setFrameOrigin_((label.frame().origin.x - 3 - KB_ICON_SIZE, round(middle - KB_ICON_SIZE / 2)))
        card.addSubview_(icon)
        card.addSubview_(label)
    if on_close is not None:
        heading_frame = heading_label.frame()
        middle = heading_frame.origin.y + heading_frame.size.height / 2
        close = CloseButton.alloc().initWithFrame_onClose_(
            NSMakeRect(width - PADDING_X - CLOSE_SIZE + 3, round(middle - CLOSE_SIZE / 2), CLOSE_SIZE, CLOSE_SIZE), on_close)
        card.addSubview_(close)
    return card


class PopupPresenter:
    """Implements the announcer's Popup contract with stacked top-right cards."""

    def __init__(self, *, on_click: Callable[[], None] | None = None):
        self._on_click = on_click
        self._cards: list[tuple] = []  # (window, session_id, sticky), top to bottom

    def show(self, announcement) -> None:
        AppHelper.callAfter(self._show_on_main, announcement)

    def resolve(self, session_id: str) -> None:
        AppHelper.callAfter(self._resolve_on_main, session_id)

    def _show_on_main(self, announcement) -> None:
        sticky = is_sticky(announcement)
        logger.info("Popup show: %s%s (%d on screen)", announcement.title, " [sticky]" if sticky else "", len(self._cards))
        holder: dict = {}

        def clicked():
            if not sticky:
                self._dismiss(holder.get("window"))
            if self._on_click is not None:
                self._on_click()

        card = build_card(title=announcement.title, subtitle=announcement.subtitle, body=announcement.body,
                          on_click=clicked, kb_usage=announcement.kb_usage,
                          questions=announcement.questions, suggestions=announcement.suggestions,
                          on_close=(lambda: self._dismiss(holder.get("window"))) if sticky else None)
        window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            card.frame(), NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel, NSBackingStoreBuffered, False
        )
        holder["window"] = window
        window.setReleasedWhenClosed_(False)
        window.setLevel_(NSStatusWindowLevel)
        window.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary)
        window.setOpaque_(False)
        window.setBackgroundColor_(NSColor.clearColor())
        window.setHasShadow_(True)
        window.setHidesOnDeactivate_(False)
        window.setContentView_(card)
        window.setAlphaValue_(0.0)

        self._cards.append((window, announcement.session_id, sticky))
        self._layout()
        window.orderFrontRegardless()
        window.animator().setAlphaValue_(1.0)
        if not sticky:
            AppHelper.callLater(display_seconds(announcement.body), self._dismiss, window)

    def _resolve_on_main(self, session_id: str) -> None:
        if not session_id:
            return
        for window, card_session, sticky in list(self._cards):
            if sticky and card_session == session_id:
                logger.info("Popup resolved: session %s answered or ended", session_id[:8])
                self._dismiss(window)

    def _dismiss(self, window) -> None:
        entry = next((card for card in self._cards if card[0] is window), None)
        if entry is None:
            return
        self._cards.remove(entry)
        logger.info("Popup dismiss (%d left)", len(self._cards))
        window.animator().setAlphaValue_(0.0)
        AppHelper.callLater(FADE_SECONDS, window.orderOut_, None)
        self._layout()

    def _layout(self) -> None:
        screen = NSScreen.mainScreen()
        if screen is None:
            return
        visible = screen.visibleFrame()
        top = visible.origin.y + visible.size.height - settings.POPUP_MARGIN
        x = visible.origin.x + visible.size.width - settings.POPUP_WIDTH - settings.POPUP_MARGIN
        for window, _, _ in self._cards:
            height = window.frame().size.height
            top -= height
            window.setFrameOrigin_((x, top))
            top -= settings.POPUP_GAP
