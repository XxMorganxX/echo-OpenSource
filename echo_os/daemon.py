"""Runs echo-OS without the menu bar (for development, or a machine where you don't want the icon)."""

from __future__ import annotations

import argparse
import logging

from echo_os import settings
from echo_os.app import build_app
from echo_os.server.server import create_server


def main() -> None:
    parser = argparse.ArgumentParser(description="echo-OS daemon without the menu bar")
    parser.add_argument("--port", type=int, default=settings.SERVER_PORT)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    app = build_app()
    app.start()
    server = create_server(app, host=settings.SERVER_HOST, port=args.port)
    logging.getLogger(__name__).info("echo-OS listening on http://%s:%d", settings.SERVER_HOST, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.stop()


if __name__ == "__main__":
    main()
