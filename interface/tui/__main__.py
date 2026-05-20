"""Entry point: python -m interface.tui [--url WS_URL]"""
from __future__ import annotations

import argparse
import logging

from .app import JARVISTui


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS TUI")
    parser.add_argument(
        "--url",
        default="ws://127.0.0.1:8765/ws",
        help="URL WebSocket del backend (default: ws://127.0.0.1:8765/ws)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Activar logging DEBUG",
    )
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    app = JARVISTui(api_url=args.url)
    app.run()


if __name__ == "__main__":
    main()
