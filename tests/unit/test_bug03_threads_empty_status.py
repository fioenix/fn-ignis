import json
from unittest.mock import patch
import pytest

from ignis.interfaces.mcp.server import (
    handle_get_threads_trending_topics,
    handle_get_threads_search_suggestions,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("handler,args,count,rows", [
    (handle_get_threads_trending_topics, {}, "total_topics", "topics"),
    (handle_get_threads_search_suggestions, {"keyword": "synthetic"}, "total_suggestions", "suggestions")])
async def test_retired_threads_tools_are_unavailable_without_touching_credentials(handler, args, count, rows):
    with patch("ignis.interfaces.mcp.server.get_components", side_effect=AssertionError("Retired tool read credentials")):
        response = json.loads(await handler(**args))
    assert response["status"] == "UNAVAILABLE" and response["reason_code"] == "HOST_BROWSER_REQUIRED"
    assert response[count] == 0 and response[rows] == []
