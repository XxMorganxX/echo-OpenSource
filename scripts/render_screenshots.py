"""Renders the README images in docs/images/ from demo data.

Nothing here is a mockup: the popup cards come from `build_card`, and the panel is the real static
page in an offscreen WKWebView (the menu bar panel's engine), fed demo state by the real HTTP server.
The demo data is made up, so no session, transcript or project name of yours ends up in an image.

    ./venv/bin/python scripts/render_screenshots.py

Needs macOS; opens no visible windows and calls no model. The animated GIF also needs ffmpeg.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyProhibited,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSBitmapImageRep,
    NSCalibratedRGBColorSpace,
    NSColor,
    NSCompositingOperationSourceOver,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSGradient,
    NSGraphicsContext,
    NSImage,
    NSMakeRect,
    NSPNGFileType,
    NSShadow,
    NSString,
    NSWindow,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSDate, NSObject, NSRunLoop, NSURL, NSURLRequest
from WebKit import WKUserScript, WKUserScriptInjectionTimeAtDocumentEnd, WKWebView, WKWebViewConfiguration

from echo_os import settings
from echo_os.echo.kb_usage import KbUsage
from echo_os.menubar.app import PANEL_MARGIN, PANEL_WIDTH, SCRIPT_HANDLER_NAME, STATUS_TITLE
from echo_os.menubar.popup import (
    COUNTDOWN_HEIGHT,
    COUNTDOWN_INSET_Y,
    FADE_SECONDS,
    PADDING_X,
    SLIDE_DISTANCE,
    SLIDE_SECONDS,
    FilledView,
    build_card,
    display_seconds,
    meta_text,
)
from echo_os.server.server import create_server

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "images"
SCALE = 2  # retina-sharp PNGs
NOW = time.time()
# Card footers show the clock time a turn finished; a fixed afternoon keeps re-renders identical.
FINISHED_AT = time.mktime((2026, 10, 19, 14, 41, 0, 0, 0, -1))

# -- Demo data --------------------------------------------------------------------------------------
# Color slots: billing-svc 0 (blue), web-app 1 (green), data-pipeline 2 (purple), docs-site 3 (orange).
# Sessions whose echo is waiting on you are idle; two others are still working.

SESSIONS = [
    {"call_sign": "Alpha", "project": "billing-svc", "status": "idle", "color": 0},
    {"call_sign": "Bravo", "project": "billing-svc", "status": "working", "color": 0},
    {"call_sign": "Alpha", "project": "web-app", "status": "idle", "color": 1},
    {"call_sign": "Alpha", "project": "data-pipeline", "status": "idle", "color": 2},
    {"call_sign": "Alpha", "project": "docs-site", "status": "working", "color": 3},
]

ECHOES = [
    {
        "call_sign": "Alpha", "project": "billing-svc", "color": 0, "minutes_ago": 1,
        "duration_seconds": 12 * 60, "tool_calls": 37, "kb_notes": 2,
        "headline": "The billing refactor is done and all 42 tests pass.",
    },
    {
        "call_sign": "Alpha", "project": "web-app", "color": 1, "minutes_ago": 9,
        "duration_seconds": 18 * 60, "tool_calls": 54, "kb_notes": 0,
        "headline": "Checkout now loads in under a second. Two questions for you on screen.",
        "questions": ["Keep /cart as a redirect, or remove the route?",
                      "Ship behind the new-checkout flag, or to everyone?"],
    },
    {
        "call_sign": "Alpha", "project": "data-pipeline", "color": 2, "minutes_ago": 41,
        "duration_seconds": 26 * 60, "tool_calls": 61, "kb_notes": 3,
        "headline": "The nightly import is fixed: a timezone bug was counting Sunday rows twice. Two suggestions on screen.",
        "suggestions": ["Backfill the last 30 days of imports", "Alert when a day's row count jumps over 20%"],
    },
    {
        "call_sign": "Bravo", "project": "billing-svc", "color": 0, "minutes_ago": 130,
        "duration_seconds": 7 * 60, "tool_calls": 19, "kb_notes": 0,
        "headline": "Stripe webhooks are safe to retry now; replayed events are ignored.",
    },
]


def echo_record(index: int, echo: dict) -> dict:
    """An echo as /api/state returns it (see EchoHistory)."""
    kb = ({"relevant": True, "context": "Notes on this project from your knowledge base.",
           "sources": [f"note-{n}" for n in range(echo["kb_notes"])]}
          if echo["kb_notes"] else {"relevant": False})
    return {
        "id": f"demo{index}", "call_sign": echo["call_sign"], "project": echo["project"], "color": echo["color"],
        "created_at": NOW - echo["minutes_ago"] * 60, "duration_seconds": echo["duration_seconds"],
        "tool_calls": echo["tool_calls"], "headline": echo["headline"], "spoken_text": echo["headline"],
        "questions": echo.get("questions", []), "suggestions": echo.get("suggestions", []), "kb": kb, "error": None,
    }


class DemoApp:
    """Stands in for EchoApp behind the real server: just the read side the panel polls."""

    def state(self) -> dict:
        return {
            "sessions": [{**session, "session_id": f"s{i}", "cwd": f"~/code/{session['project']}", "pid": None,
                          "started_at": NOW - 3600, "last_event_at": NOW, "last_headline": ""}
                         for i, session in enumerate(SESSIONS)],
            "echoes": [echo_record(i, echo) for i, echo in enumerate(ECHOES)],
            "muted": False,
            "kb": {"state": "used"},
            "kb_auth": {"state": "connected", "checked_at": NOW - 60, "source": "check"},
            "thresholds": {"min_turn_seconds": settings.MIN_TURN_SECONDS, "min_tool_calls": settings.MIN_TOOL_CALLS},
            "voice": settings.VOICE_PROVIDER,
            "directory_colors": list(settings.DIRECTORY_COLORS),
        }

    def read_prompt(self) -> str:
        return ""


# -- Drawing helpers --------------------------------------------------------------------------------

def new_canvas(width: float, height: float) -> NSBitmapImageRep:
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, int(width * SCALE), int(height * SCALE), 8, 4, True, False, NSCalibratedRGBColorSpace, 0, 0)
    rep.setSize_((width, height))
    return rep


def draw_into(rep: NSBitmapImageRep, draw) -> None:
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))
    try:
        draw()
    finally:
        NSGraphicsContext.restoreGraphicsState()


def view_image(view) -> NSImage:
    """An AppKit view rendered offscreen at SCALE."""
    bounds = view.bounds()
    rep = new_canvas(bounds.size.width, bounds.size.height)
    view.cacheDisplayInRect_toBitmapImageRep_(bounds, rep)
    return rep_image(rep)


def rep_image(rep: NSBitmapImageRep) -> NSImage:
    image = NSImage.alloc().initWithSize_(rep.size())
    image.addRepresentation_(rep)
    return image


def save_png(rep: NSBitmapImageRep, name: str) -> Path:
    path = OUTPUT_DIR / name
    rep.representationUsingType_properties_(NSPNGFileType, {}).writeToFile_atomically_(str(path), True)
    print(f"wrote {path.relative_to(OUTPUT_DIR.parent.parent)} ({rep.pixelsWide()}×{rep.pixelsHigh()})")
    return path


def draw_with_shadow(image: NSImage, x: float, y: float, *, blur: float = 18, offset: float = -6, alpha: float = 0.45,
                     fraction: float = 1.0):
    shadow = NSShadow.alloc().init()
    shadow.setShadowBlurRadius_(blur)
    shadow.setShadowOffset_((0, offset))
    shadow.setShadowColor_(NSColor.colorWithWhite_alpha_(0.0, alpha))
    NSGraphicsContext.saveGraphicsState()
    shadow.set()
    image.drawInRect_fromRect_operation_fraction_(NSMakeRect(x, y, *image.size()), NSMakeRect(0, 0, 0, 0),
                                                  NSCompositingOperationSourceOver, fraction)
    NSGraphicsContext.restoreGraphicsState()


def srgb(hex_color: str, alpha: float = 1.0):
    red, green, blue = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return NSColor.colorWithSRGBRed_green_blue_alpha_(red, green, blue, alpha)


def draw_wallpaper(width: float, height: float) -> None:
    """A plain dusk gradient standing in for a desktop."""
    gradient = NSGradient.alloc().initWithColors_([srgb("#1d2b53"), srgb("#3b2f63"), srgb("#7a4b6e")])
    gradient.drawInRect_angle_(NSMakeRect(0, 0, width, height), -60)


def draw_text(text: str, x: float, y: float, *, size: float, color, weight: float = 0.0) -> float:
    attributes = {NSFontAttributeName: NSFont.systemFontOfSize_weight_(size, weight),
                  NSForegroundColorAttributeName: color}
    string = NSString.stringWithString_(text)
    string.drawAtPoint_withAttributes_((x, y), attributes)
    return string.sizeWithAttributes_(attributes).width


# -- Popup cards ------------------------------------------------------------------------------------

COUNTDOWN_WIDTH = settings.POPUP_WIDTH - 2 * PADDING_X


def card_view(echo: dict, *, voice_state: str | None, countdown_left: float | None = None):
    """A popup card for a demo echo. `countdown_left` (0–1) draws a plain card's draining bar, frozen."""
    sticky = bool(echo.get("questions") or echo.get("suggestions"))
    card = build_card(
        title=echo["call_sign"], subtitle=echo["project"], body=echo["headline"], on_click=None,
        kb_usage=KbUsage("used", notes=echo["kb_notes"]) if echo["kb_notes"] else KbUsage("not-relevant"),
        questions=tuple(echo.get("questions", ())), suggestions=tuple(echo.get("suggestions", ())),
        on_close=(lambda: None) if sticky else None,
        meta=meta_text(duration_seconds=echo["duration_seconds"], tool_calls=echo["tool_calls"],
                       finished_at=FINISHED_AT - echo["minutes_ago"] * 60),
        voice_state=voice_state, color=echo["color"],
    )
    card.countdown_bar = None
    if countdown_left is not None:
        card.countdown_bar = FilledView.alloc().initWithFrame_color_radius_(
            NSMakeRect(PADDING_X, COUNTDOWN_INSET_Y, COUNTDOWN_WIDTH * countdown_left, COUNTDOWN_HEIGHT),
            card.color.colorWithAlphaComponent_(0.55), COUNTDOWN_HEIGHT / 2)
        card.addSubview_(card.countdown_bar)
    return card


def popup_stack() -> list[NSImage]:
    """Oldest first, as the popup stacks them: two sticky cards waiting on you, then the one speaking now."""
    return [
        view_image(card_view(ECHOES[2], voice_state=None)),
        view_image(card_view(ECHOES[1], voice_state=None)),
        view_image(card_view(ECHOES[0], voice_state="speaking", countdown_left=0.62)),
    ]


# -- Panel ------------------------------------------------------------------------------------------

class PanelBridge(NSObject):
    """Registered under the panel's script handler name, so the page renders as in the menu bar panel
    (transparent ground, close button) rather than as a browser tab."""

    def userContentController_didReceiveScriptMessage_(self, controller, message):  # noqa: N802
        pass


# Freezes the session dots' pulse so the image doesn't depend on when the snapshot lands.
STILL_CSS = "*, *::before, *::after { animation: none !important; transition: none !important; }"


def run_until(predicate, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while not predicate():
        if time.time() > deadline:
            raise TimeoutError("Timed out waiting for the panel to render")
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))


def evaluate(webview, script: str):
    result: dict = {}
    webview.evaluateJavaScript_completionHandler_(script, lambda value, error: result.update(value=value, error=error))
    run_until(lambda: result)
    if result["error"] is not None:
        raise RuntimeError(f"Panel script failed: {result['error']}")
    return result["value"]


def panel_image(base_url: str) -> NSImage:
    config = WKWebViewConfiguration.alloc().init()
    controller = config.userContentController()
    bridge = PanelBridge.alloc().init()
    controller.addScriptMessageHandler_name_(bridge, SCRIPT_HANDLER_NAME)
    controller.addUserScript_(WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
        f"const s = document.createElement('style'); s.textContent = {STILL_CSS!r}; document.head.append(s);",
        WKUserScriptInjectionTimeAtDocumentEnd, True))

    # Offscreen but ordered in: WebKit only paints into a window.
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(-5000, -5000, PANEL_WIDTH, 900), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
    window.setOpaque_(False)
    window.setBackgroundColor_(NSColor.clearColor())
    webview = WKWebView.alloc().initWithFrame_configuration_(window.contentView().bounds(), config)
    webview.setValue_forKey_(False, "drawsBackground")
    window.contentView().addSubview_(webview)
    window.orderBack_(None)

    webview.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(base_url)))
    run_until(lambda: not webview.isLoading())
    run_until(lambda: evaluate(webview, "document.querySelectorAll('.echo').length") == len(ECHOES))
    height = evaluate(webview, "Math.ceil(document.querySelector('.shell').getBoundingClientRect().height)")
    window.setContentSize_((PANEL_WIDTH, height))
    webview.setFrame_(window.contentView().bounds())
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.5))

    snapshot: dict = {}
    webview.takeSnapshotWithConfiguration_completionHandler_(None, lambda image, error: snapshot.update(image=image, error=error))
    run_until(lambda: snapshot)
    window.orderOut_(None)
    if snapshot["error"] is not None:
        raise RuntimeError(f"Panel snapshot failed: {snapshot['error']}")
    # Redraw at SCALE: the snapshot comes back at the offscreen window's backing scale.
    rep = new_canvas(PANEL_WIDTH, height)
    draw_into(rep, lambda: snapshot["image"].drawInRect_(NSMakeRect(0, 0, PANEL_WIDTH, height)))
    return rep_image(rep)


# -- Scenes -----------------------------------------------------------------------------------------

MENU_BAR_HEIGHT = 26
CARD_GAP = settings.POPUP_GAP
MARGIN = settings.POPUP_MARGIN


def draw_menu_bar(width: float, height: float, *, status_x: float | None) -> None:
    """A translucent strip with the app's status item (when `status_x` is given) and a clock, for context."""
    srgb("#0d1117", 0.55).set()
    NSBezierPath.fillRect_(NSMakeRect(0, height - MENU_BAR_HEIGHT, width, MENU_BAR_HEIGHT))
    baseline = height - MENU_BAR_HEIGHT + 5
    if status_x is not None:
        srgb("#ffffff", 0.16).set()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(status_x - 8, height - MENU_BAR_HEIGHT + 3, 50, MENU_BAR_HEIGHT - 6), 5, 5).fill()
        draw_text(STATUS_TITLE, status_x, baseline, size=13, color=srgb("#ffffff"), weight=0.3)
    draw_text("Mon 2:42 PM", width - 96, baseline, size=13, color=srgb("#ffffff", 0.9), weight=0.2)


def stack_heights(cards: list[NSImage]) -> float:
    return sum(card.size().height for card in cards) + CARD_GAP * (len(cards) - 1)


def draw_stack(cards: list[NSImage], *, right: float, top: float) -> None:
    y = top
    for card in cards:
        width, height = card.size()
        y -= height
        draw_with_shadow(card, right - width, y)
        y -= CARD_GAP


def hero(cards: list[NSImage], panel: NSImage) -> None:
    """The desktop as you'd see it: the panel open under the menu bar item, popups stacked top-right."""
    panel_width, panel_height = panel.size()
    width = 920
    height = MENU_BAR_HEIGHT + max(stack_heights(cards) + MARGIN, panel_height) + 36
    panel_right = width - settings.POPUP_WIDTH - 2 * MARGIN - 28
    rep = new_canvas(width, height)

    def draw():
        draw_wallpaper(width, height)
        draw_menu_bar(width, height, status_x=panel_right - panel_width / 2 - 18)
        top = height - MENU_BAR_HEIGHT
        draw_with_shadow(panel, panel_right - panel_width, top - panel_height, blur=24, alpha=0.35)
        draw_stack(cards, right=width - MARGIN, top=top - MARGIN)

    draw_into(rep, draw)
    save_png(rep, "hero.png")


# -- Animated popups --------------------------------------------------------------------------------
# One loop of the corner: a card waiting on you is already up; an echo with questions slides in and is
# spoken, then a plain echo slides in and is spoken while its countdown drains. You reply to the first
# session, so its card closes; the plain card fades when its countdown ends. The loop ends where it began.

GIF_FPS = 20  # GIF delays are in hundredths of a second, so 20 fps is exact
WAVEFORM_PERIOD = 1.0  # seconds per sweep of the speaking waveform
INDICATOR_FADE_SECONDS = 0.25  # the voice indicator fades out when speech ends


@dataclass(frozen=True)
class Appearance:
    """One card's life in the loop. `enters` None means it's already up when the loop starts."""

    echo: dict
    enters: float | None
    leaves: float | None
    speaks_until: float | None = None
    countdown: float | None = None


PLAIN_SECONDS = display_seconds(ECHOES[0]["headline"])
GIF_TIMELINE = (
    Appearance(ECHOES[2], enters=None, leaves=None),
    Appearance(ECHOES[1], enters=0.6, leaves=6.4, speaks_until=3.0),
    Appearance(ECHOES[0], enters=3.4, leaves=3.4 + PLAIN_SECONDS, speaks_until=5.6, countdown=PLAIN_SECONDS),
)
GIF_SECONDS = 3.4 + PLAIN_SECONDS + FADE_SECONDS + 0.6
GIF_EVENTS = sorted({t for a in GIF_TIMELINE for t in (a.enters, a.leaves) if t is not None})


def ease(progress: float) -> float:
    """NSAnimationContext's default ease-in-ease-out, near enough."""
    progress = min(1.0, max(0.0, progress))
    return 0.5 - 0.5 * math.cos(math.pi * progress)


def in_layout(appearance: Appearance, t: float) -> bool:
    """A card holds a place in the stack from when it enters until it's dismissed (it fades out of place)."""
    return ((appearance.enters is None or appearance.enters <= t)
            and (appearance.leaves is None or t < appearance.leaves))


def target_top(appearance: Appearance, t: float, heights: dict, top: float) -> float:
    """Where the card's top edge belongs at time t; a card that has left keeps its last place."""
    if not in_layout(appearance, t):
        return target_top(appearance, appearance.leaves - 1e-6, heights, top)
    for other in GIF_TIMELINE:
        if other is appearance:
            return top
        if in_layout(other, t):
            top -= heights[id(other)] + CARD_GAP
    raise ValueError("appearance not in the timeline")


def card_top(appearance: Appearance, t: float, heights: dict, top: float) -> float:
    """Cards glide to their new place over SLIDE_SECONDS whenever the stack changes."""
    now = target_top(appearance, t, heights, top)
    changed = [event for event in GIF_EVENTS if event <= t and event != appearance.enters]
    if not changed or t - changed[-1] >= SLIDE_SECONDS:
        return now
    before = target_top(appearance, changed[-1] - 1e-6, heights, top)
    return before + (now - before) * ease((t - changed[-1]) / SLIDE_SECONDS)


def card_alpha_and_shift(appearance: Appearance, t: float) -> tuple[float, float]:
    """Opacity and the sideways slide: entering cards slide in from the right while fading in."""
    if appearance.enters is not None:
        if t < appearance.enters:
            return 0.0, 0.0
        progress = ease((t - appearance.enters) / SLIDE_SECONDS)
        if progress < 1:
            return progress, SLIDE_DISTANCE * (1 - progress)
    if appearance.leaves is not None and t >= appearance.leaves:
        return max(0.0, 1 - (t - appearance.leaves) / FADE_SECONDS), 0.0
    return 1.0, 0.0


def update_card(card, appearance: Appearance, t: float) -> None:
    """Moves the live parts of a card to time t: the waveform sweep and the countdown bar."""
    if appearance.speaks_until is not None:
        indicator = card.voice_indicator
        if t < appearance.speaks_until:
            level = ((t - (appearance.enters or 0)) / WAVEFORM_PERIOD) % 1.0
            indicator.setImage_(NSImage.imageWithSystemSymbolName_variableValue_accessibilityDescription_(
                "waveform", level, "Speaking"))
            indicator.setContentTintColor_(card.color)
        else:
            indicator.setImage_(NSImage.imageWithSystemSymbolName_variableValue_accessibilityDescription_(
                "waveform", 1.0, "Speaking"))
            fade = max(0.0, 1 - (t - appearance.speaks_until) / INDICATOR_FADE_SECONDS)
            indicator.setContentTintColor_(card.color.colorWithAlphaComponent_(fade))
    if card.countdown_bar is not None:
        left = max(0.0, 1 - (t - appearance.enters) / appearance.countdown)
        card.countdown_bar.setFrameSize_((COUNTDOWN_WIDTH * left, COUNTDOWN_HEIGHT))


def popups_gif() -> None:
    """Renders the loop frame by frame and encodes it with ffmpeg (skipped, with a note, without it)."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        print("skipped docs/images/popups.gif: ffmpeg not found (brew install ffmpeg)")
        return
    cards = {id(a): card_view(a.echo, voice_state="speaking" if a.speaks_until is not None else None,
                              countdown_left=1.0 if a.countdown is not None else None)
             for a in GIF_TIMELINE}
    heights = {key: card.bounds().size.height for key, card in cards.items()}
    pad = 20
    width = settings.POPUP_WIDTH + MARGIN + pad
    height = MENU_BAR_HEIGHT + MARGIN + sum(heights.values()) + CARD_GAP * (len(heights) - 1) + pad
    top = height - MENU_BAR_HEIGHT - MARGIN
    right = width - MARGIN

    with tempfile.TemporaryDirectory() as frames:
        for index in range(round(GIF_SECONDS * GIF_FPS)):
            t = index / GIF_FPS
            rep = new_canvas(width, height)

            def draw():
                draw_wallpaper(width, height)
                draw_menu_bar(width, height, status_x=None)
                for appearance in GIF_TIMELINE:
                    alpha, shift = card_alpha_and_shift(appearance, t)
                    if alpha <= 0:
                        continue
                    card = cards[id(appearance)]
                    update_card(card, appearance, t)
                    image = view_image(card)
                    y = card_top(appearance, t, heights, top) - image.size().height
                    draw_with_shadow(image, right - image.size().width + shift, y, fraction=alpha)

            draw_into(rep, draw)
            rep.representationUsingType_properties_(NSPNGFileType, {}).writeToFile_atomically_(
                f"{frames}/frame_{index:04d}.png", True)

        output = OUTPUT_DIR / "popups.gif"
        # One palette for the whole loop; ordered dithering keeps still pixels identical between frames,
        # and diff_mode re-encodes only the rectangle that changed, which keeps the file small.
        subprocess.run([
            ffmpeg, "-loglevel", "error", "-y", "-framerate", str(GIF_FPS), "-i", f"{frames}/frame_%04d.png",
            "-vf", "split[a][b];[a]palettegen=stats_mode=full[p];[b][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle",
            "-loop", "0", str(output),
        ], check=True)
    print(f"wrote {output.relative_to(OUTPUT_DIR.parent.parent)} ({round(GIF_SECONDS * GIF_FPS)} frames, "
          f"{output.stat().st_size // 1024} KB)")


def main() -> None:
    application = NSApplication.sharedApplication()
    application.setActivationPolicy_(NSApplicationActivationPolicyProhibited)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    server = create_server(DemoApp(), host="127.0.0.1", port=0)
    threading.Thread(target=server.serve_forever, name="demo-server", daemon=True).start()
    try:
        panel = panel_image(f"http://127.0.0.1:{server.server_address[1]}/")
    finally:
        server.shutdown()

    cards = popup_stack()
    hero(cards, panel)
    popups_gif()


if __name__ == "__main__":
    main()
