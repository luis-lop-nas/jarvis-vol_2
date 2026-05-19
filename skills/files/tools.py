"""Herramientas del skill files.

Las implementaciones residen en mcp_servers/server_filesystem.py y se ejecutan
a través del MCPBus protegido por security/sandbox.py.

Ejemplo::
    from skills.files.tools import TOOLS
    assert TOOLS == {}  # Herramientas en MCPBus
"""

TOOLS: dict = {}
