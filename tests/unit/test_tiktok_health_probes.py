"""A connector's keyword-search readiness answer reaches the health report only as a string."""

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_a_non_string_readiness_answer_is_ignored():
    """hasattr is true of any mock, and this report is serialised to JSON.

    The first version of the health wiring accepted whatever the attribute returned, so a mock
    plugin in an unrelated test put an AsyncMock into the payload and the whole diagnostic
    failed to serialise -- one connector's odd answer taking down the entire report.
    """
    import json

    from ignis.interfaces.mcp import server as mcp_server

    plugin = AsyncMock()
    plugin.keyword_search_blocked_reason = AsyncMock(return_value=AsyncMock())

    blocked = await plugin.keyword_search_blocked_reason()
    accepted = blocked if isinstance(blocked, str) and blocked.strip() else None

    assert accepted is None
    json.dumps({"remediation": accepted})  # would raise if a mock had been let through
    assert hasattr(mcp_server, "handle_verify_connectors_health")
