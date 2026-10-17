"""Localhost HTTP server: hook ingress, the panel's JSON API, and the panel's static files.

Same shape as the to-do app's overlay server (stdlib ThreadingHTTPServer). Two guards keep other
web pages out: the Host header must be loopback (DNS rebinding), and every write must be
`application/json` (a cross-site page can't send that without a CORS preflight, which is never
granted).
"""

from __future__ import annotations

import json
import logging
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from echo_os.app import EchoApp

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_FILES = {"/": ("index.html", "text/html"), "/styles.css": ("styles.css", "text/css"),
                "/app.js": ("app.js", "text/javascript")}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}
MAX_BODY_BYTES = 2_000_000
REPLAY_ROUTE = re.compile(r"^/api/echoes/([A-Za-z0-9]+)/replay$")


class EchoServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], app: EchoApp):
        super().__init__(address, EchoRequestHandler)
        self.app = app


class EchoRequestHandler(BaseHTTPRequestHandler):
    server: EchoServer

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        logger.debug("%s - %s", self.address_string(), format % args)

    # -- Verbs -------------------------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return
        path = urlparse(self.path).path
        if path == "/api/health":
            return self._json({"ok": True})
        if path == "/api/state":
            return self._json(self.server.app.state())
        if path == "/api/prompt":
            return self._json({"prompt": self.server.app.read_prompt()})
        if path in STATIC_FILES:
            return self._static(*STATIC_FILES[path])
        if path == "/favicon.ico":
            return self._no_content()
        self._error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        body = self._json_body()
        if body is None:
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/hook":
            query = parse_qs(parsed.query)
            pid_raw = (query.get("pid") or [""])[0]
            self.server.app.handle_hook(
                body, entrypoint=(query.get("entrypoint") or [""])[0], pid=int(pid_raw) if pid_raw.isdigit() else None
            )
            return self._no_content()
        if parsed.path == "/api/mute":
            muted = bool(body.get("muted"))
            self.server.app.pipeline.preferences.set_muted(muted)
            return self._json({"muted": muted})
        if match := REPLAY_ROUTE.match(parsed.path):
            if self.server.app.pipeline.replay(match.group(1)):
                return self._json({"ok": True})
            return self._error(HTTPStatus.NOT_FOUND)
        self._error(HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:  # noqa: N802
        body = self._json_body()
        if body is None:
            return
        if urlparse(self.path).path != "/api/prompt":
            return self._error(HTTPStatus.NOT_FOUND)
        try:
            self.server.app.write_prompt(str(body.get("prompt", "")))
        except ValueError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        self._json({"prompt": self.server.app.read_prompt()})

    # -- Helpers -----------------------------------------------------------------------------------
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        if host in LOOPBACK_HOSTS:
            return True
        self._error(HTTPStatus.FORBIDDEN, "Host not allowed")
        return False

    def _json_body(self) -> dict | None:
        if not self._host_ok():
            return None
        if self.headers.get_content_type() != "application/json":
            self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Send application/json")
            return None
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return None
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._error(HTTPStatus.BAD_REQUEST, "Invalid JSON")
            return None
        if not isinstance(body, dict):
            self._error(HTTPStatus.BAD_REQUEST, "Expected a JSON object")
            return None
        return body

    def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _static(self, filename: str, content_type: str) -> None:
        data = (STATIC_DIR / filename).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _no_content(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def _error(self, status: HTTPStatus, message: str | None = None) -> None:
        self._json({"error": message or status.phrase}, status)


def create_server(app: EchoApp, *, host: str, port: int) -> EchoServer:
    return EchoServer((host, port), app)
