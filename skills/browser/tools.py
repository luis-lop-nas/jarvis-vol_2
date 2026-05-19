"""Herramientas del skill browser.

Las implementaciones residen en mcp_servers/server_browser.py y se ejecutan
a través del MCPBus. Este módulo no expone callables adicionales.

Ejemplo::
    from skills.browser.tools import TOOLS
    assert TOOLS == {}  # Herramientas en MCPBus
"""

TOOLS: dict = {}
