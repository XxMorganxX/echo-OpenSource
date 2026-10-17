"""Top-right popup cards that show each announcement while it is spoken.

The announcer calls `show` from its own thread; everything AppKit happens on the main thread via
`AppHelper.callAfter`. Cards stack downward when a new one arrives before the last has gone, and
clicking one dismisses it and opens the panel.
"""

from __future__ import annotations

import logging
from typing import Callable

from AppKit import (
    NSBackingStoreBuffered,
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

logger = logging.getLogger(__name__)

PADDING_X = 14
PADDING_Y = 11
LINE_GAP = 4
CORNER_RADIUS = 12
FADE_SECONDS = 0.25

# Same tokens as the panel's styles.css.
BACKGROUND = NSColor.colorWithSRGBRed_green_blue_alpha_(22 / 255, 27 / 255, 34 / 255, 0.97)
BORDER = NSColor.colorWithWhite_alpha_(1.0, 0.26)
TEXT = NSColor.colorWithSRGBRed_green_blue_alpha_(240 / 255, 246 / 255, 252 / 255, 1.0)
MUTED = NSColor.colorWithSRGBRed_green_blue_alpha_(139 / 255, 148 / 255, 158 / 255, 1.0)


def display_seconds(body: str) -> float:
    reading = len(body.split()) / settings.POPUP_READING_WORDS_PER_SECOND
    return min(settings.POPUP_MAX_SECONDS, max(settings.POPUP_MIN_SECONDS, reading + 2))


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
    size = field.fittingSize()
    field.setFrameSize_((width, size.height))
    return field


def build_card(*, title: str, subtitle: str, body: str, on_click: Callable | None):
    """The card view, sized to its text. Separate from the window so it can be rendered offscreen."""
    width = settings.POPUP_WIDTH
    text_width = width - 2 * PADDING_X
    heading = f"{title}  ·  {subtitle}" if subtitle else title
    heading_label = _label(heading, NSFont.boldSystemFontOfSize_(12), TEXT, text_width)
    if subtitle:
        # Call sign in white, project muted.
        from AppKit import NSAttributedString, NSFontAttributeName, NSForegroundColorAttributeName, NSMutableAttributedString

        styled = NSMutableAttributedString.alloc().initWithString_attributes_(
            title, {NSFontAttributeName: NSFont.boldSystemFontOfSize_(12), NSForegroundColorAttributeName: TEXT})
        styled.appendAttributedString_(NSAttributedString.alloc().initWithString_attributes_(
            f"  ·  {subtitle}", {NSFontAttributeName: NSFont.systemFontOfSize_(12), NSForegroundColorAttributeName: MUTED}))
        heading_label.setAttributedStringValue_(styled)
    body_label = _label(body, NSFont.systemFontOfSize_(13), TEXT, text_width)

    height = PADDING_Y + heading_label.frame().size.height + LINE_GAP + body_label.frame().size.height + PADDING_Y
    card = CardView.alloc().initWithFrame_onClick_(NSMakeRect(0, 0, width, height), on_click)
    body_label.setFrameOrigin_((PADDING_X, PADDING_Y))
    heading_label.setFrameOrigin_((PADDING_X, PADDING_Y + body_label.frame().size.height + LINE_GAP))
    card.addSubview_(heading_label)
    card.addSubview_(body_label)
    return card


class PopupPresenter:
    """Implements the announcer's Popup contract with stacked top-right cards."""

    def __init__(self, *, on_click: Callable[[], None] | None = None):
        self._on_click = on_click
        self._windows: list = []

    def show(self, *, title: str, subtitle: str, body: str) -> None:
        AppHelper.callAfter(self._show_on_main, title, subtitle, body)

    def _show_on_main(self, title: str, subtitle: str, body: str) -> None:
        logger.info("Popup show: %s (%d on screen)", title, len(self._windows))
        holder: dict = {}

        def clicked():
            self._dismiss(holder.get("window"))
            if self._on_click is not None:
                self._on_click()

        card = build_card(title=title, subtitle=subtitle, body=body, on_click=clicked)
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

        self._windows.append(window)
        self._layout()
        window.orderFrontRegardless()
        window.animator().setAlphaValue_(1.0)
        AppHelper.callLater(display_seconds(body), self._dismiss, window)

    def _dismiss(self, window) -> None:
        if window is None or window not in self._windows:
            return
        self._windows.remove(window)
        logger.info("Popup dismiss (%d left)", len(self._windows))
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
        for window in self._windows:
            height = window.frame().size.height
            top -= height
            window.setFrameOrigin_((x, top))
            top -= settings.POPUP_GAP
