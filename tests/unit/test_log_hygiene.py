"""API keys travel in query strings, and an HTTP client that logs request URLs leaks them.

httpx logs every request at INFO, including the full URL. Several connectors authenticate with
a key in the query string (`youtube/v3/search?...&key=...`), so an operator running the worker
at INFO writes their own credential into container logs, terminal scrollback and CI output.

Only the worker calls `basicConfig`. The MCP server leaves the root logger alone, so httpx sits
at its WARNING default there -- verified against the real Claude Desktop log, which holds no
`HTTP Request:` lines and no `key=` at all.
"""

import logging

import pytest


@pytest.mark.parametrize("module", ["ignis.interfaces.cli.scheduler"])
def test_entrypoints_keep_request_urls_out_of_the_log(module):
    __import__(module)
    for name in ("httpx", "httpcore"):
        # The logger's own level, not the effective one: pytest installs its own root handler,
        # so an effective-level assertion would pass here and still leak in production.
        level = logging.getLogger(name).level
        assert level >= logging.WARNING, (
            f"{module} does not raise {name} above {logging.getLevelName(level) or 'NOTSET'}; "
            f"request URLs carry API keys in their query string."
        )
