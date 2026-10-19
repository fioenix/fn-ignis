"""Bind the in-process MCP server's caller root for a test.

The caller root is the folder the agent was opened in: the server's working directory at startup.
In-process tests share one imported server whose startup folder is the pytest working directory,
so each test binds a temporary folder as if the agent had been opened there.
"""
from pathlib import Path


def bind_caller_root(monkeypatch, root):
    """Make the imported server resolve ``root`` as the folder the agent was opened in."""
    from ignis.infrastructure.caller_storage import CallerStorageMiddleware, _directory_identities
    from ignis.interfaces.mcp import server
    root = Path(root)
    bound = False
    for middleware in server.mcp.middleware:
        if isinstance(middleware, CallerStorageMiddleware):
            monkeypatch.setattr(middleware, '_configured_present', False)
            monkeypatch.setattr(middleware, '_startup_refused', False)
            monkeypatch.setattr(middleware, '_startup_root', root)
            monkeypatch.setattr(middleware, '_startup_identities', _directory_identities(root))
            bound = True
    if not bound:
        raise AssertionError('The server has no caller-storage middleware')
    return root
