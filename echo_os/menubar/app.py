"""Native macOS menu bar app: a status item that toggles a small floating panel, plus popups.

Adapted from the to-do app's menu bar wrapper. The app also hosts the echo-OS daemon (server,
worker, speech), unless one is already answering on the port, in which case it only shows the
panel for that one.
"""

from __future__ import annotations

import argparse
import logging
import threading
import urllib.error
import urllib.request

import objc
from AppKit import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSColor,
    NSFloatingWindowLevel,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSPanel,
    NSScreen,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSView,
    NSViewHeightSizable,
    NSViewWidthSizable,
    NSWindowCollectionBehaviorMoveToActiveSpace,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSDistributedNotificationCenter, NSObject, NSURL, NSURLRequest
from PyObjCTools import AppHelper
from WebKit import WKWebView, WKWebViewConfiguration

from echo_os import settings
from echo_os.echo.preferences import Preferences
from echo_os.menubar.popup import PopupPresenter
from echo_os.terminal_focus import focus_session

APP_NAME = "Echo"
STATUS_TITLE = "Echo"
PANEL_WIDTH = 380
PANEL_HEIGHT = 540
PANEL_MARGIN = 12
HEADER_DRAG_LEFT_INSET = 14
HEADER_DRAG_TOP_INSET = 12
HEADER_DRAG_HEIGHT = 40
HEADER_DRAG_RIGHT_INSET = 120
SCRIPT_HANDLER_NAME = "echoPanel"

logger = logging.getLogger(__name__)


class HeaderDragView(NSView):
    """Transparent native drag area layered above the web header."""

    def isOpaque(self):  # noqa: N802
        return False

    def mouseDownCanMoveWindow(self):  # noqa: N802
        return True

    def acceptsFirstMouse_(self, event):  # noqa: N802
        return True

    def mouseDown_(self, event):  # noqa: N802
        window = self.window()
        if window is not None:
            window.performWindowDragWithEvent_(event)


class FloatingPanel(NSPanel):
    """Borderless floating panel that can still take keyboard focus (for the prompt editor)."""

    def canBecomeKeyWindow(self):  # noqa: N802
        return True

    def canBecomeMainWindow(self):  # noqa: N802
        return True


class DaemonRuntime:
    """Starts the embedded echo-OS service unless another instance already serves the port."""

    def __init__(self, host: str, port: int, popup=None, preferences=None):
        self.base_url = f"http://{host}:{port}"
        self.host, self.port = host, port
        self.popup, self.preferences = popup, preferences
        self.app = None
        self.server = None

    def ensure_ready(self) -> str:
        if self._healthy():
            logger.info("echo-OS already running at %s; showing its panel only", self.base_url)
            return self.base_url
        from echo_os.app import build_app
        from echo_os.server.server import create_server

        self.app = build_app(popup=self.popup, preferences=self.preferences)
        self.app.start()
        self.server = create_server(self.app, host=self.host, port=self.port)
        threading.Thread(target=self.server.serve_forever, name="echo-http", daemon=True).start()
        logger.info("echo-OS listening on %s", self.base_url)
        return self.base_url

    def shutdown(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.app is not None:
            self.app.stop()

    def _healthy(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/health", timeout=1.0) as response:
                return response.status == 200
        except (urllib.error.URLError, TimeoutError, ValueError, ConnectionError):
            return False


class EchoMenubarApp(NSObject):
    def initWithShowOnLaunch_(self, show_on_launch: bool):  # noqa: N802
        self = objc.super(EchoMenubarApp, self).init()
        if self is None:
            return None
        self.show_on_launch = show_on_launch
        preferences = Preferences(settings.PREFERENCES_PATH)
        popup = (PopupPresenter(on_click=self._go_to_session, preferences=preferences)
                 if settings.POPUP_ENABLED else None)
        self.runtime = DaemonRuntime(settings.SERVER_HOST, settings.SERVER_PORT, popup=popup, preferences=preferences)
        self.status_item = None
        self.window = None
        self.webview = None
        self.drag_view = None
        self.last_window_frame = None
        return self

    # -- Lifecycle ---------------------------------------------------------------------------------
    def applicationDidFinishLaunching_(self, notification):  # noqa: N802
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        base_url = self.runtime.ensure_ready()
        self._build_main_menu()
        self._build_status_item()
        self._build_window()
        self._register_remote_notifications()
        self.webview.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(base_url + "/")))
        if self.show_on_launch:
            self.showWindow_(None)

    def applicationWillTerminate_(self, notification):  # noqa: N802
        NSDistributedNotificationCenter.defaultCenter().removeObserver_(self)
        self.runtime.shutdown()

    def applicationShouldTerminateAfterLastWindowClosed_(self, application):  # noqa: N802
        return False

    # -- Panel bridge and remote control -------------------------------------------------------------
    def userContentController_didReceiveScriptMessage_(self, controller, message):  # noqa: N802
        if message.body() == "hide":
            self.hideWindow_(None)

    def remoteToggle_(self, notification):  # noqa: N802
        self.toggleWindow_(None)

    def remoteShow_(self, notification):  # noqa: N802
        self.showWindow_(None)

    def _register_remote_notifications(self) -> None:
        center = NSDistributedNotificationCenter.defaultCenter()
        center.addObserver_selector_name_object_(self, "remoteToggle:", settings.MENUBAR_TOGGLE_NOTIFICATION, None)
        center.addObserver_selector_name_object_(self, "remoteShow:", settings.MENUBAR_SHOW_NOTIFICATION, None)

    @objc.python_method
    def _go_to_session(self, announcement) -> None:
        """Popup click: the session's terminal tab, or the panel when there is none to go to.
        Off the main thread because osascript can take a moment (longer on the first Automation prompt)."""
        def focus():
            if not focus_session(announcement.pid):
                AppHelper.callAfter(self.showWindow_, None)

        threading.Thread(target=focus, name="echo-focus", daemon=True).start()

    # -- Window ------------------------------------------------------------------------------------
    def windowShouldClose_(self, sender):  # noqa: N802
        self.hideWindow_(None)
        return False

    def windowDidResize_(self, notification):  # noqa: N802
        self._layout_drag_region()
        self._remember_window_frame()

    def windowDidMove_(self, notification):  # noqa: N802
        self._remember_window_frame()

    def toggleWindow_(self, sender):  # noqa: N802
        if self.window.isVisible() and self._is_on_active_space():
            self.hideWindow_(sender)
        else:
            self.showWindow_(sender)

    def showWindow_(self, sender):  # noqa: N802
        if self.window.isVisible() and not self._is_on_active_space():
            self.window.orderOut_(None)
            self._position_window()
        elif self.last_window_frame is None:
            self._position_window()
        else:
            self.window.setFrame_display_animate_(self.last_window_frame, True, False)
        self.webview.reload()
        self.window.makeKeyAndOrderFront_(None)
        self.window.orderFrontRegardless()
        NSApp.activateIgnoringOtherApps_(True)

    def hideWindow_(self, sender):  # noqa: N802
        self._remember_window_frame()
        self.window.orderOut_(None)

    def openInBrowser_(self, sender):  # noqa: N802
        import webbrowser

        webbrowser.open(self.runtime.base_url)

    def _build_main_menu(self) -> None:
        main_menu = NSMenu.alloc().init()
        app_menu_item = NSMenuItem.alloc().init()
        main_menu.addItem_(app_menu_item)
        app_menu = NSMenu.alloc().init()
        for title, action, key in (("Toggle Echo", "toggleWindow:", "e"), ("Open In Browser", "openInBrowser:", "b")):
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
            item.setTarget_(self)
            app_menu.addItem_(item)
        app_menu.addItem_(NSMenuItem.separatorItem())
        app_menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(f"Quit {APP_NAME}", "terminate:", "q"))
        app_menu_item.setSubmenu_(app_menu)

        # Standard edit menu so copy/paste/select-all work in the prompt editor.
        edit_menu_item = NSMenuItem.alloc().init()
        main_menu.addItem_(edit_menu_item)
        edit_menu = NSMenu.alloc().initWithTitle_("Edit")
        for title, action, key in (("Undo", "undo:", "z"), ("Redo", "redo:", "Z"), ("Cut", "cut:", "x"),
                                   ("Copy", "copy:", "c"), ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")):
            edit_menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key))
        edit_menu_item.setSubmenu_(edit_menu)
        NSApp.setMainMenu_(main_menu)

    def _build_status_item(self) -> None:
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        button = self.status_item.button()
        button.setTitle_(STATUS_TITLE)
        button.setToolTip_("Toggle Echo")
        button.setTarget_(self)
        button.setAction_("toggleWindow:")

    def _build_window(self) -> None:
        self.window = FloatingPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, PANEL_WIDTH, PANEL_HEIGHT), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
        )
        self.window.setReleasedWhenClosed_(False)
        self.window.setLevel_(NSFloatingWindowLevel)
        self.window.setMovableByWindowBackground_(True)
        self.window.setHidesOnDeactivate_(False)
        self.window.setDelegate_(self)
        self.window.setCollectionBehavior_(self.window.collectionBehavior() | NSWindowCollectionBehaviorMoveToActiveSpace)
        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(NSColor.clearColor())
        self.window.setHasShadow_(False)

        wk_config = WKWebViewConfiguration.alloc().init()
        wk_config.userContentController().addScriptMessageHandler_name_(self, SCRIPT_HANDLER_NAME)
        self.webview = WKWebView.alloc().initWithFrame_configuration_(self.window.contentView().bounds(), wk_config)
        self.webview.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self.webview.setValue_forKey_(False, "drawsBackground")
        self.window.contentView().addSubview_(self.webview)

        self.drag_view = HeaderDragView.alloc().initWithFrame_(NSMakeRect(0, 0, 0, 0))
        self.drag_view.setAutoresizingMask_(NSViewWidthSizable)
        self.window.contentView().addSubview_(self.drag_view)
        self._layout_drag_region()

    def _layout_drag_region(self) -> None:
        if self.window is None or self.drag_view is None:
            return
        bounds = self.window.contentView().bounds()
        width = max(80, bounds.size.width - HEADER_DRAG_LEFT_INSET - HEADER_DRAG_RIGHT_INSET)
        y = max(0, bounds.size.height - HEADER_DRAG_TOP_INSET - HEADER_DRAG_HEIGHT)
        self.drag_view.setFrame_(NSMakeRect(HEADER_DRAG_LEFT_INSET, y, width, HEADER_DRAG_HEIGHT))

    def _is_on_active_space(self) -> bool:
        try:
            return bool(self.window.isOnActiveSpace())
        except Exception:
            return True

    def _remember_window_frame(self) -> None:
        frame = self.window.frame()
        self.last_window_frame = NSMakeRect(frame.origin.x, frame.origin.y, frame.size.width, frame.size.height)

    def _position_window(self) -> None:
        screen = NSScreen.mainScreen()
        if screen is None:
            return
        visible = screen.visibleFrame()
        frame = self.window.frame()
        x = visible.origin.x + visible.size.width - frame.size.width - PANEL_MARGIN
        y = visible.origin.y + visible.size.height - frame.size.height
        target = NSMakeRect(x, y, frame.size.width, frame.size.height)
        self.window.setFrame_display_animate_(target, True, False)
        self.last_window_frame = target


def main() -> None:
    parser = argparse.ArgumentParser(description="echo-OS menu bar app")
    parser.add_argument("--show", action="store_true", help="Show the panel on launch.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    app = NSApplication.sharedApplication()
    delegate = EchoMenubarApp.alloc().initWithShowOnLaunch_(args.show)
    app.setDelegate_(delegate)
    app.run()
