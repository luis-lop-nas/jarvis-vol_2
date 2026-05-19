"""Herramientas del skill terminal.

Las implementaciones residen en mcp_servers/server_code.py y se protegen
mediante security/sandbox.py.

Ejemplo::
    from skills.terminal.tools import TOOLS
    assert TOOLS == {}  # Herramientas en MCPBus
"""

TOOLS: dict = {}
