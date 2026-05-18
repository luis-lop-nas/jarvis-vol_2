"""Entrada CLI para `python -m mcp_servers`."""

from __future__ import annotations

import asyncio

from mcp_servers.stdio_server import main


if __name__ == "__main__":
    asyncio.run(main())
